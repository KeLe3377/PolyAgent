[CmdletBinding()]
param(
    [switch]$Ingest,
    [switch]$Logs,
    [switch]$Help,
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"

if ($Help) {
    @"
PolyAgent one-click startup (conda app + docker infra)

App runs from the conda env; only the infrastructure services
(postgres, redis, etcd, minio, milvus) run in Docker.

Usage:
  .\start.cmd
  .\start.cmd -Ingest
  .\start.cmd -Ingest -Logs

Options:
  -Ingest           After health is green, write domain corpus chunks to Milvus.
  -Logs             Follow app logs after startup.
  -TimeoutSeconds   Health wait timeout. Default: 180.

Environment:
  POLYAGENT_PYTHON     Path to the conda env python.exe.
                       Default: D:\conda_envs\PolyAgent\python.exe
  POLYAGENT_NO_PAUSE=1 disables the final pause in start.cmd.
"@
    exit 0
}

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message"
}

function Invoke-Docker {
    param([string[]]$Arguments)
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Wait-PolyAgentHealth {
    param(
        [string]$Url,
        [int]$Timeout
    )

    $deadline = (Get-Date).AddSeconds($Timeout)
    $lastError = $null

    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri $Url -TimeoutSec 5
            $deps = $health.dependencies
            if (
                $health.status -eq "ok" -and
                $deps.milvus -eq $true -and
                $deps.redis -eq $true -and
                $deps.postgres -eq $true
            ) {
                return $health
            }
            $lastError = "Health returned but dependencies are not all ready."
        } catch {
            $lastError = $_.Exception.Message
        }

        Start-Sleep -Seconds 3
    }

    throw "Timed out waiting for $Url. Last error: $lastError"
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$python = if ($env:POLYAGENT_PYTHON) {
    $env:POLYAGENT_PYTHON
} else {
    "python"
}

# Infrastructure services run in Docker; the app itself runs in conda.
$infraServices = @("postgres", "redis", "etcd", "minio", "milvus")

Write-Host "PolyAgent startup (conda app + docker infra)"
Write-Host "Repo: $repoRoot"
Write-Host "Python: $python"

try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI was not found. Please install/start Docker Desktop first."
    }
    if ($python -match "[\\/]" -and -not (Test-Path $python)) {
        throw "Python not found at '$python'. Set POLYAGENT_PYTHON to your env's python.exe."
    }

    Write-Step "Checking Docker Compose config"
    Invoke-Docker @("compose", "config", "--quiet")

    Write-Step "Starting infrastructure services in Docker"
    Invoke-Docker (@("compose", "up", "-d") + $infraServices)

    Write-Step "Launching app from conda env"
    $logDir = Join-Path $repoRoot ".tmp\logs"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $logFile = Join-Path $logDir "app.log"
    if (Test-Path $logFile) { Remove-Item $logFile -Force }
    $inner = "& '$python' -m uvicorn app.main:app --host 0.0.0.0 --port 8000 *> '$logFile'"
    $appProc = Start-Process -FilePath powershell.exe `
        -ArgumentList @("-NoProfile", "-Command", $inner) `
        -WorkingDirectory $repoRoot `
        -WindowStyle Minimized -PassThru
    Write-Host ("App PID: {0}  (logs: {1})" -f $appProc.Id, $logFile)

    Write-Step "Waiting for API health"
    $healthUrl = "http://127.0.0.1:8000/api/v1/health"
    $health = Wait-PolyAgentHealth -Url $healthUrl -Timeout $TimeoutSeconds
    Write-Host ("Health: " + ($health | ConvertTo-Json -Compress))

    if ($Ingest) {
        Write-Step "Ingesting domain corpus into Milvus"
        & $python scripts/ingest_corpus.py --confirmed
        if ($LASTEXITCODE -ne 0) {
            throw "ingest_corpus.py failed with exit code $LASTEXITCODE"
        }
    } else {
        Write-Host ""
        Write-Host "Corpus ingest skipped. Run '.\start.cmd -Ingest' when you want to write corpus chunks to Milvus."
    }

    Write-Host ""
    Write-Host "PolyAgent is ready:"
    Write-Host "  API:     http://127.0.0.1:8000"
    Write-Host "  Health:  $healthUrl"
    Write-Host "  Domains: http://127.0.0.1:8000/api/v1/domains"
    Write-Host "  Stop app: Stop-Process -Id $($appProc.Id)"

    if ($Logs) {
        Write-Step "Following app logs ($logFile)"
        Get-Content $logFile -Wait
    }
} catch {
    Write-Host ""
    Write-Host "Startup failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    Write-Host "Recent app logs:"
    if (Test-Path $logFile) { Get-Content $logFile -Tail 80 }
    exit 1
}
