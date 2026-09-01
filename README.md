# Kick-Flight Private Server — bootstrap local

Repositorio independiente para preservar y reconstruir, de forma local, el protocolo de arranque de Kick-Flight 2.11.0. No contiene la APK, assets protegidos, credenciales históricas ni código copiado de la aplicación.

El estado actual es un arnés .NET 8 ejecutable y probado. Intercepta los tres hosts first-party, registra observaciones redacted y sólo responde con fixtures locales. La ejecución real confirmó y aceptó dos contratos mínimos: `POST /boot/index` con GRE/D2C (AES-256-CBC/PKCS7) y `GET /v1/list/12345/0` con una base Octo protobuf vacía. La APK alcanza la pantalla `TAP START` de la versión 2.11.0.

## Inicio rápido del servidor

```powershell
.\scripts\check-prerequisites.ps1
.\scripts\run-local.ps1 -HttpPort 8080
```

Health checks: `http://localhost:8080/health/live` y `http://localhost:8080/health/ready`.

Para la captura Android HTTPS se usan dos procesos:

```powershell
.\scripts\run-local.ps1 -HttpPort 18080 -EnableCapture
.\scripts\run-android-capture-proxy.ps1 -ListenPort 8080
```

Para ejecutarlos en segundo plano y conservar toda la salida en `.local/session-logs/`:

```powershell
.\scripts\start-logged-services.ps1
.\scripts\get-logged-services.ps1 -Tail 50
.\scripts\stop-logged-services.ps1
```

Cada inicio crea archivos separados para `stdout` y `stderr`; el archivo
`.local/session-logs/kickflight-services.json` identifica la sesión activa y
las rutas exactas de sus logs. La parada conserva los logs para diagnóstico.

Para una APK generada en modo directo no hace falta proxy ni CA:

```powershell
.\scripts\update-direct-server-ip.ps1 -Apply
.\scripts\build-direct-apk.ps1
.\scripts\configure-direct-firewall.ps1 -Apply # PowerShell como administrador
.\scripts\start-logged-services.ps1 -Mode Direct -DirectClientHost 192.168.1.34
```

La URL usada por el generador se define en
`config/apk-direct-server.local.json`. El servidor directo sólo acepta el host
LAN configurado y continúa sin tener ninguna ruta upstream.
En el teléfono se deja el proxy Wi-Fi en `Ninguno`; la APK directa utiliza HTTP
LAN y no necesita la CA de mitmproxy.

## Recursos y CDN local

Las respuestas pequeñas del backend se mantienen en `config/fixtures/`. Los
bundles, audio, vídeo y otros archivos grandes se registran por separado en
`config/resources/catalog.json`; el servidor los entrega por streaming, admite
rangos HTTP y verifica el SHA-256 antes de publicar cada entrada.

Para listar las rutas que el cliente pidió y todavía no existen:

```powershell
.\scripts\analyze-missing-requests.ps1
```

Para añadir un recurso conservando el archivo en su ubicación actual:

```powershell
.\scripts\add-resource.ps1 -Id recurso-001 -RequestPath /cdn/recurso.bundle `
  -FilePath C:\ruta\recurso.bundle -LogicalName "Nombre por identificar" `
  -Description "Descripción del contenido"
```

Con `-Copy`, el script copia el archivo a `content/resources/`. El catálogo se
recarga automáticamente; no hace falta recompilar ni reiniciar el servidor.

`update-direct-server-ip.ps1` usa por defecto el adaptador activo con gateway.
Para una zona móvil puede indicarse su nombre con `-InterfaceAlias` y el script
actualizará la URL conservando el puerto existente.

Después se aplica el proxy del emulador con `configure-android-proxy.ps1`. La instalación y retirada de la CA se explican en [docs/ANDROID_SETUP.md](docs/ANDROID_SETUP.md). El proxy TLS responde localmente a todo host no permitido y reescribe exclusivamente los tres hosts first-party a `127.0.0.1:18080`; no existe ruta de forward a Grenge.

## Pruebas

```powershell
.\.local\tools\dotnet\dotnet.exe test .\KickFlight.PrivateServer.sln --nologo
```

Consulta [docs/PHASE1_RESULT.md](docs/PHASE1_RESULT.md) para el resultado observado y [PRESERVATION_POLICY.md](PRESERVATION_POLICY.md) para los límites del repositorio.
