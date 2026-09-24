# APK de trazas y análisis nativo

`scripts/diag-apk-trace.py` construye un APK con las sondas `KFDIAG` y `KF_NRE_LR` que ya existen en
`scripts/patch-il2cpp-endpoints.py`, captura artefactos locales de logcat/tombstone y analiza archivos guardados.
No añade código de instrumentación nuevo: integra las sondas existentes. El perfil usa los parches de producción del
builder tal como están, incluidos los parches actuales de `libunity.so`. Para que baseline y DIAG compartan la misma
configuración, ambos se construyen con el mismo `build-direct-apk.sh`, incluida su transformación de
`AndroidManifest.xml`.

## Validar los deltas sin construir

El dry-run lee `base.apk`, copia los miembros necesarios a una carpeta temporal, llama las mismas funciones de parcheo
que usa el builder y valida cada guard de bytes. No modifica el APK de entrada, el servidor, un AVD ni los datos del
cliente.

```bash
python3 scripts/diag-apk-trace.py build \
  --source-apk base.apk \
  --base-url http://10.0.2.2:18080 \
  --flow photon --photon-host 51.79.241.70 \
  --compare-baseline \
  --dry-run > .local/diag-apk-plan.json
```

El perfil Photon predeterminado fija `KF_PHOTON=1` y `KF_PHOTON_HOST=51.79.241.70`, como en
[PHOTON_SERVER.md](PHOTON_SERVER.md). Para una corrida offline, usa `--flow offline` para baseline y DIAG por igual.
El JSON guarda SHA-256 del APK y de cada miembro binario, los offsets y bytes `from`/`to` de metadatos, IL2CPP y
`libunity.so`, además del SHA de los dos scripts de build/parcheo. `--compare-baseline` calcula el delta de parches
de la misma variante al activar `KF_DIAG` y `KF_NRE_LR`. Un guard fallido detiene el proceso.

## Construir el perfil

```bash
python3 scripts/diag-apk-trace.py build \
  --source-apk base.apk \
  --base-url http://10.0.2.2:18080 \
  --flow photon --photon-host 51.79.241.70 \
  --compare-baseline \
  --output .local/artifacts/KickFlight-2.11.0-DIAG.apk
```

El wrapper fuerza `KF_DIAG=1`, `KF_NRE_LR=1`, `KF_PHOTON=1` y `KF_PHOTON_HOST=51.79.241.70` por defecto. Quita del
entorno los modos que desvían comportamiento (`KF_UNLOAD_BYPASS`, `KF_FORCE_GAME_SCENE`,
`KF_UNITY_NO_ALLOCATOR_REBIND`, `KF_NO_READY_SCENE` y `KF_RESULT_DIAG`). Así se incluyen las sondas existentes junto a los parches actuales de
producción, incluyendo el rebinding de asignadores de Unity y el parche en `libunity.so+0x614c00`. No se agrega una
sonda nueva a `libunity` ni se modifica ese binario fuera de la tabla vigente.

El builder agrega `android:debuggable="true"`, `android:allowNativeHeapPointerTagging="false"` y `android:largeHeap="true"`
al manifest, igual que para el baseline construido con ese script. El sidecar registra los SHA-256 de los manifests de
entrada/salida. Compara el reporte real de los parches nativos/metadatos con el dry-run antes de aceptar el manifiesto;
también registra SHA-256 del APK, del origen y de los scripts de build/parcheo. El APK queda firmado con el keystore
local de desarrollo del builder.

El delta DIAG frente al baseline incluye dos slots sustituidos por caves que añaden trazas: `libil2cpp.so+0x1570ff0`
(guard de `SetParamVelocity`) y `libil2cpp.so+0x1576f18` (comparación de `IsReconnectEnable`). Esas caves incluyen la
comprobación o comparación desplazada junto con el registro de KFDIAG. El diff estático no prueba equivalencia
funcional; la lectura del cuerpo parcheado y la ausencia de cambios en `libunity.so` acotan el cambio a las sondas ya
existentes y los parches de producción representados.

## Capturar después de un fallo

La captura no limpia buffers ni reinicia procesos. Solo ejecuta lecturas ADB explícitas, guarda los buffers existentes
y trata de leer el tombstone más reciente si Android permite acceso. Si el sistema oculta `/data/tombstones`, conserva
los logcat y anota el motivo en `capture.json`.

```bash
python3 scripts/diag-apk-trace.py capture --serial emulator-5562
```

La carpeta `.local/diag-runs/<UTC>-<serial>/` contiene `logcat-threadtime.txt`, `logcat-crash-buffer.txt`, un
tombstone cuando fue legible, `capture.json` con comandos/hashes y `analysis.json`. `capture` requiere que el operador
lo invoque con un serial concreto; los comandos `build --dry-run` y `analyze` no usan ADB.

## Analizar artefactos existentes

```bash
python3 scripts/diag-apk-trace.py analyze \
  --logcat .local/diag-runs/20260924T070000Z-emulator-5562/logcat-threadtime.txt \
  --tombstone .local/diag-runs/20260924T070000Z-emulator-5562/tombstone_42 \
  --output .local/diag-runs/20260924T070000Z-emulator-5562/analysis.json
```

El reporte conserva los SHA-256, los últimos valores `KFDIAG`, cambios de escena, las líneas Scudo/SIGABRT y los
frames nativos (`módulo+PC`). Cuando los timestamps lo permiten calcula el intervalo desde `HomeScene`. También puede
compararse `scudoFrameSignatures` entre corridas; por ejemplo, el backtrace repetido en `UnityGfxDeviceW` con frames
de `libunity.so` como `0x4d6738`, `0x574484`, `0x573fc8` y `0xa6631c` indica que la detección vuelve a ocurrir en la
misma ruta de deallocación observada.

Ese stack identifica dónde Scudo detectó un header de heap corrupto; por sí solo no identifica la escritura anterior
que lo dañó ni qué objeto fue asignado allí. `KFDIAG` ayuda a ordenar estados IL2CPP cercanos en el tiempo, pero no
traza las asignaciones nativas del hilo `UnityGfxDeviceW`. Mantener esa limitación explícita al reportar resultados.

La captura queda separada del loop ADB descrito en [ADB_LOOP.md](ADB_LOOP.md): escalar screenshots a unos 720 px y
mantener los logs crudos fuera del prompt sigue aplicando.
