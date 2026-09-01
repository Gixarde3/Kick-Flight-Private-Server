[CmdletBinding()]
param(
    [ValidateRange(0, 500)]
    [int]$Tail = 30
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$statePath = Join-Path $repo '.local\session-logs\kickflight-services.json'

if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
    throw "No logged Kick-Flight service state exists at '$statePath'."
}

$state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
$serviceNames = @('server')
if ($state.proxy) { $serviceNames += 'proxy' }
$rows = foreach ($name in $serviceNames) {
    $service = $state.$name
    $process = Get-Process -Id $service.pid -ErrorAction SilentlyContinue
    $listener = Get-NetTCPConnection -State Listen -LocalPort $service.port -ErrorAction SilentlyContinue
    [pscustomobject]@{
        Service = $name
        PID = $service.pid
        Running = [bool]$process
        Port = $service.port
        Listening = [bool]$listener
        Stdout = $service.stdout
        Stderr = $service.stderr
    }
}

$rows | Format-Table -AutoSize

if ($Tail -gt 0) {
    foreach ($name in $serviceNames) {
        $service = $state.$name
        foreach ($stream in 'stdout', 'stderr') {
            $path = $service.$stream
            Write-Host "`n--- $name ${stream}: $path ---"
            if (Test-Path -LiteralPath $path -PathType Leaf) {
                Get-Content -LiteralPath $path -Tail $Tail
            } else {
                Write-Host '(log file not created yet)'
            }
        }
    }
}
