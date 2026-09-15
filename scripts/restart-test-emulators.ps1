[CmdletBinding()]
param(
    [string]$RunId = (Get-Date -Format 'yyyyMMdd-HHmmss'),
    [string]$EvidenceRoot = '.local\gameplay-evidence\automated',
    [int]$BootTimeoutSeconds = 150,
    [switch]$Visible
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$adb = Join-Path $repo '.local\android-sdk\platform-tools\adb.exe'
$emulator = Join-Path $repo '.local\android-sdk\emulator\emulator.exe'
$avdHome = Join-Path $repo '.local\android-avd'
$evidence = [IO.Path]::GetFullPath((Join-Path $repo (Join-Path $EvidenceRoot "$RunId-boot")))
$summary = Join-Path $evidence 'summary.json'
$devices = @(
    @{ serial = 'emulator-5554'; port = 5554; avd = 'KickFlight_API35' },
    @{ serial = 'emulator-5556'; port = 5556; avd = 'KickFlight_API35_P2' }
)

New-Item -ItemType Directory -Force -Path $evidence | Out-Null
foreach ($path in $adb, $emulator, $avdHome) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required emulator path not found: $path" }
}

function Wait-ForBoot([string]$Serial, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $state = @(& $adb -s $Serial get-state 2>$null) -join ''
        $boot = ''
        if ($LASTEXITCODE -eq 0 -and $state.Trim() -eq 'device') {
            $boot = @(& $adb -s $Serial shell getprop sys.boot_completed 2>$null) -join ''
        }
        if ($state.Trim() -eq 'device' -and $boot.Trim() -eq '1') { return }
        Start-Sleep -Seconds 3
    }
    throw "$Serial did not finish boot in $TimeoutSeconds seconds."
}

$launched = @{}
try {
    foreach ($device in $devices) {
        & $adb -s $device.serial emu kill 2>$null | Out-Null
    }
    Start-Sleep -Seconds 8

    $previousAvdHome = $env:ANDROID_AVD_HOME
    try {
        $env:ANDROID_AVD_HOME = $avdHome
        foreach ($device in $devices) {
            $stdout = Join-Path $evidence "$($device.serial)-emulator.stdout.log"
            $stderr = Join-Path $evidence "$($device.serial)-emulator.stderr.log"
            $gpuMode = if ($Visible) { 'host' } else { 'software' }
            $coreCount = if ($Visible) { '4' } else { '2' }
            $arguments = @(
                '-avd', $device.avd,
                '-port', "$($device.port)",
                '-read-only', '-no-snapshot-load', '-no-snapshot-save',
                '-gpu', $gpuMode, '-feature', '-Vulkan', '-cores', $coreCount
            )
            if (-not $Visible) { $arguments += '-no-window' }
            $windowStyle = if ($Visible) { 'Normal' } else { 'Hidden' }
            $process = Start-Process -FilePath $emulator -ArgumentList $arguments `
                -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
                -WindowStyle $windowStyle -PassThru
            $launched[$device.serial] = @{
                pid = $process.Id
                avd = $device.avd
                stdout = $stdout
                stderr = $stderr
                gpu = $gpuMode
                cores = [int]$coreCount
            }
            Wait-ForBoot -Serial $device.serial -TimeoutSeconds $BootTimeoutSeconds
        }
    } finally {
        $env:ANDROID_AVD_HOME = $previousAvdHome
    }

    @{ result = 'passed'; devices = $launched; completedAt = (Get-Date).ToString('o') } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summary
    Write-Host "Both test emulators rebooted without clearing app data. Evidence: $evidence"
} catch {
    @{ result = 'failed'; failure = $_.Exception.Message; devices = $launched; completedAt = (Get-Date).ToString('o') } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summary
    throw
}
