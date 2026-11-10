@echo off
setlocal

cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\chat.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%POLYAGENT_NO_PAUSE%"=="1" (
  exit /b %EXIT_CODE%
)

pause
exit /b %EXIT_CODE%
