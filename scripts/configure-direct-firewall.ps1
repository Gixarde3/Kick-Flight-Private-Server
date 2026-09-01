[CmdletBinding()]
param(
    [int]$Port = 18080,
    [switch]$Remove,
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
$ruleName = "KickFlight direct server $Port"
$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue

if (-not $Apply) {
    if ($Remove) {
        Write-Host "DRY RUN: would remove firewall rule '$ruleName'. Re-run with -Apply as Administrator."
    } elseif ($existing) {
        Write-Host "DRY RUN: firewall rule '$ruleName' already exists."
    } else {
        Write-Host "DRY RUN: would allow inbound TCP $Port from LocalSubnet on Private/Public profiles. Re-run with -Apply as Administrator."
    }
    exit 0
}

if ($Remove) {
    if ($existing) {
        Remove-NetFirewallRule -DisplayName $ruleName
        Write-Host "Removed firewall rule '$ruleName'."
    } else {
        Write-Host "Firewall rule '$ruleName' does not exist."
    }
    exit 0
}

if (-not $existing) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
        -Protocol TCP -LocalPort $Port -Profile Private,Public -RemoteAddress LocalSubnet | Out-Null
}
Write-Host "Firewall allows TCP $Port only from the local subnet."
