# Resultado de Fase 1

## Estado observable

Fase 1 completa: la APK original alcanza la pantalla de título con `Ver.2.11.0` y `TAP START`, sin el `Communication Error` inicial. La reproducción parte de datos limpios de la app y sólo usa el AVD Android 15.

Secuencia first-party confirmada y aceptada:

1. `POST kickflight-api.grenge.jp/boot/index` → HTTP 200, `x-app-status-code: 0`, cuerpo D2C binario de 96 bytes.
2. `GET kickflight-resource-api.grenge.jp/v1/list/12345/0` → HTTP 200, protobuf Octo `Database` con revisión 1 y listas vacías.

## Implementado y verificado

- Repositorio Git nuevo, independiente y sin remote.
- Servidor ASP.NET Core .NET 8 con health checks, routing estricto por host/método/ruta, recarga de fixtures, cuerpos texto/binarios y headers configurables.
- Logging JSON con correlation ID, SHA-256 completo del body, preview limitada y redacción determinista.
- Proxy TLS local-only: los tres hosts permitidos se reescriben a loopback; cualquier otro host se responde localmente. No hay API cliente saliente en el servidor.
- Scripts reversibles de proxy Android y retirada de CA del AVD.
- Ejecución real del APK sin modificar, captura HTTPS y evidencia redacted.
- Códec GRE/D2C reutilizable y probado: AES-256-CBC, PKCS7, vector de 16 bytes antepuesto al ciphertext.
- Fixture Boot aceptado con DTO lógico mínimo y versión Octo sintética `12345`.
- Catálogo Octo protobuf mínimo aceptado; no publica ni copia assets del repositorio de preservación.
- Evidencia visual ignorada en `captures/after-minimal-octo-list.png` y transcripción redacted versionada.

## Límites y siguiente frontera

La versión Octo `12345` es un identificador local deliberado y el catálogo está vacío. No reconstruye el catálogo histórico ni descarga bundles. La siguiente fase empieza al tocar `TAP START`; debe observarse la ruta real de autenticación antes de añadir otro fixture.

## Reproducción

Terminal 1:

```powershell
.\scripts\run-local.ps1 -HttpPort 18080 -EnableCapture
```

Terminal 2:

```powershell
.\scripts\run-android-capture-proxy.ps1 -ListenPort 8080
```

Configurar el AVD y lanzar como indica [ANDROID_SETUP.md](ANDROID_SETUP.md). Para volver al estado de red anterior:

```powershell
.\scripts\restore-android-network.ps1 -Apply
.\scripts\remove-android-test-ca.ps1 -CertificateFileName c8750f0d.0 -ClearTestPin -Apply
```

La evidencia sanitizada está en [evidence/boot-index-redacted.md](evidence/boot-index-redacted.md). La captura PNG y logs crudos quedan en `captures/`, ignorados por Git. Todo tráfico no first-party fue contestado localmente con 451 o falló TLS; los tres hosts permitidos sólo se reescribieron a `127.0.0.1:18080`.
