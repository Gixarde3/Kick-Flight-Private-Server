[CmdletBinding()]
param(
    [string]$LogDirectory = '.local\session-logs',
    [string]$OutputPath = '.local\reports\missing-requests.json'
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$resolvedLogDirectory = if ([IO.Path]::IsPathRooted($LogDirectory)) {
    [IO.Path]::GetFullPath($LogDirectory)
} else {
    [IO.Path]::GetFullPath((Join-Path $repo $LogDirectory))
}
$resolvedOutputPath = if ([IO.Path]::IsPathRooted($OutputPath)) {
    [IO.Path]::GetFullPath($OutputPath)
} else {
    [IO.Path]::GetFullPath((Join-Path $repo $OutputPath))
}

$records = foreach ($file in Get-ChildItem -LiteralPath $resolvedLogDirectory -Filter 'server-*.out.log' -File) {
    foreach ($line in Get-Content -LiteralPath $file.FullName) {
        try { $event = $line | ConvertFrom-Json } catch { continue }
        if ($event.Category -ne 'FixtureRouting' -or $event.Message -notlike 'No local fixture*') { continue }
        $method = [string]$event.State.Method
        $path = [string]$event.State.Path
        [pscustomobject]@{
            timestamp = ([DateTimeOffset]$event.Timestamp).ToString('o')
            method = $method
            host = [string]$event.State.Host
            path = $path
            kind = if ($method -in @('GET', 'HEAD')) { 'resource-candidate' } else { 'api' }
            sourceLog = $file.Name
        }
    }
}

$summary = @($records | Group-Object method, host, path, kind | ForEach-Object {
    $first = $_.Group | Select-Object -First 1
    [pscustomobject]@{
        kind = $first.kind
        method = $first.method
        host = $first.host
        path = $first.path
        occurrences = $_.Count
        firstSeen = ($_.Group | Sort-Object timestamp | Select-Object -First 1).timestamp
        lastSeen = ($_.Group | Sort-Object timestamp | Select-Object -Last 1).timestamp
    }
} | Sort-Object kind, path)

$outputDirectory = Split-Path -Parent $resolvedOutputPath
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
[ordered]@{
    generatedUtc = [DateTimeOffset]::UtcNow.ToString('o')
    missing = $summary
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $resolvedOutputPath -Encoding utf8

if ($summary.Count -eq 0) {
    Write-Host 'No missing local routes were found.'
} else {
    $summary | Format-Table kind, method, path, occurrences, firstSeen, lastSeen -AutoSize
}
Write-Host "Report: $resolvedOutputPath"
