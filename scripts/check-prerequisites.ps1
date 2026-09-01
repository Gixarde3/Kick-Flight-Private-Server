[CmdletBinding()]
param(
    [string]$SourceRepo = 'C:\Users\Gixar\Documentos\Variedad\Kick-Flight-Assets',
    [string]$AdbPath
)

$ErrorActionPreference = 'Stop'
$expectedHash = 'F79F1B48F86C4F5973C763CBC6C166BD6C42CC83D4E36ECA75D7D1CAB74AD8D1'
$apk = Join-Path $SourceRepo 'base.apk'
$repo = Split-Path -Parent $PSScriptRoot
$localDotnet = Join-Path $repo '.local\tools\dotnet\dotnet.exe'
$dotnetCommand = if (Test-Path -LiteralPath $localDotnet) { $localDotnet } else { 'dotnet' }
$dotnetInfo = & $dotnetCommand --info 2>&1 | Out-String
$sdkInstalled = $dotnetInfo -notmatch 'No SDKs were found'

if (-not $AdbPath) {
    $adbCommand = Get-Command adb -ErrorAction SilentlyContinue
    if ($adbCommand) { $AdbPath = $adbCommand.Source }
    $localAdb = Join-Path $repo '.local\tools\platform-tools\adb.exe'
    if (-not $AdbPath -and (Test-Path -LiteralPath $localAdb)) { $AdbPath = $localAdb }
}

$devices = @()
if ($AdbPath -and (Test-Path -LiteralPath $AdbPath)) {
    $devices = @(& $AdbPath devices -l 2>&1 | Select-Object -Skip 1 | Where-Object { $_ -match '\sdevice(\s|$)' })
}

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
$dockerReady = $false
if ($dockerCommand) {
    & docker info *> $null
    $dockerReady = $LASTEXITCODE -eq 0
}

$result = [ordered]@{
    timestampUtc = [DateTimeOffset]::UtcNow.ToString('o')
    dotnet8Sdk = $sdkInstalled -and ($dotnetInfo -match '8\.0\.')
    dotnetPath = $dotnetCommand
    dotnetSummary = (($dotnetInfo -split "`r?`n") | Select-Object -First 12) -join "`n"
    adbPath = $AdbPath
    androidDevices = $devices
    openssl = [bool](Get-Command openssl -ErrorAction SilentlyContinue)
    powershellCertificateCmdlets = [bool](Get-Command New-SelfSignedCertificate -ErrorAction SilentlyContinue)
    dockerInstalled = [bool]$dockerCommand
    dockerReady = $dockerReady
    apkPath = $apk
    apkPresent = Test-Path -LiteralPath $apk
    apkSha256 = if (Test-Path -LiteralPath $apk) { (Get-FileHash -Algorithm SHA256 -LiteralPath $apk).Hash } else { $null }
    apkHashMatches = if (Test-Path -LiteralPath $apk) { (Get-FileHash -Algorithm SHA256 -LiteralPath $apk).Hash -eq $expectedHash } else { $false }
}

$result | ConvertTo-Json -Depth 5
