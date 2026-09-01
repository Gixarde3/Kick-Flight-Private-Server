[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ServerAddress,
    [int]$Port = 8080,
    [string]$Serial,
    [string]$AdbPath = 'adb',
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$localAdb = Join-Path $repo '.local\tools\platform-tools\adb.exe'
if ($AdbPath -eq 'adb' -and -not (Get-Command adb -ErrorAction SilentlyContinue) -and (Test-Path -LiteralPath $localAdb)) { $AdbPath = $localAdb }
$stateDirectory = Join-Path $repo '.local'
$statePath = Join-Path $stateDirectory 'android-proxy-state.json'
$target = "$ServerAddress`:$Port"
$adbArgs = @()
if ($Serial) { $adbArgs += @('-s', $Serial) }

$current = (& $AdbPath @adbArgs shell settings get global http_proxy).Trim()
$state = [ordered]@{
    capturedUtc = [DateTimeOffset]::UtcNow.ToString('o')
    serial = $Serial
    previousHttpProxy = $current
    requestedHttpProxy = $target
}

if (-not $Apply) {
    Write-Output "DRY RUN: current Android proxy='$current'; would set '$target'. Re-run with -Apply."
    $state | ConvertTo-Json
    exit 0
}

New-Item -ItemType Directory -Force -Path $stateDirectory | Out-Null
$state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
& $AdbPath @adbArgs shell settings put global http_proxy $target
if ($LASTEXITCODE -ne 0) { throw 'ADB failed to set the proxy.' }
Write-Output "Android proxy set to $target. Previous state saved to $statePath"
Write-Warning 'HTTPS requires scripts/run-android-capture-proxy.ps1 and its local CA installed in the test emulator.'
