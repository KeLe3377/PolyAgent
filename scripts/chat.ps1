[CmdletBinding()]
param(
    [string]$Domain = "financial",
    [string]$Mode = "deliberation",
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [switch]$NoAutoStart,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

if ($Help) {
    @"
PolyAgent interactive chat

Usage:
  .\chat.cmd
  .\chat.cmd -Domain kb_qa -Mode react
  .\chat.cmd -Domain financial -Mode deliberation

Commands inside chat:
  /domain NAME       switch domain, e.g. /domain kb_qa
  /mode NAME         switch mode: react | plan_execute | deliberation
  /reset             clear local message history
  /exit              quit

Defaults:
  Domain=$Domain
  Mode=$Mode
  BaseUrl=$BaseUrl
"@
    exit 0
}

function Test-Health {
    param([string]$Url)
    try {
        $health = Invoke-RestMethod -Uri "$Url/api/v1/health" -TimeoutSec 5
        return (
            $health.status -eq "ok" -and
            $health.dependencies.milvus -eq $true -and
            $health.dependencies.redis -eq $true -and
            $health.dependencies.postgres -eq $true
        )
    } catch {
        return $false
    }
}

function Invoke-Chat {
    param(
        [string]$Url,
        [array]$Messages,
        [string]$DomainName,
        [string]$ModeName,
        [string]$ConversationId
    )

    $payload = @{
        messages = $Messages
        domain = $DomainName
        mode = $ModeName
        conversation_id = $ConversationId
    }

    $json = $payload | ConvertTo-Json -Depth 8
    return Invoke-RestMethod `
        -Uri "$Url/api/v1/chat" `
        -Method Post `
        -ContentType "application/json; charset=utf-8" `
        -Body $json `
        -TimeoutSec 180
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

if (-not (Test-Health -Url $BaseUrl)) {
    if ($NoAutoStart) {
        Write-Host "PolyAgent is not ready. Run .\start.cmd first." -ForegroundColor Yellow
        exit 1
    }

    Write-Host "PolyAgent is not ready. Starting services..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\start.ps1"
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$conversationId = [guid]::NewGuid().ToString()
$messages = @()

Write-Host ""
Write-Host "PolyAgent interactive chat"
Write-Host "Domain: $Domain | Mode: $Mode | Conversation: $conversationId"
Write-Host "Type your question, or /exit to quit. Use /reset to clear history."
Write-Host ""

while ($true) {
    $inputText = Read-Host "你"
    if ($null -eq $inputText) {
        continue
    }

    $inputText = $inputText.Trim()
    if ($inputText.Length -eq 0) {
        continue
    }

    if ($inputText -in @("/exit", "exit", "quit", "q")) {
        break
    }

    if ($inputText -eq "/reset") {
        $messages = @()
        $conversationId = [guid]::NewGuid().ToString()
        Write-Host "已重置对话。Conversation: $conversationId"
        continue
    }

    if ($inputText.StartsWith("/domain ")) {
        $Domain = $inputText.Substring(8).Trim()
        Write-Host "Domain => $Domain"
        continue
    }

    if ($inputText.StartsWith("/mode ")) {
        $Mode = $inputText.Substring(6).Trim()
        Write-Host "Mode => $Mode"
        continue
    }

    $messages += @{ role = "user"; content = $inputText }

    try {
        Write-Host "PolyAgent 正在思考..."
        $response = Invoke-Chat `
            -Url $BaseUrl `
            -Messages $messages `
            -DomainName $Domain `
            -ModeName $Mode `
            -ConversationId $conversationId

        Write-Host ""
        Write-Host "PolyAgent:"
        Write-Host $response.content
        Write-Host ""
        Write-Host ("[domain={0}, mode={1}, success={2}, degraded={3}]" -f $response.domain, $response.mode_used, $response.success, $response.degraded) -ForegroundColor DarkGray
        Write-Host ""

        $messages += @{ role = "assistant"; content = [string]$response.content }
    } catch {
        Write-Host ""
        Write-Host "请求失败: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "如果是 API key/model 错误，请检查 .env 里的 LLM_* 和 EMBED_* 配置。" -ForegroundColor Yellow
        Write-Host ""
        if ($messages.Count -gt 0) {
            $messages = $messages[0..($messages.Count - 2)]
        }
    }
}

Write-Host "已退出 PolyAgent 对话。"
