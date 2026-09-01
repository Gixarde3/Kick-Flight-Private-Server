[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$Id,
    [Parameter(Mandatory)]
    [string]$RequestPath,
    [Parameter(Mandatory)]
    [string]$FilePath,
    [Parameter(Mandatory)]
    [string]$LogicalName,
    [string]$Description = '',
    [string]$Host = 'kickflight-resource-api.grenge.jp',
    [string]$ContentType = 'application/octet-stream',
    [string]$CatalogPath = 'config\resources\catalog.json',
    [switch]$Copy
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$catalogFile = if ([IO.Path]::IsPathRooted($CatalogPath)) {
    [IO.Path]::GetFullPath($CatalogPath)
} else {
    [IO.Path]::GetFullPath((Join-Path $repo $CatalogPath))
}
$sourceFile = (Resolve-Path -LiteralPath $FilePath).Path

if (-not $RequestPath.StartsWith('/')) {
    throw '-RequestPath must start with a forward slash.'
}
if (-not (Test-Path -LiteralPath $catalogFile -PathType Leaf)) {
    throw "Resource catalog not found: $catalogFile"
}

if ($Copy) {
    $destinationDirectory = Join-Path $repo 'content\resources'
    New-Item -ItemType Directory -Force -Path $destinationDirectory | Out-Null
    $safeId = $Id -replace '[^A-Za-z0-9._-]', '_'
    $extension = [IO.Path]::GetExtension($sourceFile)
    $destination = Join-Path $destinationDirectory "$safeId$extension"
    Copy-Item -LiteralPath $sourceFile -Destination $destination -Force
    $sourceFile = $destination
}

$storedPath = if ($sourceFile.StartsWith($repo, [StringComparison]::OrdinalIgnoreCase)) {
    [IO.Path]::GetRelativePath($repo, $sourceFile).Replace('\', '/')
} else {
    $sourceFile
}
$sha256 = (Get-FileHash -LiteralPath $sourceFile -Algorithm SHA256).Hash.ToLowerInvariant()
$catalog = Get-Content -Raw -LiteralPath $catalogFile | ConvertFrom-Json
if ($catalog.schemaVersion -ne 1) {
    throw "Unsupported catalog schema: $($catalog.schemaVersion)"
}

$entry = [ordered]@{
    id = $Id
    enabled = $true
    host = $Host
    requestPath = $RequestPath
    logicalName = $LogicalName
    description = $Description
    sourcePath = $storedPath
    contentType = $ContentType
    sha256 = $sha256
}
$remaining = @($catalog.resources | Where-Object { $_.id -ne $Id })
$catalog.resources = @($remaining) + @([pscustomobject]$entry)
$catalog | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $catalogFile -Encoding utf8

Write-Host "Registered resource: $Id"
Write-Host "Request path:       $RequestPath"
Write-Host "Source:             $storedPath"
Write-Host "SHA-256:            $sha256"
Write-Host "Catalog:            $catalogFile"
