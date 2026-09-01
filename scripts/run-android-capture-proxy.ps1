[CmdletBinding()]
param(
    [int]$ListenPort = 8080,
    [string]$MitmDumpPath = 'C:\Program Files\mitmproxy\bin\mitmdump.exe'
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$addon = Join-Path $PSScriptRoot 'mitm_local_only.py'
$confDir = Join-Path $repo 'certs\mitmproxy'

if (-not (Test-Path -LiteralPath $MitmDumpPath -PathType Leaf)) {
    throw "mitmdump was not found at '$MitmDumpPath'. Install mitmproxy or pass -MitmDumpPath."
}

New-Item -ItemType Directory -Path $confDir -Force | Out-Null

Write-Host "Local-only TLS proxy listening on 0.0.0.0:$ListenPort"
Write-Host 'First-party requests are rewritten to 127.0.0.1:18080; every other host is answered locally.'
& $MitmDumpPath `
    --listen-host '0.0.0.0' `
    --listen-port $ListenPort `
    --set "confdir=$confDir" `
    --set block_global=false `
    --set connection_strategy=lazy `
    --set termlog_verbosity=info `
    -s $addon
exit $LASTEXITCODE
