[CmdletBinding()]
param(
    [string]$AdbPath = 'adb',
    [string]$CertificateFileName = 'c8750f0d.0',
    [switch]$ClearTestPin,
    [string]$TestPin = '1234',
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$localAdb = Join-Path $repo '.local\tools\platform-tools\adb.exe'
if ($AdbPath -eq 'adb' -and -not (Get-Command adb -ErrorAction SilentlyContinue) -and (Test-Path -LiteralPath $localAdb)) { $AdbPath = $localAdb }
if ($CertificateFileName -notmatch '^[0-9a-f]{8}\.0$') { throw 'CertificateFileName must be an Android CA hash filename such as c8750f0d.0.' }

$isEmulator = (& $AdbPath shell getprop ro.kernel.qemu).Trim()
if ($isEmulator -ne '1') { throw 'Refusing to alter credentials: the connected target is not an Android emulator.' }
$target = "/data/misc/user/0/cacerts-added/$CertificateFileName"

if (-not $Apply) {
    Write-Output "DRY RUN: would remove only '$target' from the emulator. Re-run with -Apply."
    exit 0
}

& $AdbPath root | Out-Host
& $AdbPath wait-for-device
& $AdbPath shell test -f $target
if ($LASTEXITCODE -eq 0) {
    & $AdbPath shell rm $target
    if ($LASTEXITCODE -ne 0) { throw "Failed to remove '$target'." }
    Write-Output "Removed emulator user CA '$target'."
} else {
    Write-Output "CA '$target' was already absent."
}

if ($ClearTestPin) {
    & $AdbPath shell locksettings clear --old $TestPin
    if ($LASTEXITCODE -ne 0) { throw 'Failed to clear the emulator test PIN.' }
    Write-Output 'Cleared the emulator test PIN.'
}
