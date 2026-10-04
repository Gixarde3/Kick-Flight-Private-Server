# Kick-Flight en un VPS con Docker Compose

Esta pila arranca PostgreSQL, la API .NET, el CDN nginx y Luxon/Photon en un solo host Linux. Usa el Compose
separado `deploy/docker-compose.vps.yml`; no modifica el Compose local ni el despliegue TrueNAS. Las imágenes
se construyen para la arquitectura del VPS, incluida ARM64 (por ejemplo, Oracle Ampere).

## Requisitos

- Un VPS Linux con Docker Engine y Docker Compose v2 (v2.24.4 o posterior para el override de base externa).
- IPv4 pública estable o un nombre DNS que apunte a ella.
- Puertos TCP 80 y 443 para la página con HTTPS automático; además 18080, 18081, 5055, 5056 y 5058.
  Abre también UDP 5055, 5056 y 5058.
- Para la configuración completa de Luxon, abrir TCP y UDP 27000–27002 también.
- Espacio persistente para PostgreSQL y aproximadamente 1 GB o más para los bundles del cliente.

Los puertos 18080 (API/CDN) y 18081 (gRPC) usan TCP. Photon requiere UDP y TCP: el NameServer anuncia
Master/Game y el cliente puede usar ambos transportes. La API solo queda en la red privada de Compose. El
puerto público 18081 termina en nginx, que solo reenvía `/openmatch.Frontend/GetAssignments`; otras rutas,
incluidas `/diag`, reciben 404. `/diag`, `/gym` y `/gym/*` también se bloquean en el frontend HTTP.
El servicio Caddy escucha en 80/443 en el host y reenvía las peticiones al CDN existente en 18080. Caddy
obtiene y renueva automáticamente el certificado de Let's Encrypt para `kick-flight-fenix.us.ci`; conserva
certificados y estado en los volúmenes Docker `caddy-data` y `caddy-config`. El DNS A del dominio debe
apuntar a la IP pública del VPS y el firewall de OCI y el del host deben permitir TCP 80/443.
La portada pública se sirve desde `deploy/site/index.html` en `/` mediante el contenedor `cdn`; usa la ruta
actual `/apk/KickFlight-2.11.0-remote-kickflightsg.apk` para descargar la APK. En una instalación limpia, la
APK es el único archivo que se instala manualmente; el primer arranque descarga los recursos del juego desde
el CDN del VPS, por lo que se requiere conexión a internet.

## Preparar catálogo, APK y assets

El endpoint `/health/ready` comprueba el catálogo entero: cada ruta `sourcePath` debe existir y coincidir con
su SHA-256. En el catálogo actual hay **36 fuentes bajo `.local/`**: la APK
`.local/KickFlight-2.11.0-remote-kickflightsg.apk` y 35 bundles generados en
`.local/weapon-costume-fallbacks/`. Por eso copiar únicamente `octo_sorted/` no deja listo el release.

Prepara junto al checkout la carpeta `Kick-Flight-Assets/octo_sorted/` con los bundles que corresponden al
catálogo y a `config/`/`content/`. Los sourcePaths del proyecto y los generadores de fallback resuelven esa
ruta como una carpeta hermana del repositorio. El árbol suele ser alrededor de 1 GB. Si lo guardas en otro
lugar, crea el enlace relativo `../Kick-Flight-Assets` hacia esa carpeta para los generadores y define la
misma ubicación en `KF_ASSETS_PATH`.

```sh
git submodule update --init --recursive
mkdir -p ../Kick-Flight-Assets
# Copia/sincroniza aquí el directorio octo_sorted con los bundles fuente del juego.
```

Los generadores de bundles requieren Python 3 y UnityPy 1.25.3. La APK también se debe compilar con los
requisitos de `scripts/build-direct-apk.sh`: `base.apk` original, Java, apktool 3.0.3 y Android build-tools
35.0.0. Para ARM64 puedes preparar los assets/APK en otra máquina y sincronizar los resultados junto con el
checkout; el Compose compila Luxon en la arquitectura nativa del VPS.

Genera una APK de producción con el endpoint público del VPS y el Photon NameServer. El **nombre de salida
debe conservarse**: lo usa la entrada actual del catálogo.

```sh
KF_PUBLIC_HOST="$(awk -F= '$1=="KF_PUBLIC_HOST" {print $2}' deploy/.env)"
KF_HTTP_PORT="$(awk -F= '$1=="KF_HTTP_PORT" {print $2}' deploy/.env)"
SERVER_BASE_URL="http://${KF_PUBLIC_HOST}:${KF_HTTP_PORT}" \
KF_PHOTON=1 \
KF_PHOTON_HOST="${KF_PUBLIC_HOST}" \
OUTPUT_APK=.local/KickFlight-2.11.0-remote-kickflightsg.apk \
scripts/build-direct-apk.sh
```

Ahora regenera el catálogo **después** de producir la APK. Este paso calcula su SHA-256 actual, vuelve a
crear los 35 clones físicos de arma desde los donantes de `octo_sorted/`, y ejecuta los generadores de
miniaturas que forman parte del catálogo. Así los hashes fijados en `catalog.json` coinciden con los bytes
que se servirán. Antes, incrementa `revision` en `title-minimum.json` y añade la revisión anterior a
`fromRevisions`. El builder no incrementa esa versión: sin el cambio, los clientes con la revisión anterior
podrían reutilizar los recursos cacheados y no descargar las fuentes actualizadas.

```sh
python3 - <<'PY'
import json
from pathlib import Path

path = Path("config/resources/title-minimum.json")
title = json.loads(path.read_text(encoding="utf-8"))
previous = int(title["revision"])
title["revision"] = previous + 1
title["fromRevisions"] = sorted(set(title.get("fromRevisions", [])) | {previous})
path.write_text(json.dumps(title, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Octo title revision: {previous} -> {title['revision']}; added fromRevision {previous}")
PY
python3 -m venv .local/assets-venv
.local/assets-venv/bin/pip install UnityPy==1.25.3
.local/assets-venv/bin/python scripts/build-title-resource-catalog.py \
  --server-base-url "http://${KF_PUBLIC_HOST}:${KF_HTTP_PORT}"
python3 scripts/update-apk-catalog-sha.py
python3 scripts/build-cdn-tree.py --assets-root "$(realpath ../Kick-Flight-Assets)" --repo-root .
```

`build-title-resource-catalog.py` actualiza las filas CDN administradas, pero no toca las filas `apk-*`.
Por eso `update-apk-catalog-sha.py` va después de generar el catálogo: actualiza el hash de la APK recién
compilada en `config/resources/catalog.json`. Sin ese paso, `/health/ready` rechaza el catálogo aunque el
archivo de la APK exista.

`build-title-resource-catalog.py` selecciona ese entorno para ejecutar `scripts/add_weapon_costume_aliases.py`
y `scripts/build-kicker-skin-thumbnail-bundles.py`; ambos toman los assets fuente del árbol configurado en
el catálogo. Para no compilar el APK en el VPS, copia a ese mismo checkout el artefacto con el nombre exacto,
el catálogo/fixtures regenerados y los bundles generados bajo `.local/` antes de levantar Compose.

El API lee `config/`, `content/` y `.local/` en modo solo lectura. PostgreSQL conserva las cuentas y el
progreso en el volumen Docker `postgres-data`; los bundles permanecen en el directorio de assets del host.
No se necesita montar ni publicar el puerto 5432.

## Configurar host y contraseña

```sh
cp deploy/.env.vps.example deploy/.env
openssl rand -hex 32
```

Edita `deploy/.env`: asigna a `KF_PUBLIC_HOST` la IPv4 pública o el DNS, sin `http://` ni puerto, y pega el
secreto aleatorio en `KF_DB_PASSWORD`. Si guardas los assets en otra ubicación, cambia `KF_ASSETS_PATH` a
una ruta absoluta. El archivo `.env` contiene una credencial y no debe publicarse.

La dirección se aplica en dos sitios: Luxon responde a los clientes con esa IP/DNS para los endpoints de
Photon; la API permite ese host en las peticiones del juego. La API prueba la salud de Photon usando el DNS
interno de Compose `photon`, así que no depende de que el VPS pueda hacer hairpin hacia su propia IP pública.

## Construir e iniciar

```sh
docker compose --env-file deploy/.env -f deploy/docker-compose.vps.yml config
docker compose --env-file deploy/.env -f deploy/docker-compose.vps.yml up -d --build
docker compose --env-file deploy/.env -f deploy/docker-compose.vps.yml ps
```

La primera compilación de Luxon descarga dependencias y puede tardar varios minutos. PostgreSQL debe estar
healthy antes de que arranque la API; Photon también debe estar healthy. Nginx espera a que la API esté
healthy. La API aplica migraciones de la base de datos al iniciar.

### Usar Neon u otro PostgreSQL externo

Si PostgreSQL vive fuera del VPS, usa `deploy/docker-compose.vps.external-db.yml`. Este modo levanta API,
Photon, CDN y gRPC, y conecta la API al `DATABASE_URL` del `.env` en la raíz del repositorio. La URL estándar
`postgresql://usuario:contraseña@host/base?sslmode=require` se convierte a parámetros de Npgsql al iniciar;
la conexión exige TLS. No copies la URL a `deploy/.env` ni a un archivo versionado.

Desde la raíz del repositorio:

```sh
docker compose --env-file .env -f deploy/docker-compose.vps.external-db.yml config
docker compose --env-file .env -f deploy/docker-compose.vps.external-db.yml up -d --build
docker compose --env-file .env -f deploy/docker-compose.vps.external-db.yml ps
```

El archivo externo omite el contenedor PostgreSQL local y su volumen; no combines este modo con
`docker-compose.vps.yml`. Conserva los montajes de `config/`, `content/`, `.local/` y `Kick-Flight-Assets`:
el API los necesita para validar el catálogo y servir las fuentes. Los bundles grandes pueden migrarse después
a un CDN externo; habrá que actualizar las URL del catálogo y comprobar `/health/ready` antes de retirar ese
montaje.

En el firewall del proveedor y el firewall del sistema abre los puertos de la tabla anterior. No abras
5432, 8080 ni 5088. 5088 es el panel web de Luxon y no hace falta para jugar.

## Crear una APK para este VPS

La dirección del servidor queda parcheada dentro del cliente; configurar Compose no cambia una APK anterior.
Usa el flujo de generación anterior antes de construir CDN y desplegar. Si cambias `KF_HTTP_PORT`, se
actualiza el valor usado para `SERVER_BASE_URL`. Mantén `KF_DIAG`, `KF_NRE_LR` y otras variables de
diagnóstico desactivadas para el release. La ruta `/apk/remote` sirve la APK con el nombre de catálogo.

## Comprobar y operar

```sh
curl -fsS http://PUBLIC_HOST:18080/health/live
curl -m 15 -fsS http://PUBLIC_HOST:18080/health/ready
curl -i http://PUBLIC_HOST:18080/diag                 # debe devolver 404
docker compose --env-file deploy/.env -f deploy/docker-compose.vps.yml logs --tail=100
```

`/health/ready` comprueba el catálogo, fixtures y conectividad con Photon. La prueba real es instalar la APK
en un teléfono fuera de la red del VPS, descargar recursos, iniciar batalla, jugar hasta el resultado y
reiniciar el stack comprobando que la misma cuenta conserve su progreso.

Para detener y volver a iniciar los contenedores sin borrar datos:

```sh
docker compose --env-file deploy/.env -f deploy/docker-compose.vps.yml down
docker compose --env-file deploy/.env -f deploy/docker-compose.vps.yml up -d
```

No uses `down -v` salvo que quieras borrar permanentemente la base de datos de jugadores.
