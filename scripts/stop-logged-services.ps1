[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$statePath = Join-Path $repo '.local\session-logs\kickflight-services.json'

if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
    Write-Host 'No logged Kick-Flight services are recorded.'
    exit 0
}

function Get-ProcessTree([int]$RootProcessId) {
    foreach ($child in Get-CimInstance Win32_Process -Filter "ParentProcessId = $RootProcessId" -ErrorAction SilentlyContinue) {
        Get-ProcessTree -RootProcessId $child.ProcessId
    }
    $RootProcessId
}

$state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
$serviceNames = @('server')
if ($state.proxy) { $serviceNames = @('proxy', 'server') }
foreach ($name in $serviceNames) {
    $service = $state.$name
    $rootProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($service.pid)" -ErrorAction SilentlyContinue
    if (-not $rootProcess) {
        Write-Host "$name PID $($service.pid) is already stopped."
        continue
    }

    if ($rootProcess.CommandLine -notmatch [regex]::Escape($repo)) {
        Write-Warning "Refusing to stop stale PID $($service.pid): its command line does not reference this repository."
        continue
    }

    foreach ($processId in Get-ProcessTree -RootProcessId $service.pid) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Stopped $name process tree rooted at PID $($service.pid)."
}

Remove-Item -LiteralPath $statePath -Force
Write-Host 'Log files were preserved.'
