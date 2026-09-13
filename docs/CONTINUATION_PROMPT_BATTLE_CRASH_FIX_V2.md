# CONTINUATION PROMPT V2: SALA DE MATCHMAKING, HUD REAL, CONTROLES Y COMBATE MULTIJUGADOR

> **Propósito**: Guía exhaustiva y ejecutable para completar la restauración del sistema de combate de Kick-Flight 2.11.0 en servidor privado (`KickFlight.BootstrapApi`), resolviendo la pantalla de preparación de sala (4v4), el HUD interactivo de combate (vs modo repetición), la activación de controles 3D, los crashes de presentación de enemigos y las pruebas multijugador en 2 emuladores.
> **Versión**: 2.0 (Actualizada con ingeniería inversa de `libil2cpp.so`, gRPC streaming y UI de combate).

---

## 0. RESUMEN EJECUTIVO Y ESTADO ACTUAL

El flujo principal del servidor privado (`KickFlight.BootstrapApi`) opera en HTTP/1.1 y gRPC en los puertos `18080` (HTTP) y `18081` (gRPC).

```
TitleScene → DownloadScene → HomeScene (3D, 14 kickers, 126 discos)
  → Tap 'Combate' → MatchingScene
    → [NUEVO] Sala de Preparación (MatchingWaitMemberDisplayView / 8 slots 4v4 + Mazo propio)
    → gRPC GetAssignments (streaming multi-etapa)
    → Tap 'Iniciar combate' (o auto-start al llenar 8 jugadores)
    → GameScene (FLD00101 Cristalmanía)
      → Spawn de 8 jugadores (Team 0 Azul vs Team 1 Rojo)
      → Presentación Equipo Aliado... ✅
      → Presentación Equipo Enemigo... ⚠️ (Fix validado con null-guard en GameStartAnimation)
      → "3, 2, 1, FLY!" → Combate Activo
      → [NUEVO] HUD Real de Combate (4 discos verdes, CD timer, SP kicker, ATQ/HP, radar)
      → [NUEVO] Controles de vuelo y combate habilitados
```

---

## 1. LOS 3 PROBLEMAS CRÍTICOS IDENTIFICADOS Y SU SOLUCIÓN TÉCNICA

### 1.1. Pantalla de Preparación de Sala Omitida (Matchmaking Room)
- **Síntoma original**: El cliente saltaba de `HomeScene` directamente a la batalla sin mostrar la pantalla de espera de participantes.
- **Causa raíz descubierta en `libil2cpp.so`**:
  - En `NormalMatchingController.<GrpcGetAssignments>b__1` (RVA `0x13EE43C`), existe una tabla de saltos (`0x3227120`) basada en `NormalMatchingController.GetAssignmentsResult`:
    - `Result 0 (Update)` -> RVA `0x13EE4D0`: Llama a `0x13EC8E4` (`MatchingManager.UpdatePlayers`), actualiza los slots de `MatchingWaitMemberDisplayView` (DisplayType `104`) y permanece en `NormalMatchingEntryState`.
    - `Result 1 (Success)` -> RVA `0x13EE4F8`: Configura el room ID y salta a `0x13EE52C` (`NormalMatchingJoinBattleRoomState`), cerrando la sala e iniciando la carga de `GameScene`.
    - `Result 2 (Error)` -> RVA `0x13EE564`: Llama a reintentos.
  - Un parche previo en `0x13EE4EC` forzaba un salto incondicional a `0x13EE52C`, anulando el `Result 0`.
- **Estructura de la pantalla requerida** (`media_1789073900084.jpg`):
  1. Header: *"Combate normal - Cristalmanía"*.
  2. Subheader de estado: *"Esperando participantes..."* (cuando `numWait > 0`) o *"Iniciar combate"* (cuando `numWait == 0`, controlado por `MatchingWaitMemberDisplayView.SetWaitNum`, RVA `0x14EF69C`).
  3. Roster de 8 jugadores (4v4 según `GameModeTypeExtensions.GetPlayerCount(3) = 8`):
     - Slot 1: Jugador humano (`Gixarde3`, avatar, rango, icono).
     - Slots 2..4: Compañeros de equipo (Aliados / Team 0).
     - Slots 5..8: Rivales (Enemigos / Team 1).
  4. Pie de pantalla: *"Mazo propio"* con los 4 discos equipados, nivel fijado ("Nivel 5") y arte del kicker.
- **Solución implementada en el servidor**:
  - `BattleMatchmakingService.cs` soporta streaming en 3 etapas:
    - *Etapa 1*: Envía asignación con `Connection = ""` y solo el jugador local. El cliente entra a `MatchingWaitMemberDisplay` mostrando "Esperando participantes...".
    - *Etapa 2*: Envía asignación con `Connection = ""` y los 8 slots poblados (humano + bots o 2 humanos + 6 bots). El cliente actualiza la lista y muestra "Iniciar combate".
    - *Etapa 3*: Tras presionar "Iniciar combate" o vencer el timer (3-5s), envía `Connection = room.BattleId` (Result 1). El cliente hace el dispatch a `NormalMatchingJoinBattleRoomState`.

### 1.2. HUD Renderizado como Repetición/Espectador en vez de Juego Real
- **Síntoma original**: Los discos en combate aparecían con marcos rojos de espectador (`SpectatorInfoView`), sin controles táctiles interactivos ni barra de vida de jugador.
- **Causa raíz descubierta en `libil2cpp.so`**:
  - `ScrambleRuleController.InGameUIPresenterInit` (RVA `0x15D2B78`) evalúa `MenuTypeExtensions.IsSpectatorMode(GameManager.GetMenuType())`.
  - Si el resultado es `1` (Spectator/Replay), inicializa `SpectatorInfoPresenter` (RVA `0x15D2DD0`) -> Discos rojos pasivos.
  - Si el resultado es `0` (Default), inicializa `PlayerInfoPresenter` (RVA `0x1745578`) -> HUD interactivo real (`media_1789078663610.jpg`).
  - Además, `ReplayManager.get_ReplayMode` (RVA `0x1773670`) devolvía `1` en offline mode.
- **Solución implementada en `scripts/patch-il2cpp-endpoints.py`**:
  - Parche RVA `0x1773670` (`ReplayManager.get_ReplayMode`): `mov w0, wzr; ret` (`e0031f2ac0035fd6`). Fuerza `ReplayMode = 0`.
  - Parche RVA `0x1570EA8` (`GameManager.GetMenuType`): `mov w0, wzr; ret` (`e0031f2ac0035fd6`). Fuerza `MenuType = 0` (`Default`).
  - Con esto, el cliente instancia `PlayerInfoPresenter`: 4 discos verdes interactivos con countdown de cooldown ("45"), botón SP central, ATQ (2119), HP (16811) y radar.

### 1.3. Controles del Jugador Congelados / Inoperativos
- **Síntoma original**: El personaje aparecía estático en la arena; los swipes y taps en la pantalla no producían rotación, vuelo ni ataques.
- **Causa raíz descubierta en `libil2cpp.so`**:
  - `PlayerStateNormal.UpdateAction` (RVA `0x017E136C`) maneja toda la máquina de estados de movimiento (`UpdateFly`, lectura del touch pad virtual, cálculo de velocidad angular y vector de impulso).
  - Un parche anterior para evitar null-pointer exceptions había colocado un stub general en `0x017E136C`: `mov w0, wzr; ret`. Esto apagaba el 100% de la lógica de vuelo y controles.
- **Solución implementada**:
  - Eliminar el stub general en `0x017E136C`.
  - Mantener exclusivamente los null-guards granulares en `0x017E13EC` y `0x017E13D4`, permitiendo que `UpdateAction` y `UpdateFly` se ejecuten libremente con el input del usuario.

---

## 2. ESTADO DE LOS BUGS ORIGINALES (A, B, C)

### 2.1. Bug A: Crash al Presentar Equipo Enemigo (`signal 11 / SIGSEGV`)
- **Diagnóstico**: Durante `GameStartAnimation.PlayReadyAnimation` (RVA `0x1762CE0`), tras presentar al Team 0, la cinemática pasa al Team 1. En `0x1762D80`, verifica si el evento actual es un festival (`FestivalManager`). Al ser null en el servidor privado, causaba dereferencia nula y SIGSEGV.
- **Parches aplicados**:
  - `0x01762D80`: Bypass de festival check mediante salto seguro a `0x1762F3C`.
  - `0x013BC314` (`PlayerBoneController.SetDisplayAngles`): Stub safe `ret` para evitar crash si el esqueleto del kicker enemigo no ha enlazado sus transforms antes de que la cámara gire hacia ellos.

### 2.2. Bug B: Crash en Intentos Subsecuentes
- **Diagnóstico**: Ocurría porque la sesión de Photon / gRPC previa dejaba handlers colgados en `MatchingManager` y `SceneManager._isChangeScene`.
- **Mitigación**: Limpieza de salas en el servidor (`BattleMatchmakingService`) y parches de desregistro seguro en `GetAssignmentsDestroy` (`0x13EAFB4`).

### 2.3. Bug C: Catálogo Octo y Assets Faltantes
- **Estado**: Catálogo con 2,579 recursos catalogados y `octo_cache.tar` con 5,160 assets (728.9 MB). Los assets críticos de la arena `FLD00101` y shaders `preloadgameshadervariants` están verificados y cacheados.

---

## 3. REGRESIÓN RECIENTE DETECTADA (CRÍTICA)

Durante la última iteración de parches en `scripts/patch-il2cpp-endpoints.py`:
- Se modificó `TitleView.Initialize` en el offset `0x31C796C` cambiando la instrucción por un `ldp x29..x23; ret`.
- **Efecto colateral indeseado**: En `0x31C7968`, `TitleView.Initialize` llama a `SetAllButtonActive(false)`. Al retornar de inmediato en `0x31C796C`, **nunca** ejecuta el bloque que asigna alpha 1.0 al `CanvasGroup` (`fmov s0, 1.0; bl 0x31852dc`) ni activa los listeners de toque del botón Start, dejando la pantalla en "CARGANDO..." o con botones inactivos.
- **Acción inmediata obligatoria**:
  - Revertir el parche en `0x31C796C` a su versión segura original en `0x31C7970`:
    ```python
    {
        "description": "bypass null _canvasGroup crash in TitleView.Initialize",
        "offset": 0x31C7970,
        "expected": bytes.fromhex("740000b5e0031faa1d328197"),  # cbnz x20, #0x31c797c; bl #0x12141ec
        "replacement": bytes.fromhex("f40000b4020000141f2003d5"),  # cbz x20, #0x31c797c; nop
    }
    ```

---

## 4. MULTIJUGADOR: PRUEBAS EN DOS EMULADORES

### Arquitectura de Matchmaking Multi-Cliente
En `BattleMatchmakingService.cs`:
1. **Cliente 1 (`emulator-5554`)**:
   - `auth/prepare` + `auth/index` -> `userId = 1000001` (`Gixarde3`).
   - `battle/entry` -> Registra intención en regla 1 (Cristalmanía).
   - Servidor crea `ActiveBattleRoom` y asigna al Cliente 1 al Team 0 (Slot 1).
2. **Cliente 2 (`emulator-5556`)**:
   - `auth/prepare` + `auth/index` -> `userId = 1000002` (`Player 0002`).
   - `battle/entry` -> Servidor detecta la sala existente con regla 1 y añade al Cliente 2 al Team 1 (Slot 5).
3. **Población con Bots**:
   - Team 0: Cliente 1 (humano) + 3 bots = 4 jugadores.
   - Team 1: Cliente 2 (humano) + 3 bots = 4 jugadores.
   - Total: 8 jugadores.
4. **Sincronización de Inicio**:
   - Ambos clientes reciben en su gRPC stream `GetAssignments` la misma lista de 8 jugadores.
   - Ambos ven la pantalla de sala (`MatchingWaitMemberDisplayView`).
   - Al pulsar "Iniciar combate" o expirar el tiempo de espera, el servidor transmite `Connection = battleId` a ambos streams gRPC, coordinando la entrada simultánea a `GameScene`.

---

## 5. CHECKLIST DE EJECUCIÓN PASO A PASO

### Paso 1: Corregir el parche de `TitleView.Initialize`
- [ ] En `scripts/patch-il2cpp-endpoints.py`, restaurar el offset `0x31C7970` para evitar el bloqueo en pantalla de inicio.
- [ ] Ejecutar prueba dry-run: `python3 scripts/patch-il2cpp-endpoints.py --dry-run .local/libil2cpp_clean.so`.

### Paso 2: Reconstruir e Instalar APK
- [ ] Recompilar APK directa:
  ```bash
  SERVER_BASE_URL="http://10.0.2.2:18080" ./scripts/build-direct-apk.sh
  ```
- [ ] Instalar en `emulator-5554`:
  ```bash
  adb -s emulator-5554 install -r .local/artifacts/KickFlight-2.11.0-direct-10.0.2.2-18080.apk
  ```
- [ ] Instalar en `emulator-5556` (si está iniciado):
  ```bash
  adb -s emulator-5556 install -r .local/artifacts/KickFlight-2.11.0-direct-10.0.2.2-18080.apk
  ```
- [ ] **OBLIGATORIO: sembrar la caché Octo completa en cada dispositivo** (ver §7.1):
  ```bash
  python3 scripts/seed-device-cache.py -s emulator-5554
  python3 scripts/seed-device-cache.py -s emulator-5556 --skip-tar
  ```
  El flujo de descarga normal sólo deja ~850 bundles en `files/octo`; `GameScene` necesita los
  2,579 preservados. Sin la siembra el cliente muere en la pantalla "Cargando..." con
  `SIGSEGV fault addr 0x7b0` en `libunity.so+0x34426c`. `pm clear` borra la siembra: repetirla
  después de cualquier `--clean`. `scripts/test-battle-loop.sh` ahora lo comprueba y siembra solo
  (`--no-seed` para omitirlo).

### Paso 3: Validar Flujo Monojugador (1 Emulador)
- [ ] Ejecutar: `./scripts/test-battle-loop.sh --no-install -d emulator-5554`.
- [ ] Capturar screenshot de la sala de espera y verificar:
  - Header: *Combate normal - Cristalmanía*.
  - 8 slots poblados con Gixarde3 y los bots.
  - "Mazo propio" visible en la parte inferior con 4 discos y kicker.
  - Botón "Iniciar combate" activo.
- [ ] Transición a combate:
  - Verificar que no haya SIGSEGV en la cinemática de presentación de aliados ni de enemigos.
  - Verificar HUD real (`media_1789078663610.jpg`): 4 cartas con cooldown numérico, botón SP central, ATQ/HP y radar.
- [ ] Validar controles:
  - Enviar swipe táctil: `adb -s emulator-5554 shell input swipe 540 1200 540 600 300`.
  - Confirmar en logcat que `UpdateFly` actualiza la posición y velocidad del kicker.

### Paso 4: Validar Flujo Multijugador (2 Emuladores)
- [ ] Iniciar ambos emuladores y el servidor (`./scripts/run-local.sh`).
- [ ] Lanzar el juego en `emulator-5554` y `emulator-5556`.
- [ ] Entrar a "Combate" en ambos dispositivos.
- [ ] Confirmar que en la pantalla de sala de ambos emuladores aparecen:
  - `Gixarde3` en el equipo azul (Team 0).
  - `Player 0002` en el equipo rojo (Team 1).
  - Los bots correspondientes completando los 8 slots.
- [ ] Pulsar "Iniciar combate" y constatar que ambos emuladores cargan la misma batalla en `GameScene`.

---

## 6. COMANDOS ÚTILES DE REFERENCIA

```bash
# Servidor local
./scripts/run-local.sh

# Captura de pantalla escalada a 720px (regla de contexto)
adb -s emulator-5554 exec-out screencap -p > /tmp/screen_raw.png && sips --resampleWidth 720 /tmp/screen_raw.png --out /tmp/screen_720.png

# Inspeccionar logs relevantes de combate y matchmaking
adb -s emulator-5554 logcat -d | grep -E "MatchingScene|GetAssignments|NormalMatching|GameScene|PlayerInfoPresenter|PlayReadyAnimation|PlayGoAnimation|UpdateFly|SIGSEGV" | tail -n 50

# Test automatizado de combate
./scripts/test-battle-loop.sh --no-install -d emulator-5554
```

---

## 7. PROBLEMAS CONOCIDOS (actualizado 2026-09-11, commit 99a7f6f)

### 7.1. Crash en "Cargando..." de `GameScene` si la caché Octo no está sembrada — RESUELTO (procedimiento)
- **Síntoma**: `SIGSEGV, SEGV_MAPERR, fault addr 0x7b0`, hilo `UnityMain`, frames
  `libunity.so+0x34426c` / `+0x6d86c4`, entre 7 y 13 s después de `D Unity: GameScene`, sin que
  la arena llegue a dibujarse. No aparece ninguna excepción Unity previa en logcat.
- **Causa**: assets faltantes. El catálogo (`config/resources/catalog.json`) sólo hace que el cliente
  descargue ~850 archivos; `libunity.so+0x344238` es la rutina variádica de log/assert de Unity y el
  cliente muere intentando *reportar* el fallo de carga. No depende del commit, de la ABI ni de la
  traducción `ndk_translation` (se reprodujo 3/3 en x86_64 y desapareció al sembrar).
- **Solución**: `scripts/seed-device-cache.py` (2,579 bundles, 729 MB) antes de entrar a combate.
  Verificación rápida: `adb shell run-as jp.grenge.kickflight find files/octo -type f | wc -l`
  debe dar ~5160. Tras sembrar, el arranque hace **1** petición `/cdn/` en lugar de ~280.
- **Verificado con siembra** en `KickFlight_A15` (x86_64 + ndk_translation): sala 4v4, presentación
  de aliados y enemigos sin crash, HUD real (`PlayerInfoPresenter`), controles de vuelo operativos,
  0 excepciones Unity, proceso vivo > 3 min. Capturas: `.local/battle-test/run-99a7f6f-seeded/`.

### 7.2. La partida nunca arrancaba: reloj fijo en 3:00 — RESUELTO (2026-09-11)
- **Síntoma**: tras la presentación de equipos el HUD aparece completo pero el temporizador no
  cuenta, el marcador no cambia y los 7 bots (`kickerAiParameterId > 0`) se quedan en su spawn.
  El jugador humano sí vuela y la cámara le sigue.
- **Lo que sí ocurre**: `battle/entry` 200 → gRPC Stage 1/2/3 → `battle/start` 200; el cliente
  carga `FLD00101`, instancia los 8 kickers y construye el HUD. Ninguna excepción en logcat.
- **Causa raíz (ingeniería inversa de `libil2cpp.so`, 2026-09-11)**:
  - El reloj usa `GameManager.GameElapsedTime`, que devuelve 0 mientras `IsGameStarted == false`.
    `IsGameStarted` sólo se pone a `true` en `set_GameStartTime(t)` con `t != -1`, y ese valor llega
    **exclusivamente** por la propiedad de sala Photon `"RoomStartTime"` (`CallbackRoomPropertiesUpdate`
    RVA `0x1574BA4`, `GetRoomProperty<double>(room, "RoomStartTime", -1.0)`).
  - `"RoomStartTime"` la escribe el master en `GameManager.UpdateState` (RVA `0x156E8E0`), una máquina
    de estados sobre la propiedad de sala `"RoomState"` (`PhotonRoomStateType`):
    `None/Matched` --(PlayerState==PreLoaded)--> `PreLoaded(4)` --(==CreatedObject)--> `CreatedObject(5)`
    --(==Readied)--> `Playing(6)` --(PlayerState==Playing)--> escribe `RoomStartTime = NetworkTime`.
    Cada transición exige que **todos** los jugadores Photon tengan `"PlayerState"` **exactamente** igual
    al valor esperado (`IsPlayerStateComplete`, RVA `0x1A29FF4`, `cmp w0,w21; b.ne`). En modo offline
    la lista de jugadores es sólo el local, y `IsRoomLocalPlayerMaster()` es `true` (`PhotonManager.IsOffline`).
  - `UpdateState` se ejecuta por dos vías: (1) `ManagedUpdate` cada frame, pero sólo cuando el manager
    está `Initialized`, es decir **después** de que `GameManager.BeginAsync` termine
    (`SystemManager.Update` filtra `ManagerInfo.IsState(2)`); (2) dentro de
    `PhotonPropertyManagerBase.IsRoomStateComplete(n)` (RVA `0x1A2A608`), que hace
    `this.UpdateState(); return RoomState == n;` y es el predicado de los `WaitWhile` de `BeginAsync`.
  - Los parches previos forzaban a `false` los seis `<BeginAsync>b__1..b__6`. `b__2` y `b__5` son
    `!IsRoomStateComplete(4)` / `!IsRoomStateComplete(5)`: al anularlos, `UpdateState` nunca corre
    durante `BeginAsync`, `RoomState` se queda en `None` y, cuando `ManagedUpdate` empieza a llamarlo,
    `PlayerState` ya es 3-4 mientras el caso `None` exige exactamente 1. Bloqueo permanente: sin
    `RoomStartTime`, sin `IsGameStarted`, sin reloj y sin IA.
  - El transporte offline sí funciona: `Player/Room.SetCustomProperties` de este PUN2 hacen `Merge` y
    disparan `OnPlayerPropertiesUpdate` / `OnRoomPropertiesUpdate` síncronamente cuando la sala es offline.
- **Fix aplicado**: eliminar de `scripts/patch-il2cpp-endpoints.py` los parches de `0x0157999C` (`b__2`)
  y `0x01579B80` (`b__5`). Se mantienen `b__1/b__3/b__4/b__6` (`IsCreatedSceneObject`, `IsCreatedPlayer`,
  `IsCreatedCommonObject`), que sí dependen de instanciación Photon. Orden verificado en la corrutina:
  estado 5 `UpdatePlayerState(1)` → espera `b__2`; estado 8 `UpdatePlayerState(2)` → espera `b__5`;
  `WaitReadiedAsync` → `UpdatePlayerState(3)`; `OnEndReadyGoAnimation` → `UpdatePlayerState(4)`.
- **Segundo bloqueo encontrado con trazas (`KF_DIAG=1`, tag logcat `KFDIAG`)**: aun con los waits
  restaurados la traza era `PlayerState 1 -> RoomState 4 -> PlayerState 2 -> RoomState 5 -> PlayerState 4`
  y **nunca `PlayerState 3 (Readied)`**. `Readied` sólo lo publica `WaitReadiedAsync`, que arranca desde
  `GameReadyScene._onCompleted` (`OnEndCutScene -> OnCompleted`), es decir al terminar la timeline de la
  escena de preparación — que los parches ponytail saltan por completo. Sin `Readied`, `UpdateState`
  no pasa de `CreatedObject(5)` y `RoomStartTime` nunca se escribe.
- **Fix 2**: cave en `GameManager.GetMenuType` (cuerpo muerto) + hook en
  `GameStartAnimation.PlayGoAnimation` (`0x17630EC`) que llama a `GameManager.CompleteGameReady()`
  (`GetSubScene<GameReadyScene>() -> Complete() -> OnCompleted()`, idempotente, y además restaura cámara,
  DOF y canvas: invocar sólo el delegado deja la cámara cinemática sin HUD).
- **Fix 3**: en este flujo `OnEndReadyGoAnimation` publica `Playing(4)` ~0,2 s ANTES de que el
  `WaitReadiedAsync` asíncrono escriba `Readied(3)` (lo pisa). Se relaja el último gate de `UpdateState`
  (`0x156EB14`: `cmp w0,#4; b.ne` -> `cmp w0,#3; b.lt`, PlayerState >= Readied).
- **Resultado**: reloj 3:00 -> 2:42 -> 2:10 -> 1:41, `RoomState = Playing`, `IsGameStarted = true`.
  Capturas: `.local/battle-test/run-final-clean/`.

### 7.4. IA de los bots — PARCIAL (2026-09-11)
- **Bloqueo 1 (resuelto)**: el parche de `0x017E13C4` salía de `PlayerStateNormal.UpdateAction` para todo
  `PlayerType != User`, apagando la máquina de movimiento de los 7 bots. Ahora sólo queda el null-guard
  sobre el `PlayerCharacter` dueño.
- **Bloqueo 2 (resuelto)**: al habilitar `UpdateAction` para bots aparecían ~40 `NullReferenceException`/s
  desde `libunity` (`Animator.SetFloat` con `Animator` nulo/destruido) vía
  `PlayerAnimator.SetParamVelocity`. Cada excepción abortaba `ObjectManager.ManagedUpdate` y con ello
  todos los managers posteriores del frame (incluido `GameManager`: reloj parado). Guard de entrada en
  `SetParamVelocity` (`0x13B3BA4` -> cave): retorna si `Animator == null` o su `m_CachedPtr == 0`.
- **Estado**: con la build limpia los 7 bots tienen `_enableAi = true` y `AIPlayerEngine.Start`
  ejecutado (trazas `601`/`700` x7), 0 excepciones, y **Kaito Bot se mueve por la arena**. Coco, Ruriha y
  el resto siguen quietos: `AIPlayerEngine.ManagedUpdate` los deja en `WaitForWarpOut` porque su
  `IsWarp` nunca se limpia — la animación de warp-in depende del `Animator`, que para esos kickers está
  muerto (objeto Unity destruido/sin nativo; `PlayerCharacter.SetAnimator` no lanza, así que se crea y
  algo lo destruye después). Siguiente paso: averiguar qué destruye el objeto Animator de los bots
  (candidatos: `PrepareAI`/`ResetAi`, `ModelManager.InstantiatePlayerAnimator` para kickers != 1/2, o
  la ruta de modelos "enemigos" estubada) — con `KF_DIAG=1` el hook I registra el sitio de cada NRE.
- **Bloqueo 3 (resuelto)**: los bots restantes no salían del warp-in. `AIPlayerEngine.ManagedUpdate` los deja
  en `WaitForWarpOut` mientras `IsWarp` (`PlayerCharacter+0x2b4`) esté activo, y sólo `AcceptCancelWarp` lo
  limpia — que empieza con `if (!CharacterBase.IsMine) return`. `IsMine` es `photonView.IsMine`: false para
  los bots (sus PhotonView pertenecen a actores inexistentes). Online el master posee a los jugadores IA;
  offline el único cliente debe poseerlo todo. Parche: `CharacterBase.IsMine` (`0x16B69BC`) devuelve `true`
  cuando `PhotonManager.IsOffline()` (cave en el cuerpo muerto de `ReplayManager.get_ReplayMode`).
- **Bloqueo 4 (resuelto, servidor)**: `PlayerCharacter.GetKickerAIParameterMaster(kickerId, rank)` elige la
  fila de `KickerAiParameter` más cercana con `fila.rank <= rango del jugador`. Todas las filas tienen
  `rank = 13` y el roster daba a los bots `rank = 10 + i % 4`, así que sólo los de rango 13 (Coco, Diatrius)
  tenían parámetros de IA. `BattleMatchmakingService.BuildRoster` ahora envía `rank = 13` a los bots.
- (Descartado) el prefab de rutas `AI/Helper/Scramble50` sí está en los Resources de la APK (`data.unity3d`
  contiene `ai/helper/{ballshoot,default,flagbattle,scramble50,trial,tutorial}`).
- Herramientas: `scripts/re/` (disasm anotado, xref, slots) y el bloque `DIAG_PATCHES_ARM64`.

### 7.5. Partida completa y pantalla de resultados — FUNCIONA (2026-09-11)
- Con el reloj corriendo la partida llega a `Timeup` a los 3:00 (banner "queda 1 minuto" a 1:00),
  `battle/end` 200, `ResultScene`, `battle/result`, marcador de equipos, "Aceptar", resultado personal,
  "Volver a Inicio" -> `home/index` -> `HomeScene`. Sin crashes.
- `/battle/result` caía en el comodín `/battle/*` (`{}`); el cliente construye `BattleResultInfo` sin
  comprobar nulos (`PlayerLevelUpRewardListInfo..ctor` -> NRE) y la pantalla se quedaba sin botón.
  Nuevo `HandleBattleResultAsync` en `DemoSessionApi.cs` con todas las listas de
  `BattleResultResponseData` (vacías) y `userExp` coherente con el exp servido en `home/index`
  (si no, la barra muestra "-37200/1000").
- Cosmético: `ResultUIManager.PlayRandomStamp` lanza un `ArgumentOutOfRangeException` una vez (lista de
  stamps vacía); inocuo.
- **Estado**: ver resultado de la prueba en `.local/adb-loop-notes.md`.

### 7.3. `scripts/patch-il2cpp-endpoints.py` guard #1 (`0x31B5024`) vs `base.apk` pristina
- Desde ca0d3b4 el guard esperaba `e8030aaa` (base ya parcheada). Con la `base.apk` original
  (sha256 `2993d66e…`, la registrada en `config/apk-direct-server.local.json`) el byte es `28118a9a`
  y el `--dry-run` fallaba en la primera entrada. Restaurado a `28118a9a`; la ruta `alreadyPatched`
  sigue aceptando bases pre-parcheadas. Los 118 parches arm64 verifican contra la base pristina.
