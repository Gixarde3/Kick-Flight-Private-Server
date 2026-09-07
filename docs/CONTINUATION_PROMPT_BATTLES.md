# CONTINUATION PROMPT: KICK-FLIGHT BATTLE SYSTEM & SCENE SPAWN RESOLUTION

> **Propósito**: Este documento es el prompt canónico y exhaustivo de continuación para que un nuevo agente retome inmediatamente la implementación del sistema de batallas de Kick-Flight 2.11.0 en una nueva ventana de contexto limpia. Contiene el estado exacto alcanzado, el script de prueba automatizado, el análisis de desensamblado ARM64 del blocker actual (`PlayerCharacter.SetModel`), las llamadas a funciones IL2CPP y la ruta directa hacia la resolución final.

---

## 1. ESTADO ACTUAL ALCANZADO (100% AUTOMATIZADO Y VERIFICADO)

### Flujo Completo Operativo:
1. **Backend ASP.NET Core (`src/KickFlight.BootstrapApi`)**:
   - Activo y saludable en `10.0.2.2:18080` (HTTP/1.1) y `18081` (gRPC HTTP/2).
   - Handlers implementados y verificados:
     - `/boot/index`: HTTP 200 con configuración de cliente.
     - `/auth/prepare`, `/auth/index`, `/startup/index`, `/download/master`: Carga limpia.
     - `/home/index`: HomeScene dinámico con Tsubame 3D, mazo, cápsulas y arena 3D FLD99999.
     - `/follow/online`, `/ping/index`: Pings periódicos y presencia online.
     - `/battle/entry` y gRPC `GetAssignments`: Empareja al jugador humano con 7 bots (4v4) de la lista de 14 Kickers con IA (`BattleMatchmakingService.cs`).
     - `/battle/start`: Responde HTTP 200 con `fieldId: 101` (Arena Cristalmanía / Scramble50), `guardianParameter`, `lotteryFestivalPointId: 0`.

2. **Parches Nativos ARM64 Aplicados en APK (`scripts/patch-il2cpp-endpoints.py`)**:
   - `0x31B5024`: Fuerza protocolo HTTP para comunicación directa con el servidor local.
   - `0x17331C0`: Bypass del setup de Firebase Chat muerto en `HomeChatNotificationView.OnCompleteChatSetup`.
   - `0x1890c50`: Bypass del format string nulo en `BattleRuleDefaultView.SetView`.
   - `0x159DF5C` y `0x159E254`: Bypasses de excepciones nulas en `HomeSummonModelController`.
   - `0x14E16AC`: Fuerza `MatchingManager.IsRoomLocalPlayerMaster` a retornar `true`.
   - `0x13EB238`: NOP a `tbnz w0, #0, #0x13eb338` (evita early-return por `IsMatched` en `NormalMatchingController.BattleStart`).
   - `0x13EB25C`: NOP a `tbz w0, #0, #0x13eb338` (evita early-return por `IsRoomLocalPlayerMaster` en `NormalMatchingController.BattleStart`).
   - `0x13EB720`: NOP a `b.eq #0x13eb868` en `NormalMatchingController.CallbackRoomPropertiesUpdate` (elimina la llamada prematura a `ChangeGameSceneSync` al fijar `status == 3`).
   - `0x13EA054`: Branch incondicional `b #0x13ea1a0` en `CallbackBattleStartSuccess` (salta el check nulo de `ArchiveData.BattleRuleInfo`, permitiendo que `CallbackBattleStartSuccess` invoque limpiamente a `MatchingManager.BattleStart`).
   - `0x31C496C`: `ret` (`c0035fd6`) en `TitleView.SetAllButtonActive` (elimina el crash por botón nulo durante el inicio de `TitleScene`).

3. **Script de Prueba Automatizado Creado**:
   - `scripts/test-battle-loop.sh` ejecuta el ciclo completo en 40 segundos:
     - Salud del backend (`/boot/index`).
     - Lanzamiento limpio de la app (`com.google.firebase.MessagingUnityPlayerActivity`).
     - Detección de `TitleScene` y pulsación de `TAP START` en `(540, 1200)`.
     - Espera de carga de `HomeScene` y descarte del modal de novedades en `(540, 2220)`.
     - Pulsación del botón "Combate" en `(820, 1480)` y entrada a la sala de Matchmaking.
     - Pulsación de "Iniciar combate" en `(540, 630)`.
     - Transición a `GameScene` (`FLD00101`).
     - Captura screenshots redimensionados automáticamente a 720px en cada fase y los guarda en `.local/battle-test/run_<timestamp>/` con symlink persistente en `.local/battle-test/latest/`.

---

## 2. EL BLOCKER ACTUAL EXACTO (DIAGNÓSTICO COMPLETO)

### Logcat de la Falla:
```text
09-07 09:18:13.892 15366 15440 D Unity   : MatchingScene
09-07 09:18:17.377 15366 15440 D Unity   : GameScene
09-07 09:18:20.128 15366 15440 W Unity   : The loaded level has a different lightmaps mode than the current one.
09-07 09:18:23.549 15366 15440 E Unity   : NullReferenceException: Object reference not set to an instance of an object.
09-07 09:18:23.549 15366 15440 E Unity   :   at Colorful.PlayerCharacter.SetModel (System.Int32 characterId, System.Single footHeight, System.Single height, Colorful.PlayerInitializeInfo initInfo) [0x00000] in <00000000000000000000000000000000>:0 
09-07 09:18:23.549 15366 15440 E Unity   :   at Colorful.PlayerCharacter.ResetPlayer (Colorful.PlayerInitializeInfo initInfo) [0x00000] in <00000000000000000000000000000000>:0 
09-07 09:18:23.549 15366 15440 E Unity   :   at Colorful.PlayerCharacter.Initialize (Colorful.PlayerInitializeInfo initInfo) [0x00000] in <00000000000000000000000000000000>:0 
09-07 09:18:23.549 15366 15440 E Unity   :   at Colorful.ObjectManager.ReceiveAddPlayer (Colorful.PlayerCharacter player, Colorful.PlayerInitializeInfo initInfo) [0x00000] in <00000000000000000000000000000000>:0 
09-07 09:18:23.549 15366 15440 E Unity   :   at Colorful.PlayerRPCController.OnPhotonInstantiate (Photon.Pun.PhotonMessageInfo info) [0x00000] in <00000000000000000000000000000000>:0 
09-07 09:18:23.549 15366 15440 E Unity   :   at Photon.Pun.PhotonNetwork.NetworkInstantiate (Photon.Pun.InstantiateParameters parameters, System.Boolean sceneObject, System.Boolean instantiateEvent)
```

---

## 3. INGENIERÍA INVERSA DEL CRASH (`PlayerCharacter.SetModel`)

### Localización en Binario (`libil2cpp.so` ARM64):
- **Clase**: `Colorful.PlayerCharacter` (Línea 551849 en `dump.cs`).
- **Método**: `SetModel(int characterId, float footHeight, float height, PlayerInitializeInfo initInfo)`
- **RVA**: `0x13C8E80`

### Desensamblado de la Sección Crítica en `0x13C8E80`:
```assembly
0x13c8ef4: bl 0x2920b7c          ; ModelManager.get_Instance() -> x20
0x13c8efc: cbnz x20, 0x13c8f08   ; Comprueba si ModelManager != null
0x13c8f04: bl 0x12141ec          ; throw NullReferenceException()
0x13c8f14: bl 0x1a7ca3c          ; Component.get_transform(PlayerCharacter) -> x22
0x13c8f1c: cbnz x22, 0x13c8f28   ; Comprueba si transform != null
0x13c8f24: bl 0x12141ec          ; throw NullReferenceException()
0x13c8f48: bl 0x19f53e8          ; ModelManager.InstantiatePlayerModel<PlayerModelController>(...) -> x22
0x13c8f54: cbnz x22, 0x13c8f5c   ; <<< CHECK CRÍTICO: Comprueba si el modelo instanciado != null
0x13c8f58: bl 0x12141ec          ; <<< THROW NullReferenceException si x22 == 0!
0x13c8f6c: bl 0x1752768          ; Continúa configurando Animator, Bones, etc.
```

### Causa Raíz Identificada:
1. Al instanciar a cada jugador con `ObjectManager.ReceiveAddPlayer`, `PlayerCharacter.SetModel` llama a `ModelManager.InstantiatePlayerModel<PlayerModelController>` en `0x13c8f48` (RVA `0x19F53E8`).
2. `InstantiatePlayerModel` busca el AssetBundle del modelo del kicker (o en la caché de `LoadManager._cacheModels`).
3. Si el modelo aún no está en caché o la instanciación devuelve `null` (`x22 == 0`), la instrucción en `0x13c8f54` (`cbnz x22, 0x13c8f5c`) no salta, cayendo directamente en `0x13c8f58`:
   ```assembly
   0x13c8f58: bl 0x12141ec   ; throw NullReferenceException
   ```
4. Esto interrumpe la instanciación de los 8 jugadores y detiene la secuencia de inicio de batalla, impidiendo que se invoque a `PlayStartAnim` (RVA `0x1764134`).

---

## 4. CÓMO REPRODUCIR EN 1 COMANDO

Para ejecutar la prueba completa de inmediato en el emulador (sin consumir tokens):
```bash
./scripts/test-battle-loop.sh --no-install
```

Si has modificado parches en `scripts/patch-il2cpp-endpoints.py` y deseas recompilar, instalar y probar automáticamente:
```bash
./scripts/test-battle-loop.sh --build
```

El script imprimirá el estado en vivo y guardará todos los screenshots en `.local/battle-test/latest/`.

---

## 5. PLAN DE ACCIÓN PARA EL SIGUIENTE AGENTE

### Paso 1: Inspeccionar `ModelManager.InstantiatePlayerModel` (RVA `0x19F53E8`) y `SetModel` (RVA `0x13C8E80`)
- Verificar cómo `InstantiatePlayerModel` obtiene el prefab:
  - ¿Busca en `LoadManager._cacheModels`?
  - ¿O busca en `AssetBundleManager` por `chara/k010/k010_001_low.unity3d`?
- Comprobar en `scripts/patch-il2cpp-endpoints.py` el parche existente en `0x19F5338` y `0x19F53A8`:
  ```python
  # scripts/patch-il2cpp-endpoints.py (línea 151)
  {
      "description": "safely return null when model asset is null in ModelManager.InstantiateModel",
      "offset": 0x19F5338,
      ...
  }
  ```
  Si `InstantiateModel` devuelve `null`, `SetModel` lanza NRE en `0x13c8f58`.

### Paso 2: Aplicar Parche Nativo en `PlayerCharacter.SetModel` (RVA `0x13C8E80`)
En `0x13c8f54`:
- En lugar de `cbnz x22, 0x13c8f5c` seguido de `bl 0x12141ec`, manejar el caso cuando `x22 == 0`:
  - Si el modelo instanciado es `null`, saltar de forma segura la configuración de componentes del modelo y permitir que `SetModel` complete sin lanzar NRE, o instanciar un placeholder/objeto vacío.
  - Verificar qué código sigue a `0x13c8f5c` (setup de animaciones y huesos) para saltar hasta el epílogo o siguiente fase (`CreateParameter`).

### Paso 3: Asegurar la Precarga de Modelos de Batalla
- `InGameSceneBase.PreBeginAsync` (RVA `0x15A8A7C`) invoca a `LoadManager.LoadPlayerModel` (RVA `0x16E68A0`) para los 8 jugadores.
- Verificar si `LoadInGameKickerEffect` o los bundles de los 8 Kickers (`k010`, `k020`, `k030`, etc.) están siendo servidos por Octo en `http://10.0.2.2:18080/cdn/...`.

### Paso 4: Criterio de Éxito de Batalla
1. Ejecutar `./scripts/test-battle-loop.sh --build`.
2. Verificar que `PlayStartAnim` (RVA `0x1764134`) aparezca en el logcat:
   ```text
   🎉 PlayStartAnim ('3, 2, 1, FLY!') detected in logcat!
   ```
3. Inspeccionar `.local/battle-test/latest/09_battle_scene_ready.png` para confirmar que los personajes y la Arena Cristalmanía `FLD00101` están completamente renderizados y los controles de combate están activos.

---

## 6. RECURSOS Y ARCHIVOS CLAVE

- **Script de Pruebas**: [scripts/test-battle-loop.sh](file:///Users/marcochavez/Documents/variedad/Kick-Flight-Private-Server/scripts/test-battle-loop.sh)
- **Script de Parches Nativos**: [scripts/patch-il2cpp-endpoints.py](file:///Users/marcochavez/Documents/variedad/Kick-Flight-Private-Server/scripts/patch-il2cpp-endpoints.py)
- **Servicio de Matchmaking y Bots**: [src/KickFlight.BootstrapApi/BattleMatchmakingService.cs](file:///Users/marcochavez/Documents/variedad/Kick-Flight-Private-Server/src/KickFlight.BootstrapApi/BattleMatchmakingService.cs)
- **Endpoints de Sesión**: [src/KickFlight.BootstrapApi/DemoSessionApi.cs](file:///Users/marcochavez/Documents/variedad/Kick-Flight-Private-Server/src/KickFlight.BootstrapApi/DemoSessionApi.cs)
- **Dump IL2CPP**: `/Users/marcochavez/Documents/variedad/Kick-Flight-Assets/server_revival_analysis/il2cpp/dump.cs`
- **Últimos Screenshots de Prueba**: `.local/battle-test/latest/`
