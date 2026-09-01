[CmdletBinding()]
param(
    [int]$HttpPort = 8080,
    [int]$HttpsPort = 8443,
    [switch]$EnableCapture,
    [string]$DirectClientHost,
    [string]$CertificatePath,
    [string]$CertificatePassword
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$localDotnet = Join-Path $repo '.local\tools\dotnet\dotnet.exe'
$dotnetCommand = if (Test-Path -LiteralPath $localDotnet) { $localDotnet } else { 'dotnet' }
$env:HttpPort = [string]$HttpPort
$env:HttpsPort = [string]$HttpsPort
$env:Harness__PersistCaptures = if ($EnableCapture) { 'true' } else { 'false' }
if ($DirectClientHost) {
    $env:Harness__DirectClientHosts__0 = $DirectClientHost
}
if ($CertificatePath) {
    $env:Certificate__Path = (Resolve-Path -LiteralPath $CertificatePath).Path
    $env:Certificate__Password = $CertificatePassword
}

& $dotnetCommand run --project (Join-Path $repo 'src\KickFlight.BootstrapApi\KickFlight.BootstrapApi.csproj') --no-launch-profile
exit $LASTEXITCODE
