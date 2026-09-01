[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw 'Python is required to encode the Octo protobuf catalog.'
}

& $python.Source (Join-Path $PSScriptRoot 'build-title-resource-catalog.py')
if ($LASTEXITCODE -ne 0) {
    throw "Octo catalog generator failed with exit code $LASTEXITCODE."
}
