# CONTINUATION PROMPT: BATALLA CRASH FIX & MULTIJUGADOR (2 EMULADORES)

> **Propósito**: Resolver los 3 problemas pendientes del sistema de batalla offline y probar multijugador real con dos instancias simultáneas.
> **Prioridad**: Alta. Estos son los últimos bloqueantes antes de tener combate funcional.

---

## 0. RESUMEN DE SITUACIÓN ACTUAL

El servidor privado de Kick-Flight 2.11.0 (`KickFlight.BootstrapApi`) está operativo y el flujo completo funciona hasta el inicio de la batalla:

```
TitleScene → DownloadScene → HomeScene (3D completo, 14 kickers, 126 discos)
  → Combate → MatchingScene → GetAssignments (gRPC) → GameScene
    → Carga de arena FLD00101 (Cristalmanía / Scramble50)
    → Spawn de 6 jugadores (3v3: 1 humano + 5 bots)
    → Presentación equipo aliado... ✅
    → Presentación equipo enemigo... ❌ CRASH (signal 11 / SIGSEGV)
```

**Además**: Después de un primer intento exitoso (que llega hasta la presentación de aliados), los intentos subsecuentes crashean más temprano — mostrando apenas 2 frames de la batalla (~1 segundo) antes de morir con `SIGSEGV`.

---

## 1. BUG CRÍTICO A: CRASH AL PRESENTAR EQUIPO ENEMIGO

### Síntoma
La secuencia de inicio de batalla (`GameStartAnimation`) presenta correctamente al equipo aliado (Team 0 / Blue), pero al intentar presentar al equipo enemigo (Team 1 / Red), el proceso muere con `signal 11 (SIGSEGV)` en el hilo `UnityPreload` o en el hilo principal de rendering.

### Evidencia de logcat
```
GameStartView.PlayStartAnim (RVA 0x1764134)        ← se alcanza
GameStartAnimation.PlayReadyAnimation (RVA 0x1762CE0) ← se alcanza
[equipo aliado se presenta correctamente]
[CRASH: signal 11 (SIGSEGV), code 1 (SEGV_ACCERR)]
```

### Hipótesis de causa raíz (investigar en orden)

1. **Asset de cinemática de enemigos faltante**: La presentación de cada equipo posiblemente carga assets de cámara/cinemática específicos por equipo. Si el asset del Team 1 no está en el catálogo Octo o en la caché del dispositivo, la carga devuelve null y la siguiente operación sobre ese puntero causa SIGSEGV.

2. **NullReferenceException en `PlayerCharacter.SetModel` para los enemigos**: Los parches existentes en `patch-il2cpp-endpoints.py` resuelven null checks para ciertos kickers/armas, pero los bots enemigos podrían usar combinaciones de kickerId/costumeId/weaponId no cubiertas. Revisa si hay NREs justo antes del SIGSEGV en logcat.

3. **`Lightmaps mode` incompatible**: Unity advierte `"Loaded level has a different lightmaps mode than the current one"` durante la carga del campo de batalla. Esto podría corromper la memoria del renderer al intentar aplicar lightmaps durante la cinemática de enemigos.

4. **Spawn point index out of bounds para Team 1**: Ya existen parches de clamp para spawn points en `0x17407F4`, `0x1740BC0`, `0x1740BF8`, `0x1740D5C`, pero podría haber un path no cubierto cuando la cinemática de enemigos reubica las cámaras.

5. **`PlayerBoneController` o `CharacterAnimatorBase` sin inicializar para enemigos**: Los parches existentes retornan safe defaults, pero si la cinemática de presentación invoca métodos adicionales del animator (e.g., `SetTrigger`, `CrossFade`, `Play`) que no están parcheados, pueden crashear.

### Plan de investigación

```bash
# 1. Capturar logcat completo de un intento de batalla
adb -s $DEVICE logcat -c
# [lanzar juego, llegar a batalla]
adb -s $DEVICE logcat -d > /tmp/battle-crash-full.log

# 2. Filtrar las líneas relevantes
grep -E "GameStart|PlayReady|PlayGo|ReceiveAdd|SetModel|PlayStartAnim|NullRef|SIGSEGV|signal 11|SEGV|AddPlayer|Team|Enemy|ally|libil2cpp|libunity" /tmp/battle-crash-full.log > /tmp/battle-crash-filtered.log

# 3. Buscar el ÚLTIMO log antes del SIGSEGV
grep -B 20 "signal 11\|SIGSEGV" /tmp/battle-crash-full.log | tail -40

# 4. Buscar NREs que precedan al crash
grep -B 5 "NullReferenceException" /tmp/battle-crash-full.log

# 5. Verificar si hay asset requests fallidos
grep -E "404|NotFound|missing|null.*asset|Load.*fail" /tmp/battle-crash-full.log
```

### Parches candidatos a añadir en `scripts/patch-il2cpp-endpoints.py`

Si la causa es una NRE durante la presentación de enemigos, los RVAs más probables a investigar con capstone son:

| Función | RVA aprox. | Qué hace |
|---------|-----------|----------|
| `GameStartAnimation.PlayTeamAnimation` | cerca de `0x1762CE0` | Presenta un equipo; podría tener lógica diferente para team 0 vs team 1 |
| `GameStartView.SetTeamView` | buscar callers de `PlayStartAnim` | Configura la UI/cámara por equipo |
| `ObjectManager.ReceiveAddPlayer` | buscar en logcat | Spawn del modelo 3D de cada jugador |
| `InGameCameraManager` | buscar en dump.cs | Puede intentar posicionar la cámara en un nodo null del equipo enemigo |

Usar capstone para disassemblar:
```python
import capstone
md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
lib = ".local/apk-direct-work/build.T03dt2/decoded/lib/arm64-v8a/libil2cpp.so"
with open(lib, "rb") as f:
    data = f.read()
offset = 0x1762CE0  # GameStartAnimation.PlayReadyAnimation
for i in md.disasm(data[offset:offset+0x200], offset):
    print(f"0x{i.address:x}: {i.mnemonic} {i.op_str}")
```

---

## 2. BUG CRÍTICO B: CRASH EN INTENTOS SUBSECUENTES (2 FRAMES → SIGSEGV)

### Síntoma
Después de un primer intento que llega más lejos (hasta presentación de aliados), los siguientes intentos de batalla crashean mucho antes: se ven 2 frames del campo de batalla renderizándose parcialmente (~1 segundo) y luego SIGSEGV.

### Hipótesis de causa raíz

1. **Estado sucio de `SceneManager` / `LoadManager`**: El primer intento de batalla carga la `GameScene` y assets de combate. Cuando el crash ocurre, esos assets quedan en un estado parcialmente cargado. En el siguiente intento, `LoadManager.LoadCacheAsync` o `ModelManager.InstantiateModel` intentan reusar punteros inválidos de la sesión anterior.

2. **`_isUnloading` flag stuck en true**: Ya hay un parche en `0x16E2AD8` que bypasea `_isUnloading` en `LoadManager.LoadCacheAsync`, pero si la escena anterior nunca completó su cleanup, el `LoadManager` podría estar en un estado inconsistente.

3. **`_isChangeScene` flag residual**: Ya hay un parche en `0x1CAC918` que bypasea `_isChangeScene` en `SceneManager.ChangeScene`, pero el segundo intento podría estar encontrando el flag en un valor inesperado.

4. **Memory corruption acumulativa**: Los parches en `libunity.so` para `MemoryManager` (`0x50AE7C`-`0x50AEF0`) protegen contra crashes de asignación, pero podrían no cubrir todas las rutas de corrupción cuando assets de la sesión anterior persisten en memoria.

### Plan de investigación

```bash
# 1. Comparar logcat del primer intento vs segundo intento
# Buscar diferencias en el orden de carga de assets y escenas

# 2. Verificar si pm clear entre intentos resuelve el crash repetido
adb -s $DEVICE shell pm clear jp.grenge.kickflight
adb -s $DEVICE shell pm grant jp.grenge.kickflight android.permission.POST_NOTIFICATIONS
# [relanzar y probar]

# 3. Si pm clear lo resuelve, el problema es estado residual en SharedPrefs/cache
# Si NO lo resuelve, es estado in-memory (memory corruption)

# 4. Buscar los assets específicos que fallan en el segundo intento
grep -E "Load.*fail|InstantiateModel.*null|asset.*null|bundle.*null" /tmp/battle-crash-attempt2.log
```

### Posible fix rápido
Si el segundo intento crashea por estado residual, forzar un `force-stop` + relaunch completo entre batallas puede ser un workaround temporal mientras se investiga el cleanup correcto.

---

## 3. BUG C: DESCARGA COMPLETA DE ELEMENTOS

### Síntoma
El modal de descarga de elementos que aparece al inicio no descarga TODOS los assets necesarios para la batalla. Algunos assets se intentan cargar en runtime y fallan.

### Estado actual
- **Catálogo Octo**: Revisión 16 con 2,579 recursos catalogados
- **Pre-seeding**: `scripts/seed-device-cache.py` genera `octo_cache.tar` (728.9 MB) con 5,160 assets
- **Generador de catálogo**: `scripts/build_complete_catalog.py` genera protobuf

### Investigación requerida

1. **Listar los assets que el juego intenta cargar durante GameScene y que fallan**:
```bash
# Capturar requests de assets durante la batalla
grep -E "/cdn/|LoadCacheAsync|GenerateAssetBundleUrl|Load.*bundle" /tmp/battle-crash-full.log
```

2. **Comparar los assets del catálogo con los que realmente se necesitan en GameScene**:
   - `field/fld00101/` — Campo de batalla (ya catalogado)
   - `shader/preloadgameshadervariants.unity3d` — Shaders de combate (ya catalogado)
   - `effect/game/` — Efectos de juego (¿catalogados?)
   - `effect/wp/` — Efectos de armas (parcialmente catalogados)
   - `gimmick/` — Objetos del campo (¿catalogados?)
   - `item/` — Cristales y power-ups (¿catalogados?)
   - `player/pc_XXX/` — Modelos de los 14 kickers (¿todos los costumes catalogados?)
   - `weapon/wp_XXX/` — Armas de los 14 kickers (¿todas catalogadas?)
   - `animator/` — Controllers de animación (¿catalogados?)
   - `sound/` — Audio de batalla (¿catalogado?)

3. **Verificar que `title-minimum.json` incluya las referencias a todos los bundles de batalla**:
```bash
# Contar recursos en el catálogo
python3 -c "import json; d=json.load(open('config/resources/catalog.json')); print(len(d.get('resources',[])))"

# Verificar presencia de battle-critical assets
python3 -c "
import json
cat = json.load(open('config/resources/catalog.json'))
names = [r['logicalName'] for r in cat.get('resources',[])]
critical = ['field/fld00101/', 'shader/preloadgameshadervariants', 'effect/game/', 'gimmick/', 'item/it_001']
for c in critical:
    found = [n for n in names if c in n]
    print(f'{c}: {len(found)} entries')
"
```

4. **Extender `build_complete_catalog.py`** si hay categorías faltantes en el catálogo.

---

## 4. TAREA NUEVA: MULTIJUGADOR CON DOS EMULADORES

### Objetivo
Probar el flujo de matchmaking con dos clientes simultáneos conectándose al mismo servidor, verificando que ambos entren a la misma sala de batalla.

### Prerrequisitos

1. **Dos emuladores Android corriendo simultáneamente**:
   - Emulador A: `emulator-5554` (ya existente: `kickflight_api35_arm64`)
   - Emulador B: Crear un segundo AVD o clonar el existente

```bash
# Crear segundo AVD
$ANDROID_HOME/emulator/emulator -avd kickflight_api35_arm64_2 -port 5556 &
# O clonar:
avdmanager create avd -n kickflight_client2 -k "system-images;android-35;google_apis;arm64-v8a" -d "pixel_6"
```

2. **APK instalada en ambos emuladores**:
```bash
APK=".local/artifacts/KickFlight-2.11.0-direct-10.0.2.2-18080.apk"
adb -s emulator-5554 install -r "$APK"
adb -s emulator-5556 install -r "$APK"
```

3. **Caché de assets seedeada en ambos**:
```bash
# Si se usa seed-device-cache.py:
python3 scripts/seed-device-cache.py --device emulator-5554
python3 scripts/seed-device-cache.py --device emulator-5556
```

4. **Servidor accesible desde ambos emuladores**: Ambos usan `10.0.2.2:18080` (gateway del host desde el emulador).

### Flujo de test manual

```
EMULADOR A                          EMULADOR B
─────────                          ─────────
1. Lanzar app                      1. Lanzar app
2. TAP START                       2. TAP START
3. Esperar HomeScene               3. Esperar HomeScene
4. Tap "Combate" → MatchingScene   (esperar)
5. Tap "Iniciar combate"           (esperar 5s)
6. (esperando en sala)             4. Tap "Combate" → MatchingScene
                                   5. Tap "Iniciar combate"
7. Ambos matcheados en misma room  7. Ambos matcheados en misma room
8. GameScene carga en ambos        8. GameScene carga en ambos
```

### Flujo de test automatizado

Modificar `scripts/test-battle-loop.sh` o crear `scripts/test-multiplayer.sh` que:

1. Acepte `--device1 emulator-5554 --device2 emulator-5556`
2. Lance ambos apps en paralelo
3. Ejecute TAP START en ambos
4. Espere HomeScene en ambos
5. Tape "Combate" en Emulador A primero
6. Tape "Iniciar combate" en Emulador A
7. Espere 3s, luego tape "Combate" + "Iniciar combate" en Emulador B
8. Verifique que el servidor reporta a ambos en la misma room (`BattleMatchmakingService.ResolveAssignment`)
9. Verifique que ambos alcanzan `GameScene`

### Servidor: Verificar matching multi-cliente

El código en `BattleMatchmakingService.cs` líneas 121-159 ya soporta multi-client matching:

```csharp
// Multi-client matching check: find existing room with available human player slot
foreach (var room in _roomsByBattleId.Values)
{
    if (room.BattleRuleId == playerSession.BattleRuleId && room.HumanPlayers.Count < 6)
    {
        if (room.HumanPlayers.Count < 2) // Join as second player!
        {
            matchedRoom = room;
            room.HumanPlayers.Add(playerSession);
            break;
        }
    }
}
```

**PERO**: Cada cliente recibe su propio UUID en `/auth/prepare` → `/auth/index`, generando un `userId` diferente. Verificar que:
- Emulador A obtiene `userId = 1000001`
- Emulador B obtiene `userId = 1000002` (o similar)
- Ambos `RegisterEntry()` con el mismo `battleRuleId`
- `ResolveAssignment()` los empareja en la misma `ActiveBattleRoom`

### Verificación del roster

Cuando hay 2 humanos, el roster debe ser:
- **Team 0 (Blue)**: Humano A + 2 Bots = 3
- **Team 1 (Red)**: Humano B + 2 Bots = 3
- **Total**: 6 jugadores (3v3)

Verificar en los logs del servidor:
```bash
grep -E "Registered battle entry|Created new battle room|Matched second human" /tmp/server.log
```

---

## 5. ARQUITECTURA DE REFERENCIA RÁPIDA

### Archivos clave del servidor
| Archivo | Descripción |
|---------|-------------|
| `src/KickFlight.BootstrapApi/DemoSessionApi.cs` | API principal (1117 líneas): auth, startup, home, battle, kicker, disc, masters |
| `src/KickFlight.BootstrapApi/BattleMatchmakingService.cs` | Matchmaking y roster (321 líneas): RegisterEntry, ResolveAssignment, BuildRoster |
| `src/KickFlight.BootstrapApi/Program.cs` | Routing y middleware |

### Archivos clave del cliente (parcheador)
| Archivo | Descripción |
|---------|-------------|
| `scripts/patch-il2cpp-endpoints.py` | 498 líneas de parches ARM64 para libil2cpp.so + 84 para libunity.so |
| `scripts/build-direct-apk.sh` | Pipeline: decodificar APK → parchear → recompilar → firmar |
| `scripts/test-battle-loop.sh` | Test automatizado de 7 pasos (título → home → combate → batalla) |
| `scripts/seed-device-cache.py` | Pre-siembra de 5,160 assets en caché del dispositivo |

### Catálogo y assets
| Archivo | Descripción |
|---------|-------------|
| `config/resources/catalog.json` | Catálogo completo de recursos Octo (~1.4 MB JSON) |
| `config/resources/title-minimum.json` | Catálogo mínimo de título (~1.3 MB JSON) |
| `octo_cache.tar` | Archivo tar con 5,160 assets pre-seedeados (728.9 MB) |
| `scripts/build_complete_catalog.py` | Generador de catálogo Octo protobuf |

### Masters encriptados (DemoSessionApi.cs)
MasterVersion: `demo-master-v27`. Todos encriptados con AES-256-CBC, key: `1a837b9ee2ae11a07a0f529a4cd4b61c`.

| Master | Entradas | Fuente |
|--------|----------|--------|
| Kicker | 14 | `config/masters_kicker.json` |
| KickerCostume | 118 | `config/masters_kicker_costume.json` |
| KickerDetail | 14 | `config/masters_kicker_detail.json` |
| KickerParameter | 14 | `config/masters_kicker_parameter.json` |
| KickerAbility | 14 | `config/masters_kicker_ability.json` |
| KickerAbilityCondition | 14 | `config/masters_kicker_ability_condition.json` |
| Translation | 456+ | `config/masters_translation.json` |
| Field | 2 | inline (FLD99999, FLD00101) |
| BattleRule | 6 | inline |
| BattleRuleField | 6 | inline |
| BattleRank | 13 | inline |
| Weapon | dinámico | generado desde `catalog.json` |
| + 15 masters más | varios | inline en DemoSessionApi.cs |

### Parches nativos (73 parches IL2CPP + 12 libunity)
Categorías de parches en `patch-il2cpp-endpoints.py`:
- **Conectividad**: HTTP forzado, endpoint literals reescritos
- **Firebase/Chat bypass**: `HomeChatNotificationView`, SSL bypass
- **Null safety (Home)**: `HomeSummonModelController`, `BattleRuleDefaultView`, `TitleView`
- **Null safety (Batalla)**: `PlayerCharacter.SetModel`, `WeaponModelController`, `PlayerBoneController`, `CharacterAnimatorBase`, armas de 11+ kickers
- **Matchmaking bridge**: `NormalMatchingController`, `MatchingManager.IsRoomLocalPlayerMaster`, `CallbackBattleStartSuccess`, `ApplyBattleProperties`
- **GameScene lifecycle**: `SceneManager.ChangeScene`, `GameManager.BeginAsync` (7 lambdas), `GameScene.PreBeginAsync/PostEndAsync`, `ReplayManager` bypass
- **Asset loading safety**: `ModelManager.InstantiateModel`, `LoadManager.LoadCacheAsync`, `LoadDeckSummonModel`, `SkillRangeValidator`
- **Spawn points**: 4 parches de clamp para índices de spawn
- **Memory management (libunity)**: 12 parches para radix table overflow, operator new/delete binding, null-safe allocator

---

## 6. ENCRIPTACIÓN D2C (REFERENCIA RÁPIDA)

```
Key:  "1a837b9ee2ae11a07a0f529a4cd4b61c" (32 bytes UTF-8 = AES-256)
IV:   Primeros 16 bytes del payload
Data: bytes[16..] desencriptados con AES-256-CBC, PKCS7 padding
```

Tanto los requests como responses del cliente se encriptan. Los masters se encriptan con `EncryptMaster()` (IV aleatorio + misma key).

---

## 7. REGLAS OPERATIVAS

### Screenshots
```bash
adb -s $DEVICE exec-out screencap -p > /tmp/raw.png && sips --resampleWidth 720 /tmp/raw.png --out /tmp/720.png
```
**Nunca** usar la resolución nativa del dispositivo/emulador.

### Contexto
- Techo duro de 250,000 tokens; compactar antes de 240,000.
- Estado persistente en `.local/adb-loop-notes.md`.
- Capturas y logs crudos en `.local/battle-test/latest/`.

### Build y test
```bash
# Reconstruir APK con todos los parches
SERVER_BASE_URL="http://10.0.2.2:18080" ./scripts/build-direct-apk.sh

# Test automatizado completo
./scripts/test-battle-loop.sh --build

# Test rápido sin reinstalar
./scripts/test-battle-loop.sh --no-install

# Servidor
./scripts/run-direct.sh  # o ./scripts/run-local.sh para LAN
```

### Tests unitarios
```bash
cd /Users/marcochavez/Documents/variedad/Kick-Flight-Private-Server
dotnet test
```

---

## 8. CRITERIOS DE ACEPTACIÓN FINALES

### Para Bug A (Crash al presentar enemigos)
- [ ] La secuencia `PlayReadyAnimation` → `PlayGoAnimation` ("3, 2, 1, FLY!") se completa sin SIGSEGV
- [ ] Los 6 jugadores (3 aliados + 3 enemigos) se presentan en la cinemática de inicio
- [ ] El combate entra en modo activo (`PlayerStateNormal.UpdateFly`)
- [ ] Logcat NO muestra `signal 11`, `SIGSEGV`, ni `NullReferenceException` durante la transición

### Para Bug B (Crash en intentos subsecuentes)
- [ ] Al menos 3 intentos de batalla consecutivos funcionan sin crash
- [ ] No se requiere `pm clear` ni `force-stop` entre intentos
- [ ] Si se necesita workaround temporal (force-stop entre batallas), documentarlo

### Para Bug C (Descarga completa de elementos)
- [ ] El modal de descarga baja TODOS los assets necesarios para la batalla
- [ ] No hay requests de assets que retornen 404 durante GameScene
- [ ] Los assets de batalla están en el catálogo Octo y en `octo_cache.tar`

### Para Multijugador (2 emuladores)
- [ ] Dos emuladores Android corren simultáneamente
- [ ] Ambos se conectan al mismo servidor en `10.0.2.2:18080`
- [ ] Ambos obtienen userIds diferentes
- [ ] `BattleMatchmakingService` los empareja en la misma `ActiveBattleRoom`
- [ ] Ambos alcanzan `GameScene` con el roster correcto (2 humanos + 4 bots en 3v3)
- [ ] Si la batalla crashea en alguno, documentar en cuál y con qué log

---

## 9. ORDEN DE EJECUCIÓN RECOMENDADO

1. **Primero**: Diagnosticar Bug A (crash al presentar enemigos) — es el bloqueante principal
2. **Segundo**: Diagnosticar Bug B (crash subsecuente) — podría resolverse al arreglar A
3. **Tercero**: Verificar Bug C (descarga completa) — puede causar A y B si hay assets faltantes
4. **Cuarto**: Configurar y probar multijugador con 2 emuladores — depende de que la batalla funcione

> **NOTA**: Los Bugs A, B y C están probablemente interrelacionados. Un asset faltante (Bug C) podría causar el crash al presentar enemigos (Bug A), y la corrupción de memoria resultante causaría el crash en intentos subsecuentes (Bug B). Empezar verificando qué assets se cargan durante `GameStartAnimation` y cuáles faltan.
