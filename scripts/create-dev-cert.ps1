[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [SecureString]$PfxPassword,
    [string]$OutputDirectory = (Join-Path (Split-Path -Parent $PSScriptRoot) 'certs')
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$root = $null
$leaf = $null
try {
    $root = New-SelfSignedCertificate `
        -Subject 'CN=Kick-Flight Local Development Root CA' `
        -FriendlyName 'Kick-Flight Local Development Root CA (temporary generation)' `
        -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 `
        -KeyExportPolicy Exportable -KeyUsage CertSign,CRLSign,DigitalSignature `
        -TextExtension @('2.5.29.19={critical}{text}ca=1&pathlength=0') `
        -CertStoreLocation 'Cert:\CurrentUser\My' `
        -NotAfter (Get-Date).AddYears(5)

    $leaf = New-SelfSignedCertificate `
        -Subject 'CN=kickflight-api.grenge.jp' `
        -DnsName @('kickflight-api.grenge.jp','colorful-api-octo-sb.grenge.jp','kickflight-resource-api.grenge.jp','localhost') `
        -Signer $root -KeyAlgorithm RSA -KeyLength 2048 -HashAlgorithm SHA256 `
        -KeyExportPolicy Exportable -KeyUsage DigitalSignature,KeyEncipherment `
        -TextExtension @('2.5.29.19={critical}{text}ca=0','2.5.29.37={text}1.3.6.1.5.5.7.3.1') `
        -CertStoreLocation 'Cert:\CurrentUser\My' `
        -NotAfter (Get-Date).AddYears(2)

    Export-Certificate -Cert $root -FilePath (Join-Path $OutputDirectory 'kickflight-dev-root.cer') -Force | Out-Null
    Export-PfxCertificate -Cert $leaf -FilePath (Join-Path $OutputDirectory 'kickflight-server.pfx') -Password $PfxPassword -Force | Out-Null
    @{
        generatedUtc = [DateTimeOffset]::UtcNow.ToString('o')
        rootThumbprint = $root.Thumbprint
        serverThumbprint = $leaf.Thumbprint
        dnsNames = @('kickflight-api.grenge.jp','colorful-api-octo-sb.grenge.jp','kickflight-resource-api.grenge.jp','localhost')
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputDirectory 'certificate-manifest.json') -Encoding utf8
    Write-Output "Created ignored development certificates under $OutputDirectory"
}
finally {
    if ($leaf) { Remove-Item -LiteralPath "Cert:\CurrentUser\My\$($leaf.Thumbprint)" -Force -ErrorAction SilentlyContinue }
    if ($root) { Remove-Item -LiteralPath "Cert:\CurrentUser\My\$($root.Thumbprint)" -Force -ErrorAction SilentlyContinue }
}
