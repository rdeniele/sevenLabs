@echo off
setlocal
cd /d "%~dp0"
title SevenLabs

if not exist ".venv\Scripts\python.exe" (
  echo SevenLabs needs to be set up first.
  echo.
  echo Running the one-time setup now...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
  if errorlevel 1 (
    echo.
    echo Setup did not complete. Press any key to close.
    pause >nul
    exit /b 1
  )
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"

if errorlevel 1 (
  echo.
  echo SevenLabs stopped with an error. Press any key to close.
  pause >nul
)

