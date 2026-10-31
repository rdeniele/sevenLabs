$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "The app is not set up yet. Run .\setup.ps1 first." -ForegroundColor Yellow
    exit 1
}

Set-Location $projectRoot
$env:PYTHONUTF8 = "1"
$env:HF_HOME = Join-Path $projectRoot "data\models\huggingface"
$env:HF_HUB_CACHE = Join-Path $env:HF_HOME "hub"

Write-Host "Opening SevenLabs..." -ForegroundColor Green
& $python -m app.desktop

