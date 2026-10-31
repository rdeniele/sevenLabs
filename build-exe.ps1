$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$distFolder = Join-Path $projectRoot "dist"
$outputExe = Join-Path $distFolder "SevenLabs.exe"
$sourceFile = Join-Path $projectRoot "launcher\Program.cs"
$iconFile = Join-Path $projectRoot "launcher\sevenlabs.ico"

$compilerCandidates = @(
    (Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
    (Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe")
)
$compiler = $compilerCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $compiler) { throw "The built-in Windows .NET compiler could not be found." }

New-Item -ItemType Directory -Force -Path $distFolder | Out-Null

$payloadFiles = @(
    Get-ChildItem -LiteralPath (Join-Path $projectRoot "app") -Recurse -File |
        Where-Object { $_.FullName -notmatch "__pycache__" -and $_.Extension -ne ".pyc" }
    Get-ChildItem -LiteralPath (Join-Path $projectRoot "vendor\VoxCPM") -Recurse -File |
        Where-Object { $_.FullName -notmatch "(__pycache__|\.git|\.egg-info)" -and $_.Extension -ne ".pyc" }
    Get-Item -LiteralPath (Join-Path $projectRoot "scripts\warm_models.py")
    Get-Item -LiteralPath (Join-Path $projectRoot "requirements.txt")
    Get-Item -LiteralPath (Join-Path $projectRoot "setup.ps1")
    Get-Item -LiteralPath (Join-Path $projectRoot "start.ps1")
    Get-Item -LiteralPath (Join-Path $projectRoot "README.md")
)

$compilerArguments = @(
    "/nologo",
    "/target:winexe",
    "/platform:x64",
    "/optimize+",
    "/win32icon:$iconFile",
    "/out:$outputExe",
    "/reference:System.Windows.Forms.dll",
    $sourceFile
)

foreach ($file in $payloadFiles) {
    $relativePath = $file.FullName.Substring($projectRoot.Length + 1).Replace("\", "/")
    $compilerArguments += "/resource:$($file.FullName),payload/$relativePath"
}

Write-Host "Building the portable SevenLabs launcher..." -ForegroundColor Cyan
& $compiler $compilerArguments

if ($LASTEXITCODE -ne 0) { throw "The SevenLabs launcher build failed." }
$file = Get-Item -LiteralPath $outputExe
$hash = (Get-FileHash -LiteralPath $outputExe -Algorithm SHA256).Hash

Write-Host ""
Write-Host "Build complete" -ForegroundColor Green
Write-Host "File: $($file.FullName)"
Write-Host "Size: $([math]::Round($file.Length / 1MB, 1)) MB"
Write-Host "SHA256: $hash"
