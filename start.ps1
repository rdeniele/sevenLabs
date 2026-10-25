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

try {
    $running = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 1
    if ($running.ok) {
        Start-Process "http://127.0.0.1:8765"
        Write-Host "Local Voice Studio is already running." -ForegroundColor Green
        exit 0
    }
} catch {}

Start-Process "http://127.0.0.1:8765"
Write-Host "Local Voice Studio is running. Keep this window open." -ForegroundColor Green
Write-Host "Close this window or press Ctrl+C to stop it." -ForegroundColor DarkGray
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8765

