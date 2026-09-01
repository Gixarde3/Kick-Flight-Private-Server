# Prompt histórico de continuación — Fase 1 (completada)

> Este archivo conserva el estado de entrada anterior para trazabilidad. El resultado vigente está en `PHASE1_RESULT.md`; las tareas pendientes descritas abajo ya fueron resueltas.

Actúa como agente principal de implementación. Continúa el trabajo existente hasta completar realmente la Fase 1 del servidor privado local de Kick-Flight. No te limites a analizar ni a proponer un plan: inspecciona el estado actual, reproduce el bloqueo, implementa el siguiente contrato, ejecuta el cliente Android y avanza iterativamente hasta que la APK deje atrás el error inicial y alcance el título/inicio o una pantalla posterior inequívoca.

## Rutas y alcance

- `SERVER_REPO`: `C:\Users\Gixar\Documentos\Variedad\Kick-Flight-Private-Server`
- `SOURCE_REPO`, estrictamente sólo lectura: `C:\Users\Gixar\Documentos\Variedad\Kick-Flight-Assets`
- APK original: `SOURCE_REPO\base.apk`
- SHA-256 obligatorio antes y después: `F79F1B48F86C4F5973C763CBC6C166BD6C42CC83D4E36ECA75D7D1CAB74AD8D1`

Todo código, scripts, pruebas, fixtures y documentación nuevos deben escribirse únicamente en `SERVER_REPO`. No modifiques, copies ni reorganices `SOURCE_REPO`. Su estado Git observado ya contiene `M .gitignore` y `?? server_revival_analysis/`; presérvalo y no intentes limpiarlo. No configures remote, no publiques, no hagas push y no uses comandos destructivos de Git.

El usuario autorizó instalar dependencias necesarias y confirmó que Docker Desktop/Daemon está activo. Aun así, mantén todos los cambios Android y de red limitados al AVD de pruebas y completamente reversibles.

## Estado actual confirmado

`SERVER_REPO` ya es un repositorio Git independiente inicializado con `git init`, sin remote y todavía sin commits. Conserva todos los archivos y cambios existentes.

Existe una solución .NET 8 funcional:

- `KickFlight.PrivateServer.sln`
- `src/KickFlight.BootstrapApi/`
- `tests/KickFlight.BootstrapApi.Tests/`
- `config/fixtures/`
- `scripts/`
- `docs/`

El servidor ASP.NET Core ya implementa:

- `/health/live` y `/health/ready`;
- routing estricto por `host + método + ruta`;
- los hosts `kickflight-api.grenge.jp`, `colorful-api-octo-sb.grenge.jp` y `kickflight-resource-api.grenge.jp`;
- fixtures JSON con cuerpos texto o Base64/binarios y headers configurables;
- recarga de fixtures por timestamp/tamaño sin recompilar;
- error local para rutas desconocidas, sin forward;
- logs JSON, correlation ID, redacción de secretos y captura opcional limitada;
- tamaño y SHA-256 completo del body, sin persistir secretos completos;
- rechazo 421 de hosts no permitidos.

No existe `HttpClient`, `TcpClient`, `WebRequest.Create` ni otra API de upstream en el código de producción. La prueba automatizada lo verifica.

Existe además un proxy TLS local-only:

- `scripts/mitm_local_only.py`
- `scripts/run-android-capture-proxy.ps1`

Su política actual es crítica y debe conservarse: todo host ajeno a los tres first-party recibe respuesta local 451; los tres first-party se reescriben exclusivamente a `127.0.0.1:18080`, conservando el `Host` original. Nunca permitas un destino histórico de Grenge ni conviertas este proxy en un proxy abierto.

## Herramientas ya instaladas

No reinstales sin necesidad:

- .NET SDK portátil 8.0.424: `SERVER_REPO\.local\tools\dotnet\dotnet.exe`
- ADB/platform-tools: `SERVER_REPO\.local\android-sdk\platform-tools\adb.exe` y una copia bajo `.local\tools\platform-tools\`
- Android command-line tools y emulator bajo `SERVER_REPO\.local\android-sdk\`
- mitmproxy 12.2.3: `C:\Program Files\mitmproxy\bin\mitmdump.exe`
- Python 3 con `capstone` y `pyelftools`
- script auxiliar ignorado `.local\disasm.py`
- Docker instalado y Daemon activo
- cmdlets PowerShell de certificados disponibles; OpenSSL no está instalado ni es necesario actualmente

AVDs creados durante el trabajo previo:

- API 29 `google_apis` x86_64: arranca, pero la APK falla con `INSTALL_FAILED_NO_MATCHING_ABIS`.
- API 29 `google_apis` ARM64: no puede ejecutarse en este host x86_64.
- `KickFlight_API35`, API 35 `google_apis` x86_64: funciona y ofrece NDK translation/Berberis para `arm64-v8a`. Éste es el AVD válido.

La APK se instaló y ejecutó sin modificar en `KickFlight_API35`. Unity 2018.4.11f1 e IL2CPP ARM64 arrancaron correctamente mediante Berberis.

## Verificación actual

El último resultado fue:

```text
13 pruebas superadas, 0 fallidas
APK SHA-256 correcto
Docker ready: true
ADB detectó emulator-5554 durante la prueba
```

Comandos:

```powershell
cd C:\Users\Gixar\Documentos\Variedad\Kick-Flight-Private-Server
.\.local\tools\dotnet\dotnet.exe test .\KickFlight.PrivateServer.sln --no-restore --nologo
.\scripts\verify-apk-hash.ps1
.\scripts\check-prerequisites.ps1 -AdbPath .\.local\android-sdk\platform-tools\adb.exe
```

Al terminar la sesión anterior se restauró todo:

- proxy Android: `null`;
- CA mitm del usuario eliminada;
- PIN temporal `1234` eliminado;
- aplicación detenida;
- AVD apagado;
- Kestrel y mitmproxy detenidos;
- puertos 8080 y 18080 libres.

No asumas que el AVD está corriendo. Arráncalo de nuevo y vuelve a aplicar proxy/CA de manera reversible siguiendo `docs/ANDROID_SETUP.md`.

## Evidencia dinámica confirmada

La ejecución real descifrada confirmó esta primera petición first-party:

```text
POST https://kickflight-api.grenge.jp/boot/index
Content-Type: application/octet-stream
Content-Length: 32
x-app-application-version: 2.11.0
x-app-asset-platform: 3
x-app-asset-revision: 0
```

Los headers `x-app-adid` y `x-app-adjust-adid` aparecieron, pero el harness sólo guardó presencia, longitud y fingerprint corto. Mantén esa redacción.

El body binario de 32 bytes cambia entre relanzamientos. Ejemplos de SHA-256 observados:

- `ffbfa36af8d3ed394cf4a517d3c12c9969eacc1759b21a8b7206f1951bacd1e1`
- `a60fba24253275afc9ca572618219bf877b25f92c9e2922004e61ee8651baaa2`

Un 404 estricto reproduce el error inicial. Después se creó `config/fixtures/boot-index.observation.json` con HTTP 200, `x-app-status-code: 200` y:

```json
{"assetVersion":0,"smartBeatAvailableFlag":false,"rebateUrl":""}
```

El cliente siguió mostrando:

```text
Communication Error
A communication error has occurred.
```

No apareció ninguna petición first-party posterior. Por tanto, ese JSON es una sonda negativa reproducible, no una respuesta válida. No documentes ni nombres el fixture como contrato completo hasta que la APK lo acepte.

La evidencia redacted está en:

- `docs/evidence/boot-index-redacted.md`
- `docs/DISCOVERED_STARTUP_FLOW.md`
- `docs/PHASE1_RESULT.md`
- captura local ignorada `captures/kickflight-phase1.png`

## Evidencia estática relevante

No repitas la extracción general. Usa los artefactos existentes de sólo lectura:

- `SOURCE_REPO\server_revival_analysis\PRIVATE_SERVER_REVIVAL_PLAN.md`
- `SOURCE_REPO\server_revival_analysis\README.md`
- `SOURCE_REPO\server_revival_analysis\protocol_inventory.json`
- `SOURCE_REPO\server_revival_analysis\il2cpp\dump.cs`
- `SOURCE_REPO\server_revival_analysis\il2cpp\script.json`
- `SOURCE_REPO\server_revival_analysis\il2cpp\stringliteral.json`
- `SOURCE_REPO\server_revival_analysis\il2cpp\il2cpp.h`
- `SOURCE_REPO\server_revival_analysis\apk_extracted\lib\arm64-v8a\libil2cpp.so`
- manifests JADX y `PIPELINE_OUTPUT_V3/report_v3.json` sólo cuando se llegue a Octo/assets

DTO confirmado en `dump.cs`:

```csharp
public class BootResponseData : ResponseDataBase
{
    public int assetVersion;
    public bool smartBeatAvailableFlag;
    public string rebateUrl;
}
```

Métodos/RVA ya localizados:

- `NetworkManager.GetRequestToData<T>`: generic RVA `0x19912DC`
- `NetworkManager.GetToData<T>`: generic RVA `0x1991360`
- `NetworkManager.GetResponceFromData<T>`: generic RVA `0x19F562C`
- `NetworkManager.GetFromData<T>`: generic RVA `0x19F5540`
- `NetworkManager.GetToJsonData<T>`: generic RVA `0x1991550`
- `NetworkManager.GetFromJsonData<T>`: generic RVA `0x19F55A8`
- `NetworkManager.GetD2CParallelInfo`: RVA `0x31B9308`
- `D2CManager.ToParallel`: RVA `0x1A6E0D8`
- `D2CManager.FromParallel`: RVA `0x1A6E7A8`
- `D2CParallelInfo(string,string)`: RVA `0x1A6F748`
- `D2CParallelInfo(byte[],byte[])`: RVA `0x1A72538`
- `D2CParallelInfo.SetInfo`: RVA `0x1A6F7DC`

La inspección ARM64 dirigida de `GetToData<T>` indicó esta cadena:

1. crea/obtiene un código basado en `ParallelCode` o en `NetworkManager._hash`;
2. genera un vector de 16 bytes;
3. llama a `GetD2CParallelInfo`;
4. serializa el DTO con JSON/`JsonUtility.ToJson`;
5. llama a `D2CManager.ToParallel`;
6. concatena datos auxiliares/vector con el resultado para producir `application/octet-stream`.

`D2CParallelInfo` contiene:

```text
byte[] _parallelCode
byte[] _parallelEc
int _fill
int _change
int _parallelSize
int _worldSize
```

La transformación parece personalizada, no MessagePack. El assembly contiene referencias a `MessagePackInternalAssembly`, pero el flujo de control de esta API usa los métodos JSON + GRE/D2C anteriores. No cambies a MessagePack sin evidencia dinámica o nativa directa.

Constantes recuperadas en `NetworkManager`:

```text
TO_CODE_SIZE = 256
TO_CODE_BYTE_SIZE = 32
TO_WORLD_SIZE = 128
TO_WORLD_EC_SIZE = 16
JSON_EMPTY = "{}"
```

La hipótesis más fuerte, todavía por demostrar, es que los 32 bytes de la petición vacía incluyen 16 bytes de vector/datos auxiliares y una transformación de `"{}"`. Debes confirmar el layout exacto antes de implementar la respuesta.

## Objetivo inmediato obligatorio

Reconstruye sólo lo necesario para que una respuesta mínima de `POST /boot/index` sea aceptada:

1. Reproduce primero el estado actual y confirma la misma petición y pantalla.
2. Analiza de forma dirigida `GetResponceFromData<T>`, `GetFromData<T>`, `GetD2CParallelInfo`, `D2CManager.ToParallel` y `D2CManager.FromParallel`; no desensambles toda `libil2cpp.so`.
3. Determina el layout exacto del cuerpo, el papel del vector de 16 bytes, `_hash`/`ParallelCode`, `_parallelEc`, `fill`, `change`, `parallelSize` y `worldSize`.
4. Usa la petición de `BootRequestData` vacío como vector de prueba conocido: el JSON lógico debe ser `"{}"`. Si necesitas conservar temporalmente bytes crudos para comparar, hazlo sólo bajo `captures/` ignorado, limita el tamaño y no captures ni publiques secretos.
5. Considera instrumentación dinámica local del AVD como oráculo si resulta más eficiente. Frida u otra herramienta puede instalarse porque el usuario autorizó dependencias, pero limita el hook a los métodos/RVA anteriores. No patches la APK salvo que proxy/CA/instrumentación sean insuficientes y exista evidencia concreta.
6. Implementa la transformación en `SERVER_REPO`, preferiblemente como componente probado y reutilizable del servidor o generador de fixtures.
7. Sustituye la sonda JSON por una respuesta binaria válida de `BootResponseData`.
8. Añade pruebas de vectores conocidas y una prueba contractual del fixture aceptado.
9. Limpia datos o fuerza cierre de la app, relanza desde estado conocido y confirma visualmente si aparece la siguiente petición.
10. Sólo entonces implementa la siguiente ruta alcanzada, siguiendo el mismo ciclo evidencia → DTO/caller → fixture mínimo → prueba → relanzamiento.

No implementes preventivamente las 539 rutas candidatas. Posibles rutas futuras (`auth/prepare`, `auth/create`, `auth/index`, `agreement/read`, `agreement/dataUsage`, `download/master`, `startup`, `home`) son sólo pistas hasta que el cliente las solicite.

## Captura Android reproducible

Procesos requeridos:

Terminal 1:

```powershell
cd C:\Users\Gixar\Documentos\Variedad\Kick-Flight-Private-Server
.\scripts\run-local.ps1 -HttpPort 18080 -EnableCapture
```

Terminal 2:

```powershell
cd C:\Users\Gixar\Documentos\Variedad\Kick-Flight-Private-Server
.\scripts\run-android-capture-proxy.ps1 -ListenPort 8080
```

Aplicar proxy al AVD:

```powershell
$adb = '.\.local\android-sdk\platform-tools\adb.exe'
.\scripts\configure-android-proxy.ps1 -AdbPath $adb -ServerAddress 10.0.2.2 -Port 8080 -Apply
```

La CA se genera en `certs/mitmproxy/`, ignorado. Android 15 requirió un PIN temporal y la instalación manual desde:

```text
Settings → Security & privacy → More security & privacy
→ Encryption & credentials → Install a certificate → CA certificate
```

El hash del certificado en la ejecución previa fue `c8750f0d.0`, pero verifícalo; una CA regenerada puede cambiarlo.

Lanzamiento:

```powershell
.\scripts\launch-and-capture.ps1 -AdbPath $adb -Install
```

Si automatizas la navegación UI, inspecciona primero con `uiautomator dump`; no uses coordenadas antiguas a ciegas.

## Restauración obligatoria al terminar cada sesión

Aunque la fase aún no esté terminada, no dejes el host ni Android alterados:

```powershell
.\scripts\restore-android-network.ps1 -AdbPath $adb -Apply
.\scripts\remove-android-test-ca.ps1 -AdbPath $adb -CertificateFileName <hash>.0 -ClearTestPin -Apply
& $adb shell am force-stop jp.grenge.kickflight
& $adb emu kill
```

Detén también Kestrel/mitmproxy y confirma que 8080/18080 quedan libres. El script de CA rechaza dispositivos que no sean emuladores; conserva esa protección.

## Seguridad y preservación

- Nunca contactes ni pruebes servidores históricos de Grenge.
- Nunca uses DNS/hosts globales del host.
- Nunca dejes que los tres hosts first-party salgan a Internet.
- No registres access tokens, cookies, UUIDs ni IDs publicitarios completos.
- No copies la APK, bundles, dumps completos, dummy DLLs ni assets a `SERVER_REPO`.
- No uses credenciales, API keys ni tokens históricos.
- No implementes endpoints admin/debug recuperados.
- No hagas root/remount de un dispositivo real. El único target permitido para cambios de credenciales es el AVD de prueba.
- No modifiques la APK original. Verifica su hash antes y después.
- Conserva `.gitignore` antes de crear nuevas capturas, certificados o binarios.
- No elijas licencia pública sin decisión explícita del usuario.

## Criterios para declarar Fase 1 completa

No la declares completa hasta demostrar todos:

1. `dotnet test` pasa.
2. El servidor arranca con el comando documentado.
3. Los tres hosts first-party están controlados localmente o bloqueados explícitamente.
4. Ninguna petición first-party se reenvía a Internet.
5. Logs/capturas no contienen secretos completos.
6. La APK ya no muestra el `Communication Error` inicial y alcanza título/inicio o una pantalla posterior inequívoca.
7. Hay evidencia de servidor, logcat redacted, secuencia ordenada y screenshot.
8. La reproducción funciona tras restaurar y volver a aplicar la red.
9. El hash final de `base.apk` coincide exactamente.
10. `docs/PHASE1_RESULT.md` queda actualizado con respuestas mínimas, límites y restauración.

Al completar, ejecuta al menos:

```powershell
.\.local\tools\dotnet\dotnet.exe test .\KickFlight.PrivateServer.sln --no-restore --nologo
.\scripts\verify-apk-hash.ps1
git remote -v
git status --short
```

No es necesario crear commit salvo que el usuario lo pida. Reporta claramente el estado Git y cualquier cambio preexistente.

## Entrega esperada

Empieza la respuesta final por el resultado observable del cliente. Incluye:

- pantalla exacta alcanzada;
- secuencia first-party confirmada en orden;
- fixtures/transformaciones realmente aceptados por la APK;
- comandos de reproducción;
- número de pruebas aprobadas;
- evidencia de no-upstream;
- hash final de la APK;
- archivos principales modificados;
- estado del repositorio Git independiente;
- siguiente bloqueo concreto, sólo si aún existe.

Distingue siempre entre hallazgo confirmado, inferencia y trabajo pendiente. No afirmes que un fixture es válido sólo porque responde HTTP 200: debe haber evidencia de que el cliente avanzó.
