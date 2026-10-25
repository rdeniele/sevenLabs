@echo off
setlocal
cd /d "%~dp0"
title Local Voice Studio

if not exist ".venv\Scripts\python.exe" (
  echo Local Voice Studio needs to be set up first.
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
  echo Local Voice Studio stopped with an error. Press any key to close.
  pause >nul
)

