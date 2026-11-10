@echo off
setlocal

cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%POLYAGENT_NO_PAUSE%"=="1" (
  exit /b %EXIT_CODE%
)

if "%EXIT_CODE%"=="0" (
  echo PolyAgent startup finished.
) else (
  echo PolyAgent startup failed with exit code %EXIT_CODE%.
)
pause
exit /b %EXIT_CODE%
