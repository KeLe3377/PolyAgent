@echo off
setlocal

cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$py = $env:POLYAGENT_PYTHON; if (-not $py) { $py = 'D:\conda_envs\PolyAgent\python.exe' }; if (-not (Test-Path $py)) { $py = 'python' }; & $py scripts\e2e_chat_benchmark.py %*"

exit /b %ERRORLEVEL%
