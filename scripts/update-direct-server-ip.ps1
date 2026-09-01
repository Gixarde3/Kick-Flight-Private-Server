[CmdletBinding()]
param(
    [string]$ConfigPath = 'config\apk-direct-server.local.json',
    [string]$InterfaceAlias,
    [ValidateRange(1, 65535)]
    [int]$Port,
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$configFile = if ([IO.Path]::IsPathRooted($ConfigPath)) {
    [IO.Path]::GetFullPath($ConfigPath)
} else {
    [IO.Path]::GetFullPath((Join-Path $repo $ConfigPath))
}

if (-not (Test-Path -LiteralPath $configFile -PathType Leaf)) {
    throw "Direct-server config not found: $configFile"
}

$candidates = Get-NetIPConfiguration | Where-Object {
    $_.IPv4Address -and
    $_.NetAdapter.Status -eq 'Up' -and
    $_.InterfaceAlias -notmatch 'Loopback|vEthernet|VirtualBox|VMware'
}

if ($InterfaceAlias) {
    $candidates = $candidates | Where-Object InterfaceAlias -EQ $InterfaceAlias
    if (-not $candidates) {
        throw "No active IPv4 interface named '$InterfaceAlias' was found."
    }
} else {
    $candidates = $candidates | Where-Object IPv4DefaultGateway
    if (-not $candidates) {
        throw 'No active IPv4 interface with a default gateway was found.'
    }
}

$selected = $candidates | Sort-Object {
    (Get-NetIPInterface -InterfaceIndex $_.InterfaceIndex -AddressFamily IPv4).InterfaceMetric
} | Select-Object -First 1
$address = [string]$selected.IPv4Address.IPAddress
if (-not $address -or $address -like '169.254.*' -or $address -eq '127.0.0.1') {
    throw "Selected interface returned an unusable IPv4 address: '$address'."
}

$config = Get-Content -Raw -LiteralPath $configFile | ConvertFrom-Json
$currentUri = [Uri]$config.serverBaseUrl
$selectedPort = if ($PSBoundParameters.ContainsKey('Port')) { $Port } else { $currentUri.Port }
$newUrl = "http://$address`:$selectedPort"

Write-Host "Interface:  $($selected.InterfaceAlias)"
Write-Host "IPv4:       $address"
Write-Host "Current URL: $($config.serverBaseUrl)"
Write-Host "New URL:     $newUrl"

if (-not $Apply) {
    Write-Host 'DRY RUN: configuration was not changed. Re-run with -Apply.'
    exit 0
}

$config.serverBaseUrl = $newUrl
$config | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $configFile -Encoding utf8
Write-Host "Updated: $configFile"
& (Join-Path $PSScriptRoot 'build-title-resource-catalog.ps1')
Write-Warning 'Rebuild the direct APK after changing its server URL.'
