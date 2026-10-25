$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

function Assert-LastCommand([string]$message) {
    if ($LASTEXITCODE -ne 0) { throw $message }
}

function Resolve-Python311 {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            & py -3.11 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0) { return @("py", "-3.11") }
        } catch {}
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        try {
            $version = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
            if ($version -eq "3.11") { return @("python") }
        } catch {}
    }

    return $null
}

$pythonCommand = Resolve-Python311
if (-not $pythonCommand) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Python 3.11 is required. Install it from https://www.python.org/downloads/release/python-3119/ and run setup.ps1 again."
    }

    Write-Host "Python 3.11 was not found. Installing it with winget..." -ForegroundColor Cyan
    winget install --id Python.Python.3.11 --exact --accept-package-agreements --accept-source-agreements
    $pythonCommand = Resolve-Python311
    if (-not $pythonCommand) {
        $knownPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"
        if (Test-Path $knownPython) { $pythonCommand = @($knownPython) }
    }
    if (-not $pythonCommand) { throw "Python installed, but could not be found. Reopen PowerShell and run setup.ps1 again." }
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating the local Python environment..." -ForegroundColor Cyan
    if ($pythonCommand.Count -eq 2) {
        & $pythonCommand[0] $pythonCommand[1] -m venv .venv
        Assert-LastCommand "Could not create the Python environment."
    } else {
        & $pythonCommand[0] -m venv .venv
        Assert-LastCommand "Could not create the Python environment."
    }
}

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path (Join-Path $projectRoot ".venv\Scripts\pip.exe"))) {
    Write-Host "Repairing an incomplete Python environment..." -ForegroundColor Yellow
    if ($pythonCommand.Count -eq 2) {
        & $pythonCommand[0] $pythonCommand[1] -m venv --clear .venv
    } else {
        & $pythonCommand[0] -m venv --clear .venv
    }
    Assert-LastCommand "Could not repair the Python environment."
}

& $venvPython -m pip install --upgrade pip wheel "setuptools<81"
Assert-LastCommand "Could not update the Python package installer."

$hasNvidia = $null -ne (Get-Command nvidia-smi -ErrorAction SilentlyContinue)
if ($hasNvidia) {
    Write-Host "NVIDIA GPU detected. Installing the CUDA build of PyTorch..." -ForegroundColor Cyan
    & $venvPython -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
    Assert-LastCommand "Could not install the CUDA build of PyTorch."
} else {
    Write-Host "Installing the CPU build of PyTorch..." -ForegroundColor Cyan
    & $venvPython -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu
    Assert-LastCommand "Could not install the CPU build of PyTorch."
}

Write-Host "Installing Local Voice Studio..." -ForegroundColor Cyan
& $venvPython -m pip install -r requirements.txt
Assert-LastCommand "Could not install the app dependencies."

New-Item -ItemType Directory -Force -Path "data\voices", "data\outputs", "data\models" | Out-Null
Write-Host "Setup complete. Run .\start.ps1" -ForegroundColor Green

