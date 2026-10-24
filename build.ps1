param(
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$env:PYTHONPATH = "$projectRoot\vendor;$projectRoot\src"
Set-Location -LiteralPath $projectRoot
& $Python -m PyInstaller --noconfirm --clean `
    --distpath "$projectRoot\dist" --workpath "$projectRoot\build" `
    "$projectRoot\OCRProxyDesktop.spec"
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
& $Python "$projectRoot\package.py"
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
