[CmdletBinding()]
param(
    [int]$HttpPort = 18080,
    [int]$ProxyPort = 8080,
    [ValidateSet('Proxy', 'Direct')]
    [string]$Mode = 'Proxy',
    [string]$DirectClientHost
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$logDirectory = Join-Path $repo '.local\session-logs'
$statePath = Join-Path $logDirectory 'kickflight-services.json'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null

function Assert-PortAvailable([int]$Port) {
    if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
        throw "TCP port $Port is already in use. Run scripts/stop-logged-services.ps1 or stop the existing process first."
    }
}

function Wait-ForListener([System.Diagnostics.Process]$Process, [int]$Port, [int]$TimeoutSeconds) {
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        if ($Process.HasExited) {
            throw "Process $($Process.Id) exited before listening on TCP port $Port."
        }
        if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
            return
        }
        Start-Sleep -Milliseconds 250
    }
    throw "Timed out waiting for TCP port $Port."
}

function Stop-ProcessTree([int]$RootProcessId) {
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $RootProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-ProcessTree -RootProcessId $child.ProcessId
    }
    Stop-Process -Id $RootProcessId -Force -ErrorAction SilentlyContinue
}

Assert-PortAvailable -Port $HttpPort
if ($Mode -eq 'Proxy') {
    Assert-PortAvailable -Port $ProxyPort
} elseif (-not $DirectClientHost) {
    throw '-DirectClientHost is required when -Mode Direct is selected.'
}

$serverOut = Join-Path $logDirectory "server-$stamp.out.log"
$serverErr = Join-Path $logDirectory "server-$stamp.err.log"
$proxyOut = Join-Path $logDirectory "proxy-$stamp.out.log"
$proxyErr = Join-Path $logDirectory "proxy-$stamp.err.log"
$powershell = (Get-Process -Id $PID).Path
$serverScript = Join-Path $PSScriptRoot 'run-local.ps1'
$proxyScript = Join-Path $PSScriptRoot 'run-android-capture-proxy.ps1'
$serverProcess = $null
$proxyProcess = $null

try {
    $serverArguments = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', "`"$serverScript`"",
        '-HttpPort', $HttpPort,
        '-EnableCapture'
    )
    if ($Mode -eq 'Direct') {
        $serverArguments += @('-DirectClientHost', $DirectClientHost)
    }
    $serverProcess = Start-Process -FilePath $powershell -ArgumentList $serverArguments `
        -RedirectStandardOutput $serverOut -RedirectStandardError $serverErr -WindowStyle Hidden -PassThru
    Wait-ForListener -Process $serverProcess -Port $HttpPort -TimeoutSeconds 45

    if ($Mode -eq 'Proxy') {
        $proxyProcess = Start-Process -FilePath $powershell -ArgumentList @(
            '-NoProfile',
            '-ExecutionPolicy', 'Bypass',
            '-File', "`"$proxyScript`"",
            '-ListenPort', $ProxyPort
        ) -RedirectStandardOutput $proxyOut -RedirectStandardError $proxyErr -WindowStyle Hidden -PassThru
        Wait-ForListener -Process $proxyProcess -Port $ProxyPort -TimeoutSeconds 20
    }

    [ordered]@{
        startedUtc = [DateTimeOffset]::UtcNow.ToString('o')
        mode = $Mode
        server = [ordered]@{
            pid = $serverProcess.Id
            port = $HttpPort
            stdout = $serverOut
            stderr = $serverErr
        }
        proxy = if ($proxyProcess) {
            [ordered]@{
                pid = $proxyProcess.Id
                port = $ProxyPort
                stdout = $proxyOut
                stderr = $proxyErr
            }
        } else { $null }
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statePath -Encoding utf8
} catch {
    if ($proxyProcess -and -not $proxyProcess.HasExited) {
        Stop-ProcessTree -RootProcessId $proxyProcess.Id
    }
    if ($serverProcess -and -not $serverProcess.HasExited) {
        Stop-ProcessTree -RootProcessId $serverProcess.Id
    }
    throw
}

Write-Host "Kick-Flight services started."
Write-Host "Mode:   $Mode"
Write-Host "Server: PID $($serverProcess.Id), TCP $HttpPort, logs $serverOut / $serverErr"
if ($proxyProcess) {
    Write-Host "Proxy:  PID $($proxyProcess.Id), TCP $ProxyPort, logs $proxyOut / $proxyErr"
}
Write-Host "State:  $statePath"
