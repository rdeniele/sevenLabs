$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$exeBuildScript = Join-Path $projectRoot "build-exe.ps1"
$installerScript = Join-Path $projectRoot "installer\SevenLabs.iss"
$outputInstaller = Join-Path $projectRoot "dist\SevenLabs-Setup.exe"

$compilerCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Join-Path $env:USERPROFILE "AppData\Local\Programs\Inno Setup 6\ISCC.exe")
)
$compiler = $compilerCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $compiler) {
    throw "Inno Setup 6 is required. Install it with: winget install --id JRSoftware.InnoSetup --exact"
}

Write-Host "Building SevenLabs.exe..." -ForegroundColor Cyan
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $exeBuildScript
if ($LASTEXITCODE -ne 0) { throw "The SevenLabs launcher build failed." }

Write-Host ""
Write-Host "Building SevenLabs-Setup.exe..." -ForegroundColor Cyan
& $compiler $installerScript
if ($LASTEXITCODE -ne 0) { throw "The SevenLabs installer build failed." }

$file = Get-Item -LiteralPath $outputInstaller
$hash = (Get-FileHash -LiteralPath $outputInstaller -Algorithm SHA256).Hash
Write-Host ""
Write-Host "Installer complete" -ForegroundColor Green
Write-Host "File: $($file.FullName)"
Write-Host "Size: $([math]::Round($file.Length / 1MB, 1)) MB"
Write-Host "SHA256: $hash"
