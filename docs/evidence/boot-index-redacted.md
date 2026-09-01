# Transcripción redacted — 2026-08-31 UTC

```text
APK SHA-256: F79F1B48F86C4F5973C763CBC6C166BD6C42CC83D4E36ECA75D7D1CAB74AD8D1
Android: 15 / API 35, google_apis x86_64, NDK translation arm64-v8a

request 1
POST https://kickflight-api.grenge.jp/boot/index
Content-Type: application/octet-stream
Content-Length: 32
x-app-application-version: 2.11.0
x-app-asset-platform: 3
x-app-asset-revision: 0
x-app-adid: <redacted; present; length=36; short fingerprint retained only in ignored capture>
x-app-adjust-adid: <redacted; present; length=32; short fingerprint retained only in ignored capture>
body: <binary; 32 bytes; SHA-256=a60fba24253275afc9ca572618219bf877b25f92c9e2922004e61ee8651baaa2>

accepted response
HTTP 200
Content-Type: application/octet-stream
Content-Length: 96
x-app-status-code: 0
logical body after local D2C verification: {"assetVersion":12345,"smartBeatAvailableFlag":false,"rebateUrl":""}

observable result
GET https://kickflight-resource-api.grenge.jp/v1/list/12345/0
Accept: application/x-protobuf,x-octo-app/1
X-OCTO-KEY: <redacted; present; length=32; short fingerprint retained only in ignored capture>

accepted Octo response: protobuf Database { revision: 1 }, empty lists
screen: Ver.2.11.0 — TAP START
```

Todo host ajeno a los tres first-party recibió una respuesta local 451 o fallo TLS. El único destino abierto por el addon para tráfico first-party fue `127.0.0.1:18080`.
