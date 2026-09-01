[CmdletBinding()]
param(
    [string]$AdbPath = 'adb',
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$localAdb = Join-Path $repo '.local\tools\platform-tools\adb.exe'
if ($AdbPath -eq 'adb' -and -not (Get-Command adb -ErrorAction SilentlyContinue) -and (Test-Path -LiteralPath $localAdb)) { $AdbPath = $localAdb }
$statePath = Join-Path $repo '.local\android-proxy-state.json'
if (-not (Test-Path -LiteralPath $statePath)) { throw "No saved Android proxy state: $statePath" }
$state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
$adbArgs = @()
if ($state.serial) { $adbArgs += @('-s', [string]$state.serial) }
$previous = [string]$state.previousHttpProxy

if (-not $Apply) {
    Write-Output "DRY RUN: would restore Android proxy to '$previous'. Re-run with -Apply."
    exit 0
}

if ([string]::IsNullOrWhiteSpace($previous) -or $previous -eq 'null' -or $previous -eq ':0') {
    & $AdbPath @adbArgs shell settings delete global http_proxy
} else {
    & $AdbPath @adbArgs shell settings put global http_proxy $previous
}
if ($LASTEXITCODE -ne 0) { throw 'ADB failed to restore the proxy.' }
Write-Output "Android proxy restored to '$previous'."
