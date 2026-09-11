# CONTINUATION PROMPT V3: SINCRONIZACIÓN REAL MULTIJUGADOR (PHOTON), FÍSICAS DE VUELO, COMBATE ACTIVO Y AUDIO

> **Propósito**: Guía exhaustiva, técnica y ejecutable para resolver los 5 problemas de gameplay identificados tras la restauración del combate en Kick-Flight 2.11.0: sincronización en tiempo real de jugadores en la misma arena (Photon / P2P), calibración de velocidad y aceleración de vuelo 3D (Dash), activación táctil de discos, resolución de la habilidad definitiva (Ultimate / SP) tras la cinemática, y persistencia continua de la música de fondo (BGM / CRIWARE streaming).
> **Versión**: 3.0 (Secuela directa de `CONTINUATION_PROMPT_BATTLE_CRASH_FIX_V2.md`).

---

## 0. RESUMEN EJECUTIVO Y ESTADO AL CIERRE DE V2

En la fase V2 se completaron con éxito los cimientos críticos del cliente y el servidor:
- **Sala de Matchmaking 4v4 (`MatchingWaitMemberDisplayView`)**: Operativa mediante streaming gRPC multi-etapa en `BattleMatchmakingService.cs`, mostrando los 8 slots poblados (4v4 Team 0 Azul vs Team 1 Rojo), "Mazo propio" en pie de pantalla con 4 cartas nivel 5 y subheader "Iniciar combate".
- **HUD Real de Combate Restaurado**: Se resolvió la degradación a modo espectador parchando `MatchingControllerBase.CreatePlayerBattleInfo` (`0x17A17F4`) para determinar `IsAi` desde `kickerAiParameterId != 0` en lugar de `PhotonUtil` nulo. El cliente instancia `PlayerInfoPresenter` con 4 cartas interactivas, botón SP central, estadísticas de ATQ (279) y HP (8056) y radar con cronómetro.
- **Prevención de Crashes Nativos (SIGSEGV)**: Eliminación del stub global en `0x017E136C`, bypass seguro de `FestivalManager` nulo en `0x1762D80`, safe-return en `PlayerBoneController.SetDisplayAngles` (`0x013BC314`) y protección a bots en `PlayerStateNormal.UpdateAction` (`0x017E13C4`).
- **Validación Multijugador Básica**: Dos emuladores (`emulator-5554` y `emulator-5556`) se emparejaron en la misma sala `battle-1007` y cargaron simultáneamente la arena `FLD00101` (Cristalmanía) con vuelo 3D funcional en ambos dispositivos.

---

## 1. LOS 5 PROBLEMAS DE GAMEPLAY IDENTIFICADOS Y SU DIAGNÓSTICO TÉCNICO

### 1.1. Problema 1: Falta de Sincronización en Tiempo Real entre Jugadores (Photon vs Simulación Offline Aislada)
- **Síntoma**: Ambos jugadores ingresaron al centro de la arena en sus respectivos emuladores, pero ninguno veía al otro ni sus puntos se movían en el minimapa/radar. Cada cliente operaba en su propio mundo desacoplado.
- **Causa Raíz en la Arquitectura**:
  - En `libil2cpp.so`, el flujo de red en combate de Kick-Flight está separado en dos capas:
    1. *Matchmaking y Configuración de Sala*: Controlado por HTTP/gRPC (`OpenMatch` / `BattleMatchmakingService`).
    2. *Sincronización en Batalla (Transform, Input, Vida, Radar)*: Controlado exclusivamente por **Photon Realtime / PUN (`Photon.Pun.PhotonNetwork`)**.
  - En la fase de despegue offline, el parche en `MatchingControllerBase.ApplyBattleProperties` (RVA `0x17A2148`) puenteó la llamada de conexión a la sala Photon llamando directamente a `ChangeGameSceneSync`.
  - Como consecuencia:
    - Cada cliente ejecutó `PhotonManager.CreateOfflineRoom` (RVA `0x18D783C`).
    - Las entidades de red (`Colorful.PlayerRPCController`, `PhotonView`, `OnPhotonSerializeView`) no transmiten paquetes UDP/P2P hacia el otro emulador.
    - El kicker contrario permanece en el spawn o es manejado como bot local ficticio.
- **Solución Técnica Requerida**:
  - **Opción A (Servidor Photon Realtime Local - Recomendada)**:
    - Levantar una instancia local de Photon Server (puertos UDP `5055` / `5056`) o un Photon Relay ligero.
    - En el cliente, redirigir el endpoint de Photon NameServer / MasterServer (`app.realtime.photonengine.cn` o `ns.exitgames.com`) hacia `10.0.2.2:5055` mediante parche en `scripts/patch-il2cpp-endpoints.py` o DNS redirection.
    - Restaurar el flujo original de `ApplyBattleProperties` para que ambos clientes se unan a la misma `roomName` de Photon (definida por `targetRoom.BattleId`).
  - **Opción B (Relay P2P / WebSocket en `KickFlight.BootstrapApi`)**:
    - Si se desea evitar levantar Photon Server, interceptar las llamadas de `PlayerRPCController` y `OnPhotonSerializeView` y puentearlas mediante un túnel UDP / WebSocket en el servidor C# que retransmita las coordenadas `(x, y, z)` y rotaciones de cada jugador.

---

### 1.2. Problema 2: Velocidad de Vuelo Extremadamente Lenta
- **Síntoma**: El personaje responde a los controles táctiles y vuela en 3D, pero la velocidad de desplazamiento es mínima ("lentísima").
- **Causa Raíz y Mecánica del Juego**:
  - En Kick-Flight existen **dos velocidades de vuelo distintas**:
    1. *Vuelo Estático / Flotante (Gliding / Aiming)*: Ocurre cuando el dedo se arrastra levemente cerca del centro del joystick virtual. La velocidad se rige por `groundMoveSpeedCoefficient` / `speed: 1.2`.
    2. *Vuelo Rápido / Propulsado (Dash Flight)*: Ocurre al arrastrar el dedo hacia el radio exterior del pad virtual o al realizar un doble-flick sostenido, activando los cohetes a máxima potencia (`moveDashSpeedCoefficient` y `acceleration`).
  - Factores determinantes descubiertos:
    - **Valores en `masters_kicker_parameter.json`**: En el servidor, los parámetros de Kaito (`id: 1` o `id: 2`) tienen coeficientes base en `1.0`. En la versión oficial, los kicks de Kaito contaban con aceleraciones dinámicas y velocidades multiplicadas por el nivel de kicker (Rank 13).
    - **Throw Sites Parchados en `PlayerStateNormal.UpdateAction`**: En `scripts/patch-il2cpp-endpoints.py`, los parches entre `0x017E1858` y `0x017E1964` saltan de forma preventiva al epílogo `0x17E19D4`. Si alguno de estos saltos intercepta el cálculo del vector de impulso de Dash (`UpdateFlySpeed` o `PlayerCharacter.get_MoveSpeed`), el jugador queda atrapado permanentemente en la velocidad mínima de flotación.
- **Solución Técnica Requerida**:
  - Revisar `PlayerStateNormal.UpdateFly` (RVA `0x017E136C`..`0x017E1800`) mediante desensamblado o Frida:
    - Identificar en qué offset exacto se evalúa el umbral de arrastre táctil (`VirtualPad.Magnitude >= DashThreshold`).
    - Asegurar que no se salte al epílogo antes de aplicar `PlayerStateFly.ApplyVelocity` / `Rigidbody.velocity`.
  - Calibrar `moveSpeedCoefficient`, `moveDashSpeedCoefficient` y `acceleration` en `config/masters_kicker_parameter.json` (por ejemplo, elevar `speed` de `1.2` a `3.5` y `moveDashSpeedCoefficient` a `2.5`).

---

### 1.3. Problema 3: Activación Táctil de Discos (Slide / Flick Up) [Prioridad Baja]
- **Síntoma**: Los discos no se activan al deslizar el dedo hacia arriba sobre ellos.
- **Causa Raíz Potencial**:
  - En el juego original, el lanzamiento de un disco requiere:
    1. Detección del gesto táctil vertical (`DiscPresenter.OnFlickUp`).
    2. Validación de rango y objetivo (`SkillRangeValidator.CreateValidator`). Nuestro parche en `0x18436D0` (`bypass DiscSkill InvalidCastException`) colocó un salto incondicional `b #0x184377c`. Si este salto elude la asignación de target o declara el rango como inválido (`false`), el disco no se dispara.
    3. Validación de red: Si `PlayerRPCController.SendUseDisc` espera confirmación del servidor Photon antes de entrar en `PlayerStateSkill`, en modo offline nunca recibe la confirmación.
- **Solución Técnica Requerida**:
  - Verificar en logcat si el flick emite `SkillRangeValidator` o `DiscSkillParameter`.
  - En `scripts/patch-il2cpp-endpoints.py`, ajustar el bypass de `SkillRangeValidator` para que retorne `true` (rango siempre válido) en lugar de cancelar la validación.

---

### 1.4. Problema 4: Ultimate (SP Skill) se Congela tras la Animación
- **Síntoma**: Al presionar el botón SP central, la pose y animación cinemática del Kicker se reproducen correctamente; sin embargo, al terminar la cinemática, el personaje se queda inmóvil en el lugar sin ejecutar el ataque, y sólo después de unos segundos recupera el control de vuelo normal.
- **Causa Raíz**:
  - El ciclo de vida de la habilidad especial consta de 3 estados:
    1. *Animación de Inicio (Cinemática / Pose)*: Reproducida por `GameReadyAnimation` / `PlayerStateSpecialSkill.PlayAnim`. ✅ FUNCIONA.
    2. *Spawn del Hitbox / Proyectil / Efecto*: En `ObjectManager.InstantiateSkillEffect` o `KickerSkillAction.Execute`. Si el prefab del efecto no se encuentra o si depende de un RPC de red para instanciar el proyectil sincronizado, la acción falla en silencio.
    3. *Timeout / Recuperación*: Al no completarse el callback de impacto del skill, expira el temporizador de seguridad de la máquina de estados y el kicker vuelve a `PlayerStateNormal`.
- **Solución Técnica Requerida**:
  - Hookear o desensamblar `PlayerStateSpecialSkill.Update` (o la clase específica de Kaito `KaitoSpecialSkillAction`).
  - Asegurar que la creación del área de daño / corte de espada no lance NRE y no dependa de Photon RPC para transicionar a la fase activa de ataque.

---

### 1.5. Problema 5: Pérdida de Música de Fondo (BGM) durante la Batalla
- **Síntoma**: La música de combate suena al inicio, pero trascurridos unos minutos deja de escucharse completamente.
- **Causa Raíz Identificada en el Catálogo de Audio (CRIWARE)**:
  - **Falta del archivo `.awb` de streaming**: En `config/resources/catalog.json`, sólo está registrado `audio-acb-bgm_battle01.acb`. En el sistema CRI Atom Craft, el archivo `.acb` contiene únicamente los metadatos y el bloque de pre-carga; las pistas de audio en streaming y bucles continuos se almacenan en el archivo complementario `.awb` (`bgm_battle01.awb`). Al agotarse el búfer inicial en memoria sin encontrar el `.awb`, la música se detiene.
  - **Cambio de pista en el último minuto ("Hurry Up")**: Las partidas de Kick-Flight duran 3:00 minutos. Al alcanzar el minuto 1:00 (o los últimos 30 segundos), el sistema ejecuta un crossfade hacia la versión acelerada del tema (`bgm_battle01_hurry` o `bgm_battle_hurry`). Al no existir esta pista catalogada, el tema actual hace fade-out y el nuevo nunca comienza, dejando la arena en silencio absoluto.
- **Solución Técnica Requerida**:
  - Verificar en `octo_cache.tar` o en los assets extraídos si existe `bgm_battle01.awb` y los archivos de `hurry`.
  - Catalogar los archivos `.awb` correspondientes en `config/resources/catalog.json` y actualizar `Octo.DataManager` para que se descarguen en la fase de carga.

---

## 2. CHECKLIST DE EJECUCIÓN PASO A PASO PARA V3

### Fase 1: Calibración de Físicas de Vuelo y Aceleración
- [ ] Modificar `config/masters_kicker_parameter.json`:
  - Incrementar `speed` de `1.2` a `3.2` para Kaito (`kickerId: 1` y `2`).
  - Incrementar `moveDashSpeedCoefficient` a `2.5` y `acceleration` a `2.0`.
- [ ] Revisar desensamblado de `PlayerStateNormal.UpdateFly`:
  - Asegurar que el swipe largo active la aceleración máxima sin salir anticipadamente al epílogo.
- [ ] Probar en `emulator-5554` con swipe sostenido y verificar en logcat la velocidad de `UpdateFly`.

### Fase 2: Restauración de BGM Continuo (CRIWARE Audio)
- [ ] Buscar en los archivos de assets locales los CueSheets de audio:
  - `bgm_battle01.awb`
  - `bgm_battle01_hurry.acb` / `bgm_battle01_hurry.awb`
- [ ] Agregar las entradas en `config/resources/catalog.json` y recompilar el catálogo:
  ```bash
  python3 scripts/build-title-resource-catalog.py
  ```
- [ ] Validar que durante una partida completa de 3:00 la música continúe reproduciéndose sin cortes.

### Fase 3: Resolución de la Ultimate (Kicker SP Skill)
- [ ] Inspeccionar en Frida / Logcat el ciclo de vida de `PlayerStateSpecialSkill`:
  ```bash
  adb -s emulator-5554 logcat | grep -E "SpecialSkill|SkillAction|ObjectManager"
  ```
- [ ] Aplicar guard o stub en caso de que falte instanciar el efecto de impacto, asegurando que el ataque concluya su animación con hitbox activo.

### Fase 4: Sincronización en Tiempo Real (Photon Network / Relay)
- [ ] Investigar la configuración de conexión Photon en `PhotonManager.ConnectToMaster`:
  - Localizar cadenas de conexión o hostnames de Photon en `libil2cpp.so`.
  - Evaluar implementación de Photon Server local o retransmisión de estados mediante socket relay en `KickFlight.BootstrapApi`.
- [ ] Verificar que ambos jugadores aparezcan mutuamente en el radar y se desplacen en la pantalla contraria en tiempo real.

---

## 3. COMANDOS ÚTILES PARA EL ENTORNO V3

```bash
# Iniciar backend
./scripts/run-local.sh

# Captura de pantalla de ambos emuladores escalada a 720px (Regla estricta de contexto)
adb -s emulator-5554 exec-out screencap -p > /tmp/e1_raw.png && sips --resampleWidth 720 /tmp/e1_raw.png --out /tmp/e1_720.png
adb -s emulator-5556 exec-out screencap -p > /tmp/e2_raw.png && sips --resampleWidth 720 /tmp/e2_raw.png --out /tmp/e2_720.png

# Filtrar eventos de audio CRIWARE y habilidades en combate
adb -s emulator-5554 logcat -d | grep -E "CriWare|CriAtom|SpecialSkill|PlayerRPC|UpdateFly|Photon" | tail -n 50
```
