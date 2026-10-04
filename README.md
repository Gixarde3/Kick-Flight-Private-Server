# Kick Flight: The Fenix Returns

Servidor privado de comunidad para **Kick-Flight 2.11.0**. Este repositorio contiene la API compatible con el cliente, el servidor Photon basado en LuxonServer, los datos de juego editables y las herramientas para preparar el CDN y una APK parcheada.

La instancia pública corre en una VM de OCI. Docker Compose levanta la API, Photon, el CDN y la landing; la persistencia de jugadores usa PostgreSQL administrado por Neon. Caddy publica la web por HTTPS en `kick-flight-fenix.us.ci`.

## Instancia pública

- Sitio y descarga: [kick-flight-fenix.us.ci](https://kick-flight-fenix.us.ci/)
- APK Android 2.11.0: [descargar](https://kick-flight-fenix.us.ci/apk/KickFlight-2.11.0-remote-kickflightsg.apk)
- Estado de la API: [health/ready](https://kick-flight-fenix.us.ci/health/ready)

La APK ya apunta a esta instancia. Tras instalarla, el primer inicio requiere internet para bajar los recursos del juego desde el CDN. Las partidas usan Photon; la API y Photon son servicios separados dentro de la pila.

## Arquitectura desplegada

```text
Cliente Android
  ├─ HTTPS :443 ──> Caddy ──> Nginx
  │                              ├─ landing
  │                              ├─ /cdn/ ──> bundles del juego
  │                              └─ API HTTP, incluida la descarga de APK ──> ASP.NET Core
  ├─ gRPC :18081 ──> Nginx gRPC ──> API
  └─ Photon TCP/UDP ──> LuxonServer

API ── TLS ──> PostgreSQL en Neon
```

La VM OCI ejecuta los contenedores definidos en [`deploy/docker-compose.vps.external-db.yml`](deploy/docker-compose.vps.external-db.yml). Nginx entrega la landing y los bundles; reenvía las rutas HTTP del juego y la descarga de la APK a la API. Caddy termina HTTPS para `kick-flight-fenix.us.ci`. El modo de base externa omite el contenedor PostgreSQL local y lee `DATABASE_URL` del entorno; la documentación de despliegue usa Neon como proveedor.

El cliente llega a Photon por los puertos TCP/UDP configurados para NameServer, MasterServer y GameServer. El puerto público de gRPC pasa por un proxy Nginx dedicado. La base de datos no se publica desde la VM.

La portada está en [`deploy/site/index.html`](deploy/site/index.html) y ofrece español e inglés. Recuerda la selección en el navegador; si todavía no hay una selección guardada, usa el idioma del navegador y la sugerencia regional disponible. Los textos del juego están en `config/masters_translation.json` y se mantienen con `scripts/generate_translations.py`; esa tabla es independiente del idioma de la landing.

## Desarrollo local

Se necesita el SDK de .NET 8 para compilar y ejecutar la API. Inicializa también el submódulo de Photon:

```bash
git submodule update --init --recursive
```

Para levantar el servidor directo local, prepara la configuración ignorada por Git a partir del ejemplo y cambia `serverBaseUrl` por una dirección HTTP accesible desde el teléfono o emulador:

```bash
cp config/apk-direct-server.example.json config/apk-direct-server.local.json
./scripts/run-direct.sh
```

El servidor usa el puerto indicado en esa URL. Los scripts de configuración local, proxy Android, Compose de desarrollo y solución de problemas están descritos en [`docs/RECREATE_FROM_SCRATCH.md`](docs/RECREATE_FROM_SCRATCH.md), [`docs/ENVIRONMENT_REFERENCE.md`](docs/ENVIRONMENT_REFERENCE.md) y [`docs/ANDROID_SETUP.md`](docs/ANDROID_SETUP.md).

Para compilar la API y ejecutar las pruebas del repositorio:

```bash
dotnet test KickFlight.PrivateServer.sln --nologo
python3 tests/test_teamtype.py
```

## APK y recursos

El cliente Android se obtiene parcheando una APK base de Kick-Flight 2.11.0; no se compila desde el código fuente del juego. Para producir una APK local se requieren esa APK base, un keystore propio y las herramientas de Android indicadas en [`docs/RECREATE_FROM_SCRATCH.md`](docs/RECREATE_FROM_SCRATCH.md). Los archivos protegidos, los assets originales y los artefactos locales no se distribuyen en este repositorio.

El endpoint del servidor y el host Photon quedan grabados en la APK al construirla. `scripts/build-direct-apk.sh` prepara y firma el cliente; `KF_PHOTON=1` y `KF_PHOTON_HOST` activan y configuran Photon para una compilación remota. La guía [`deploy/VPS.md`](deploy/VPS.md) detalla el artefacto publicado y sus rutas.

Los recursos se definen en `config/resources/catalog.json`. `scripts/build-title-resource-catalog.py` actualiza el catálogo del juego y `scripts/update-apk-catalog-sha.py` registra el hash de la APK. `scripts/build-cdn-tree.py` reconstruye el árbol completo `/cdn/` a partir del catálogo y de los assets preparados localmente; la carpeta de assets debe existir fuera del repositorio. Revisa los argumentos y el destino antes de ejecutarlo, porque cada ejecución reemplaza el árbol CDN de salida.

## Despliegue

La configuración que representa el despliegue actual es la de VM con PostgreSQL externo:

```bash
docker compose --env-file .env \
  --project-name deploy \
  -f deploy/docker-compose.vps.external-db.yml up -d --build
```

`DATABASE_URL` y los valores de host se suministran desde archivos de entorno locales ignorados por Git. No pegues credenciales en comandos compartidos ni las agregues al repositorio. El Compose alternativo [`deploy/docker-compose.vps.yml`](deploy/docker-compose.vps.yml) incluye un PostgreSQL local para instalaciones que no usen Neon.

La guía [`deploy/VPS.md`](deploy/VPS.md) cubre la VM, reglas de red, la base externa, Caddy, la landing y el orden para generar la APK, el catálogo y el CDN. Incluye los endpoints de salud y comandos para operar el stack.

### CI/CD

El workflow [`deploy-vps-main.yml`](.github/workflows/deploy-vps-main.yml) despliega únicamente en `push` a `main`. Omite eventos atrasados si el commit ya no es la punta de `main` y serializa los despliegues. Se activa cuando el workflow y sus cambios llegan a `main`; no se ejecuta en pull requests ni tiene ejecución manual.

El despliegue selecciona los servicios según los archivos cambiados: API, Photon, CDN y Caddy se reconstruyen cuando corresponde; cambios en `deploy/site/` sincronizan la landing; cambios de `config/`, `content/` o generadores marcados fuerzan la reconstrucción de la pila y del árbol CDN. Cambios de Compose, GeoIP o gRPC fuerzan la pila completa. El workflow hace checkout recursivo de submódulos y compila las imágenes en la VM.

En GitHub, el environment `production` necesita estos secretos y variables:

| Tipo | Nombre |
| --- | --- |
| Secret | `VPS_SSH_PRIVATE_KEY` |
| Secret | `VPS_KNOWN_HOSTS` |
| Variable | `VPS_HOST` |
| Variable | `VPS_USER` |
| Variable | `VPS_APP_DIR` (ruta absoluta) |
| Variable opcional | `VPS_SSH_PORT` (por defecto `22`) |

La VM debe tener Docker Compose, `rsync`, `flock`, `curl` y Python 3. El usuario SSH debe ejecutar Docker sin `sudo`. Antes del primer despliegue, prepara en `VPS_APP_DIR` el `.env` de producción y el directorio persistente `.local/`, además del árbol de assets `octo_sorted/`; el workflow no sube estos datos ni crea la VM, Neon o sus reglas de red. `DATABASE_URL` permanece en el `.env` del host, nunca en GitHub. Consulta [la guía de despliegue](deploy/VPS.md) para preparar y verificar ese estado.

Antes del cambio, valida todas las fuentes habilitadas del catálogo. Después comprueba `/health/ready`, el SHA-256 de un recurso servido por `/cdn/` y, si cambió el sitio, el SHA-256 de la landing servida. Ante un fallo, intenta restaurar el código y árbol CDN previos y vuelve a construir y levantar el stack. No revierte migraciones ni datos de Neon. El workflow comprueba salud de runtime; las pruebas de .NET y Python se ejecutan aparte con los comandos de desarrollo de arriba.

## Estructura

| Ruta | Contenido |
| --- | --- |
| `src/KickFlight.BootstrapApi/` | API .NET 8, sesiones, estado del jugador, datos de juego y matchmaking gRPC |
| `submodules/luxonserver/` | servidor de partidas Photon/LuxonServer |
| `config/` | masters, fixtures y catálogo de recursos |
| `content/` | bundles y archivos generados para el cliente |
| `scripts/` | build de APK, datos, CDN, despliegue y herramientas de diagnóstico |
| `deploy/` | Compose, Caddy, Nginx, Photon y landing pública |
| `docs/` | configuración, despliegue, Android y documentación de ingeniería inversa |

Los archivos de trabajo como `.env`, la APK base, el keystore, los bundles grandes y los artefactos bajo `.local/` deben mantenerse fuera del control de versiones. [`PRESERVATION_POLICY.md`](PRESERVATION_POLICY.md) describe los límites del repositorio y [`docs/PHOTON_SERVER.md`](docs/PHOTON_SERVER.md) documenta el servidor Photon.
