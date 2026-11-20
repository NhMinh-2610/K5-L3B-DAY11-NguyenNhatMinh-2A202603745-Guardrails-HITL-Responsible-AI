# Run the repository virtualenv, following its short-path junction on Windows.
# Example: .\scripts\python.ps1 -m pytest tests/smoke tests/public -q
$ErrorActionPreference = 'Stop'
# Lab logs contain Vietnamese and Unicode attack samples, including in pipes.
$labPreviousEncoding = $env:PYTHONIOENCODING
$env:PYTHONIOENCODING = 'utf-8'
$labRoot = Split-Path -Parent $PSScriptRoot
$labVenv = Join-Path $labRoot '.venv'
$labVenvItem = Get-Item -LiteralPath $labVenv -ErrorAction SilentlyContinue
if ($labVenvItem -and $labVenvItem.LinkType -eq 'Junction') {
    $labVenv = $labVenvItem.Target | Select-Object -First 1
}
$labPython = Join-Path $labVenv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $labPython)) {
    throw 'Create .venv with Python 3.11 and install requirements.txt first.'
}
Push-Location -LiteralPath $labRoot
try {
    & $labPython @args
    $labExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
    if ($null -eq $labPreviousEncoding) {
        Remove-Item -LiteralPath Env:PYTHONIOENCODING -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONIOENCODING = $labPreviousEncoding
    }
}
exit $labExitCode
