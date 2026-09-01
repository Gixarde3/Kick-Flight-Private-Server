[CmdletBinding()]
param([string]$ApkPath = 'C:\Users\Gixar\Documentos\Variedad\Kick-Flight-Assets\base.apk')

$ErrorActionPreference = 'Stop'
$expected = 'F79F1B48F86C4F5973C763CBC6C166BD6C42CC83D4E36ECA75D7D1CAB74AD8D1'
if (-not (Test-Path -LiteralPath $ApkPath)) { throw "APK not found: $ApkPath" }
$actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $ApkPath).Hash
if ($actual -ne $expected) { throw "APK hash mismatch. Expected $expected, got $actual" }
Write-Output "OK base.apk SHA-256 $actual"
