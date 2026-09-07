# CONTINUATION PROMPT: KICK-FLIGHT PRIVATE SERVER & CLIENT REVERSE ENGINEERING

> **Propósito**: Este documento es la fuente canónica y exhaustiva de estado, arquitectura, hallazgos de ingeniería inversa, diagnósticos IL2CPP/ARM64, base de datos de assets, y roadmap prioritario para la resurrección integral de **Kick-Flight 2.11.0** con su servidor privado C# ASP.NET Core (`KickFlight.BootstrapApi`).

---

## 1. Entorno de Ejecución y Conectividad

- **Repositorio Servidor**: `/Users/marcochavez/Documents/variedad/Kick-Flight-Private-Server`
- **Repositorio Assets**: `/Users/marcochavez/Documents/variedad/Kick-Flight-Assets`
- **Dispositivo Físico Primario**: Xiaomi POCO F6 Pro (`3d3dc71d`), Snapdragon 8 Gen 2 / Adreno 750, 12GB RAM, Android 16 / HyperOS 3.0, resolución 1220x2712.
- **Dispositivo Secundario**: Emulador Android API 35 ARM64 (`emulator-5554`, 1080x2340).
- **Servidor Local LAN**: Mac ejecutándose en `http://192.168.1.141:18080` (lanzado como daemon mediante `./scripts/run-local.sh`).
- **APK Instalada**: `.local/artifacts/KickFlight-2.11.0-direct-192.168.1.141-18080.apk` (conexión HTTP directa sin proxy ni certificados MITM, parcheada con `scripts/patch-il2cpp-endpoints.py` y `scripts/build-direct-apk.sh`).
- **Binario IL2CPP de referencia (sin parchear)**: `.local/apk-direct-work/build.T03dt2/decoded/lib/arm64-v8a/libil2cpp.so`
- **Metadata IL2CPP**: `.local/apk-direct-work/build.T03dt2/decoded/assets/bin/Data/Managed/Metadata/global-metadata.dat`
- **Tests unitarios**: 22/22 pasados (`dotnet test`).
- **MasterVersion**: `demo-master-v18`

### Regla estricta de screenshots
Toda captura de pantalla del dispositivo DEBE redimensionarse a ~720px de ancho antes de ser vista:
```bash
adb -s 3d3dc71d exec-out screencap -p > /tmp/poco_raw.png && sips --resampleWidth 720 /tmp/poco_raw.png --out /tmp/poco_720.png
```

---

## 2. BUGS PENDIENTES (2 restantes)

### BUG A: La música de fondo (BGM) NO hace loop

**Síntoma**: La música de título/home suena una sola vez y se detiene. En logcat aparece:
```
AudioTrackImpl: [audioTrackData][fine] 5s... maxAmplitude 4510
AudioTrackImpl: [audioTrackData][zero] 1s...
```

**Estado del parche actual**: Ya existe un parche en `scripts/patch-il2cpp-endpoints.py` que parchea RVA `0x2724398`:
```python
{
    "description": "force CriAtomSource.Play to always configure loop before starting playback",
    "offset": 0x2724398,
    "expected": bytes.fromhex("60010035"),  # cbnz w0, #0x27243c4
    "replacement": bytes.fromhex("1f2003d5"),  # nop
},
```
**¡Este parche NO es suficiente!** La pista sigue terminando después de 1 reproducción.

**Análisis ARM64 del flujo de audio en `0x2724350`–`0x27243f8`**:

La función que contiene `PlayBgm` hace:
```arm64
; x19 = this (sound source instance), x20 = CriAtomSource, w21 = cue ID
0x2724360: mov x0, x20         ; CriAtomSource
0x2724364: mov w1, w21         ; cue ID
0x272436c: bl #0x2819c0c      ; CriAtomSource.SetCue(cueId)
0x2724370: ldrb w8, [x19, #0x34] ; checks some bool flag
0x2724374: cbnz w8, #0x2724388
0x272437c: bl #0x2723b6c      ; some initialization call (only once)
0x2724384: strb w8, [x19, #0x34]
0x2724388: ldr x0, [x19, #0x18] ; CriAtomSource
0x2724394: bl #0x28128a8      ; CriAtomExPlayback.GetStatus() or similar
0x2724398: cbnz w0, #0x27243c4 ; [PATCHED to nop] - skip if already playing
0x272439c: ldr x20, [x19, #0x18]
0x27243a0: ldrb w21, [x19, #0x49] ; isLoop flag byte
0x27243b0: cmp w21, #0
0x27243b4: cset w1, ne          ; w1 = (isLoop != 0) ? 1 : 0
0x27243b8: mov x0, x20
0x27243c0: bl #0x2819d74      ; CriAtomSource.SetLoop(bool)
0x27243c4: ldr x0, [x19, #0x18]
0x27243dc: bl #0x2816d04      ; CriAtomSource.Play()
```

**Problema**: El byte `[x19, #0x49]` (`isLoop` flag) es 0, entonces `SetLoop(false)` se llama antes de `Play()`.

**Investigación del parámetro `isLoop` en metadata**:
En `global-metadata.dat`, la firma de `PlayBgm` incluye los parámetros en este orden:
```
AddBgmSource | isLoop | isReplay | fadeInTime | fadeOutTime | sustainLevel | isCrossFade | PlayBgm
```
Esto indica que `PlayBgm(string cueName, bool isLoop, bool isReplay, float fadeInTime, float fadeOutTime, ...)` es la firma completa. El caller que invoca `PlayBgm` desde `HomeScene` o `TitleScene` podría estar pasando `isLoop=false`.

**Solución recomendada**: Forzar que `[x19, #0x49]` sea 1, O parchear `0x27243b4` para que `cset w1, ne` sea `mov w1, #1` (siempre loop):
```arm64
; En 0x27243b0-0x27243b8:
0x27243b0: cmp w21, #0
0x27243b4: cset w1, ne    ; <- cambiar a: mov w1, #1 (0x21008052)
```

**ALTERNATIVA** (posiblemente más segura): Parchear la lectura de `isLoop` en `0x27243a0`:
```arm64
0x27243a0: ldrb w21, [x19, #0x49]  ; <- cambiar a: mov w21, #1 (0x35008052)
```

**Verificar bytes exactos ANTES de parchear**: Usar capstone para confirmar los bytes en esas posiciones del binario sin parchear (build.T03dt2).

---

### BUG B: Owlbert (Kicker 5) NO aparece en el escenario 3D

**Síntoma**: Al seleccionar a Owlbert en la pestaña de Kickers, la tarjeta UI se actualiza correctamente (nombre, habilidades, thumbnail), pero el modelo 3D del personaje NO se renderiza en el escenario — el stage queda completamente vacío.

**Causa raíz confirmada por ingeniería inversa ARM64**:

El flujo de carga del modelo 3D es:
```
HomeScene -> HighPlayerCharacter.SetModel(kickerId, costumeId, ...)
  -> 0x172c11c -> 0x172c218 (HighPlayerCharacter.SetModel interno)
    -> 0x19f53e8 (función intermedia)
      -> 0x1873834 (generador de nombre de bundle)
```

**La función generadora de nombre de bundle en `0x1873834`**:
```arm64
; w0 = kickerId, w1 = costumeIdArg (¡este es el problema!), w2 = modelTypeFlag
0x1873850: mov w20, w2     ; modelTypeFlag
0x1873854: mov w19, w1     ; costumeIdArg -> w19
...
0x18738c0: tst w20, #1     ; check modelTypeFlag
0x18738c4: mov w8, #0x64   ; 100
0x18738c8: csel w8, w8, wzr, ne  ; w8 = modelType ? 100 : 0
0x18738cc: add w8, w8, w19      ; w8 = 100 + costumeIdArg  <- ¡AQUÍ ESTÁ EL BUG!
```

El bundle final se genera como: `player/pc_{kickerId:03d}/pc_{kickerId:03d}_{w8:03d}.unity3d`

Ejemplo para Owlbert (kicker 5):
- **Esperado**: `player/pc_005/pc_005_101.unity3d` (100 + costumeId=1 = 101)
- **Real cuando recibe id=38**: `player/pc_005/pc_005_138.unity3d` (100 + 38 = 138) -> **¡NO EXISTE!**

**¿Por qué `w19` recibe 38 en lugar de 1?**

La cadena de llamadas que establece `w19`:
```
0x18ae828-0x18ae834: El caller lee dos getters del objeto UserKicker:
  0x18ae800: bl #0x13b8c20  ; get_KickerId() -> ldr w0, [x0, #0x3c] -> w23
  0x18ae830: bl #0x13b8c40  ; get_KickerCostumeId() -> ldr w0, [x0, #0x44] -> w24
```

El campo `[x0, #0x44]` de `UserKicker` es `kickerCostumeId`. El servidor lo llena con el campo `kickerCostumeId` del JSON de startup/home.

**El contrato del campo `kickerCostumeId` en el JSON del servidor**:

En `config/masters_kicker_costume.json`, cada costume tiene:
- `id`: ID global único (autoincremental). Ej: Owlbert default = **38**
- `kickerId`: Kicker al que pertenece. Ej: **5** (Owlbert)
- `costumeId`: ID relativo dentro del kicker (1, 2, 3...). Ej: **1** (default)

Para Tsubame: `id=1, kickerId=1, costumeId=1` -> funciona porque `id == costumeId`
Para Owlbert: `id=38, kickerId=5, costumeId=1` -> **falla** porque el servidor envía `id` (38) como `kickerCostumeId`, pero el cliente espera `costumeId` (1)

**Verificación**: El servidor en `DemoSessionApi.cs` línea 88 construye `_costumesByKicker`:
```csharp
cList.Add(id);  // <- añade el campo "id" (38), NO el campo "costumeId" (1)
```
Y en `BuildStartupJson()` línea 581:
```csharp
kickerCostumeId = selectedCostume,  // <- envía id=38 al cliente
```

**Tabla de impacto**: Solo funciona para Kicker 1 (Tsubame) porque su `id` coincide con su `costumeId`:

| Kicker | Nombre | id global | costumeId relativo | Bundle esperado | Bundle calculado |
|--------|--------|-----------|-------------------|-----------------|-----------------|
| 1 | Tsubame | 1 | 1 | pc_001_101 | pc_001_101 ✅ |
| 2 | Ruriha | 10 | 1 | pc_002_101 | pc_002_110 ❌ |
| 3 | Coco | 19 | 1 | pc_003_101 | pc_003_119 ❌ |
| 5 | Owlbert | 38 | 1 | pc_005_101 | pc_005_138 ❌ |
| 8 | Anna | 64 | 1 | pc_008_101 | pc_008_164 ❌ |

**SOLUCIÓN (en el servidor, NO en ARM64)**:

Cambiar `_costumesByKicker` para que almacene el `costumeId` relativo en lugar del `id` global. El cliente espera recibir `costumeId` (1-7, 21-23, 51-52) NO `id` (1-118).

Cambio requerido en `DemoSessionApi.cs`:
```csharp
// ANTES (linea 88):
cList.Add(id);

// DESPUÉS:
var costumeId = el.GetProperty("costumeId").GetInt32();
cList.Add(costumeId);
```

Y también necesitamos cambiar cómo se construye `userKickerCostumeList` en `BuildStartupJson()`:
```csharp
// ANTES (linea 581-584):
kickerCostumeId = selectedCostume,  // selectedCostume viene de _costumesByKicker -> es "id"
userKickerCostumeList = costumes.Select(c => new { kickerCostumeId = c, ... })

// DESPUÉS: deve ser "costumeId" relativo
```

**IMPORTANTE**: Verificar que `HandleKickerChangeAsync` y `BuildHomeJson` también se actualicen para persistir/enviar `costumeId` en lugar de `id`. El campo `state.KickerCostumeId` debe contener el `costumeId` relativo.

---

## 3. Arquitectura del Servidor C# (`DemoSessionApi.cs`)

### Clase principal y estado
```csharp
public sealed class DemoSessionApi {
    public const string MasterVersion = "demo-master-v18";
    private const string CommonCode = "1a837b9ee2ae11a07a0f529a4cd4b61c";  // AES-256-CBC key

    public sealed class SessionState {
        public string UserId { get; set; } = "1000001";
        public int KickerId { get; set; } = 1;
        public int KickerCostumeId { get; set; } = 1;  // <- DEBE ser costumeId relativo (1-7, 21-23, 51-52)
        public int ActiveDeckNumber { get; set; } = 1;
        public Dictionary<int, List<int>> Decks { get; set; } = ...;
        public Dictionary<int, UserDiscState> Discs { get; set; } = ...;
        public int ItemJetCoins { get; set; } = 208754;
        // ...
    }
}
```

### Endpoints implementados
| Endpoint | Descripción |
|----------|-------------|
| `POST /boot/index` | Autenticación e inicio de sesión |
| `POST /startup/index` | Datos iniciales (kickers, discos, decks, items) |
| `POST /home/index` | Datos de la pantalla principal |
| `POST /download/master` | Descarga de masters encriptados AES-256-CBC |
| `POST /kicker/change` | Cambio de kicker activo y traje |
| `POST /disc/change` | Cambio de mazo activo y disposición de discos |
| `POST /disc/buildup` | Subida de nivel de discos |
| `POST /training/index` | Datos del modo tutorial |
| `POST /follow/online` | Lista de amigos online (vacía) |
| `POST /user/online` | Heartbeat de usuario |
| `GET /v1/list/{appId}/{fromRevision}` | Catálogo de recursos Octo (protobuf) |
| `GET /cdn/{objectName}` | Descarga de asset bundles |
| `GET /health/ready` | Health check del servidor |

### Encriptación D2C
Todos los payloads JSON entre cliente y servidor se encriptan con AES-256-CBC:
- **Key**: `"1a837b9ee2ae11a07a0f529a4cd4b61c"` (convertida a bytes UTF-8, 32 bytes)
- **IV**: Primeros 16 bytes del payload
- Los masters se encriptan con `EncryptMaster(json)` usando la misma key + IV aleatorio

### Persistencia de usuario
Perfiles guardados en: `src/KickFlight.BootstrapApi/data/users/{userId}.json`

---

## 4. Parches Nativos ARM64 Aplicados (`scripts/patch-il2cpp-endpoints.py`)

### En `libil2cpp.so` (arm64-v8a)
| RVA | Descripción | Original | Parche |
|-----|-------------|----------|--------|
| `0x31B5024` | Forzar HTTP | `csel` -> `mov x8, x10` | Siempre HTTP |
| `0x17331C0` | Bypass Firebase chat | `str x21, [sp, #-0x30]!` -> `ret` | Evita NRE en Firebase |
| `0x1890c50` | Bypass null format en BattleRuleDefaultView | `tbz` -> `b #0x1890d04` | Salta el String.Format nulo |
| `0x159DF5C` | Bypass HomeSummonModelController.UnloadModel | `str x21, [sp, #-0x30]!` -> `ret` | Evita crash al cerrar ventana |
| `0x159E254` | Bypass LoadModelAsync corutina | `str + stp` -> `mov w0, wzr; ret` | Termina corutina limpio |
| `0x151DAE8` | JapaneseSwordAction.IsCloded null check | verificación extendida | Retorna falso si _flagBone es null |
| `0x151DB2C` | JapaneseSwordAction.IsInHandScabbard null check | verificación extendida | Retorna falso si _flagBone es null |
| `0x151D820` | JapaneseSwordAction.InitializeSword null check | `mov xzr; bl` -> `b #skip; nop` | Salta inicialización vacía |
| `0x2724398` | CriAtomSource.Play loop config | `cbnz w0, skip` -> `nop` | Siempre configura loop (**insuficiente**) |
| `0x159D1BC` | HomeSummonModelController.SetModel bypass | `str d10, [sp, #-0x80]!` -> `ret` | Evita crash de modelo de invocación |
| `0x1818FD8` | Weapon.Initialize null model bypass | `cbnz x22, play; bl raise` -> `cbz x22, #skip; nop` | Salta attachment si modelo es null |

### En `libunity.so` (arm64-v8a)
| RVA | Descripción |
|-----|-------------|
| `0xA045C4` | Bypass radix table overflow Insert |
| `0xA045DC` | Bypass radix table overflow error handler Insert |
| `0xA0481C` | Bypass radix table overflow Remove |
| `0xA04834` | Bypass radix table overflow error handler Remove |
| `0xDA630+` | 6 patches: bind operator new/delete to MemoryManager |
| `0x50AE7C` | Route MemoryManager::Reallocate null-safe |
| `0x50AED4` | Bypass invalid free in MemoryManager::Deallocate |
| `0x50AEF0` | Null-safe allocator stub |

---

## 5. Sistema de Masters (JSONs de configuración)

| Archivo | Entradas | Descripción |
|---------|----------|-------------|
| `config/masters_kicker.json` | 14 | Los 14 kickers con nombres y VA |
| `config/masters_kicker_costume.json` | 118 | Trajes con `id` global, `kickerId`, `costumeId` relativo |
| `config/masters_kicker_detail.json` | 14 | Texto de habilidades en español |
| `config/masters_kicker_parameter.json` | 14 | Stats (HP, ATK, SPD, tipo de arma) |
| `config/masters_kicker_ability.json` | 14 | Habilidades pasivas |
| `config/masters_kicker_ability_condition.json` | 14 | Condiciones de activación |
| `config/masters_disc.json` | 126 | Discos con stats y elementos |
| `config/masters_skill.json` | 126 | Habilidades de disco en español |
| `config/masters_disc_grow.json` | 50 | Curvas de crecimiento |
| `config/masters_disc_buildup.json` | | Costes de subida de nivel |
| `config/masters_gear.json` | 500 | Engranajes |
| `config/masters_gear_skill.json` | 25 | Habilidades de engranajes |
| `config/masters_gear_same_color_bonus.json` | | Bonificación por color |
| `config/masters_translation.json` | 456+ | Localización español |

---

## 6. Catálogo Octo de Assets (Revisión 16)

- **Total de recursos catalogados**: 2,579
- **Generador**: `scripts/build_complete_catalog.py` (genera protobuf)
- **Ficheros fixture**: `config/fixtures/resource-list-12345-from-{N}.json` (N = 0 a 16)
- **Pre-seeding**: `scripts/seed-device-cache.py` genera `octo_cache.tar` (728.9 MB)

### Bundles del modelo 3D de un Kicker
Para Owlbert (kicker 5, costumeId 1), los bundles en el manifiesto son:
```
player/pc_005/pc_005_001.unity3d   -> Modelo base (costumeId 1..7 usa _00X)
player/pc_005/pc_005_101.unity3d   -> Modelo "high" (100 + costumeId)
player/pc_005/pc_005_102.unity3d   -> Modelo "high" (100 + costumeId=2)
player/pc_005/pc_005_103.unity3d   -> Modelo "high" (100 + costumeId=3)
player/pc_005/animator/pc_005_101_result.unity3d -> AnimatorController
```

La fórmula del cliente es: `100 + costumeId` (el costumeId relativo, NO el id global).

---

## 7. Corrección de Armas y Animación de Owlbert (Kicker 5)

Ya resuelto en versiones anteriores:
- **propId**: Debe ser `101` (no 1) para activar `DroneAction` en `Weapon.CreateAction`
- **attachType**: Debe ser `2` (raíz libre) para que el dron flote independiente
- Configuración actual en servidor:
  ```json
  {"id":5,"kickerId":5,"modelId":1,"propId":101,"boneName":"","rootName":"","attachType":2}
  ```

---

## 8. Logros Previos Completados

1. ✅ Pantalla de título con audio CriWare
2. ✅ Transición title -> download -> home sin crashes
3. ✅ Home UI completa: header, battle card, countdown, botón "Combate" amarillo activo
4. ✅ 14 kickers con thumbnails, role icons, nombres y habilidades en español
5. ✅ 3D rendering de Tsubame en Home arena a 60 FPS
6. ✅ Cambio de kicker persistente entre sesiones
7. ✅ 126 discos con artwork, niveles, buildup funcional
8. ✅ 5 mazos con cambio de deck funcional
9. ✅ Combate de clasificación con rango S+6 visual
10. ✅ Localización completa en español
11. ✅ Pre-seeding de caché sin descarga Wi-Fi
12. ✅ Firebase bypass, JapaneseSword null fixes, HomeSummon fixes
13. ✅ Owlbert drone propId=101 + attachType=2 configurado

---

## 9. Plan de Ejecución Inmediato

### Paso 1: Fix Owlbert 3D Model (Server-Side)
**Archivo**: `src/KickFlight.BootstrapApi/DemoSessionApi.cs`

1. En `InitializeMasters()` (~línea 82-88), cambiar:
   ```csharp
   // ANTES:
   cList.Add(id);
   // DESPUÉS:
   var costumeId = el.GetProperty("costumeId").GetInt32();
   cList.Add(costumeId);
   ```

2. En `BuildStartupJson()` (~línea 576-588), verificar que `kickerCostumeId` y `userKickerCostumeList[].kickerCostumeId` usen `costumeId` relativo.

3. En `HandleKickerChangeAsync()` (~línea 452-458), verificar que `state.KickerCostumeId` reciba el `costumeId` relativo del cliente.

4. En `BuildHomeJson()` (~línea 676), `kickerCostumeId = state.KickerCostumeId` debe ser el relativo.

5. **Migrar todos los `data/users/*.json` existentes**: Los que tienen `KickerCostumeId: 38` (Owlbert) deben cambiarse a `1`, los que tienen `64` (Anna) a `1`, etc. O simplemente borrarlos para que se regeneren.

### Paso 2: Fix BGM Looping (Native ARM64 Patch)
**Archivo**: `scripts/patch-il2cpp-endpoints.py`

Verificar bytes exactos en RVA `0x27243a0` y `0x27243b4`, luego añadir un parche que fuerce `isLoop = true`:

**Opción A** (forzar en la lectura): Parchear `0x27243a0`:
```python
{
    "description": "force BGM isLoop flag to always be true for looping playback",
    "offset": 0x27243a0,
    "expected": bytes.fromhex("???"),  # ldrb w21, [x19, #0x49]
    "replacement": bytes.fromhex("b5008052"),  # mov w21, #1 -> Verificar encoding
},
```

**Opción B** (forzar en el cset): Parchear `0x27243b4`:
```python
{
    "description": "force SetLoop(true) unconditionally for BGM playback",
    "offset": 0x27243b4,
    "expected": bytes.fromhex("???"),  # cset w1, ne
    "replacement": bytes.fromhex("21008052"),  # mov w1, #1
},
```

**Verificar bytes exactos ANTES de parchear**: Usar capstone para confirmar los bytes en esas posiciones del binario sin parchear (build.T03dt2).

### Paso 3: Rebuild, Instalar y Verificar
```bash
# 1. Correr tests
dotnet test

# 2. Rebuild APK con todos los patches
SERVER_BASE_URL="http://192.168.1.141:18080" ./scripts/build-direct-apk.sh

# 3. Instalar en POCO F6 Pro
adb -s 3d3dc71d install -r .local/artifacts/KickFlight-2.11.0-direct-192.168.1.141-18080.apk

# 4. Lanzar y verificar
adb -s 3d3dc71d shell am force-stop jp.grenge.kickflight
adb -s 3d3dc71d shell am start -n jp.grenge.kickflight/com.google.firebase.MessagingUnityPlayerActivity

# 5. Verificar en logcat
adb -s 3d3dc71d logcat -v time | grep -E "audioTrack|NullRef|Exception|HomeScene|SetModel"

# 6. Captura
adb -s 3d3dc71d exec-out screencap -p > /tmp/poco_raw.png && sips --resampleWidth 720 /tmp/poco_raw.png --out /tmp/poco_720.png
```

### Criterios de aceptación
1. **BGM**: La música suena continuamente sin interrupción. No aparecen `[audioTrackData][zero]` en logcat.
2. **Owlbert**: Al seleccionar a Owlbert en la pestaña Kickers, su modelo 3D (búho con googles y dron) aparece en el escenario con animaciones completas.
3. **Todos los kickers**: Los 14 kickers cargan su modelo 3D correctamente, no solo Tsubame.
4. **Tests**: `dotnet test` sigue pasando 22/22.

---

## 10. Herramientas de Diagnóstico ARM64

### Disassemblar una función
```python
import capstone
md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
lib_path = ".local/apk-direct-work/build.T03dt2/decoded/lib/arm64-v8a/libil2cpp.so"
with open(lib_path, "rb") as f:
    data = f.read()
offset = 0xRVA
code = data[offset:offset+0x100]
for i in md.disasm(code, offset):
    print(f"0x{i.address:x}: {i.mnemonic} {i.op_str}")
```

### Encontrar callers de una función
```python
target = 0xRVA
for pc in range(0, len(data), 4):
    word = int.from_bytes(data[pc:pc+4], "little")
    if (word & 0xfc000000) == 0x94000000:
        imm26 = word & 0x03ffffff
        if imm26 & (1 << 25): imm26 -= (1 << 26)
        dest = pc + (imm26 << 2)
        if dest == target:
            print(f"Found caller at 0x{pc:x}")
```

### Getters de UserKicker
```
0x13b8c20: ldr w0, [x0, #0x3c]  -> get_KickerId()
0x13b8c40: ldr w0, [x0, #0x44]  -> get_KickerCostumeId()  <- Este es el que recibe id=38
0x13b8c50: ldr x0, [x0, #0x48]  -> algún puntero a objeto
```

### Callers importantes del flujo de modelo 3D
```
HomeScene -> 0x18ae830 (bl get_KickerCostumeId) -> 0x18ae860 (bl 0x18ae984)
  -> 0x18aea8c (bl 0x140051c) -> 0x140063c (bl 0x172c11c)
    -> 0x172c178 (bl 0x172c218 HighPlayerCharacter.SetModel)
      -> 0x172c2c0 (bl 0x19f53e8 función intermedia)
        -> 0x19f546c (bl 0x1873834 generador de nombre de bundle)
          -> 0x18738cc: add w8, w8, w19  <- w19=costumeId (DEBE ser 1, no 38)
```

---

## 11. Roadmap Futuro (post-bugs)

1. **Sistema de Gears**: Implementar `/gear/index`, `/gear/change`, `/gear/set`, `/gear/sell`
2. **Modo Tutorial**: Implementar `/tutorial/start`, `/tutorial/battle/progress`, `/tutorial/battle/end`
3. **Combate contra Bots**: Activar `PhotonNetwork.offlineMode = true` + AI masters
4. **Matchmaking local**: `POST /matching/request` con sala Photon local
5. **Base de datos relacional**: Migrar de JSON files a SQLite/PostgreSQL
