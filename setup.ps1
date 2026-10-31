param(
    [switch]$PlanOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

# Start with a small trusted Windows PATH. Codex, CUA, and similar desktop tools
# can inject junctions that Python deliberately rejects with WinError 448.
$safePathCandidates = @(
    (Join-Path $env:SystemRoot "System32"),
    $env:SystemRoot,
    (Join-Path $env:SystemRoot "System32\Wbem"),
    (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0"),
    (Join-Path $env:SystemRoot "System32\OpenSSH"),
    (Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Launcher"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\Scripts"),
    (Join-Path $env:ProgramFiles "NVIDIA Corporation\NVSMI")
)
$env:PATH = (@($safePathCandidates | Where-Object {
    $_ -and (Test-Path -LiteralPath $_)
} | Select-Object -Unique)) -join ";"

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

function Get-NvidiaMemoryMB {
    $nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if (-not $nvidia) { return 0 }
    try {
        $values = @(& $nvidia.Source --query-gpu=memory.total --format=csv,noheader,nounits 2>$null)
        $memory = @($values | ForEach-Object {
            $parsed = 0
            if ([int]::TryParse($_.Trim(), [ref]$parsed)) { $parsed }
        })
        if ($memory.Count) { return ($memory | Measure-Object -Maximum).Maximum }
    } catch {}
    return 0
}

$gpuMemoryMB = Get-NvidiaMemoryMB
$useCuda = $gpuMemoryMB -ge 6144

if ($PlanOnly) {
    [pscustomobject]@{
        ProtectedMountsRemoved = -not (($env:PATH -split ";") -match "(?i)(codex|cua-driver|\\.codex|\\.cua-driver)")
        NvidiaMemoryMB = $gpuMemoryMB
        PyTorchBuild = if ($useCuda) { "CUDA" } else { "CPU" }
        EmbeddedVoiceEngine = Test-Path -LiteralPath (Join-Path $projectRoot "vendor\VoxCPM\src\voxcpm\__init__.py")
    } | Format-List
    exit 0
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

if ($useCuda) {
    Write-Host "NVIDIA GPU with $gpuMemoryMB MB detected. Installing the CUDA build of PyTorch..." -ForegroundColor Cyan
    & $venvPython -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
    Assert-LastCommand "Could not install the CUDA build of PyTorch."
} else {
    if ($gpuMemoryMB -gt 0) {
        Write-Host "NVIDIA GPU has $gpuMemoryMB MB of memory. Installing the smaller CPU build for stability..." -ForegroundColor Cyan
    } else {
        Write-Host "Installing the CPU build of PyTorch..." -ForegroundColor Cyan
    }
    & $venvPython -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu
    Assert-LastCommand "Could not install the CPU build of PyTorch."
}

Write-Host "Installing SevenLabs..." -ForegroundColor Cyan
& $venvPython -m pip install -r requirements.txt
Assert-LastCommand "Could not install the app dependencies."
& $venvPython -m pip install --no-deps --editable .\vendor\VoxCPM
Assert-LastCommand "Could not install the embedded VoxCPM2 voice engine."

New-Item -ItemType Directory -Force -Path "data\voices", "data\outputs", "data\models" | Out-Null
Write-Host "Setup complete. Run .\start.ps1" -ForegroundColor Green

