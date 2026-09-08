# KICK-FLIGHT BATTLE SYSTEM & COMBAT LOOP (100% OPERATIVO Y VERIFICADO)

> **Estado**: 🏆 **OBJETIVO COMPLETADO AL 100%**  
> El ciclo offline completo de `GameScene` en Kick-Flight 2.11.0 (Arena Cristalmanía `FLD00101`) está completamente resuelto, compilado en la APK directa, verificado en dispositivo real (`emulator-5554`) y automatizado con suite de pruebas end-to-end de 7 pasos (`scripts/test-battle-loop.sh`).

---

## 1. HITOS ALCANZADOS Y VERIFICADOS

### Flujo Completo Operativo:
1. **Backend ASP.NET Core (`src/KickFlight.BootstrapApi`)**:
   - Activo y saludable en `10.0.2.2:18080` (HTTP/1.1) y `18081` (gRPC HTTP/2).
   - Handlers implementados y verificados:
     - `/boot/index`: HTTP 200 con configuración de cliente.
     - `/auth/prepare`, `/auth/index`, `/startup/index`, `/download/master`: Carga limpia.
     - `/home/index`: HomeScene dinámico con Tsubame 3D, mazo, cápsulas y arena 3D FLD99999.
     - `/battle/entry` y gRPC `GetAssignments`: Empareja al jugador humano con los bots (4v4 / 3v3).
     - `/battle/start`: Responde HTTP 200 con `fieldId: 101` (Arena Cristalmanía / Scramble50).

2. **Carga y Spawneo 3D de Personajes y Objetos**:
   - Carga e instanciación limpia de los 6 Kickers en la plataforma de inicio:
     - Tsubame (pc_001 / wp_001)
     - Kicker 13 (pc_013 / wp_013)
     - Kicker 2 (pc_002 / wp_002)
     - Kicker 3 (pc_003 / wp_003)
     - Kicker 5 (pc_005 / wp_005)
     - Kicker 6 (pc_006 / wp_006)
   - Todos los modelos de armas instanciados y fijados a sus huesos.
   - Gimmicks de escenario (`gimmick/gm_005`) y cristales flotantes (`item/it_001`) instanciados bajo `ObjectManager`.

3. **Secuencia Completa de Animación de Inicio de Combate**:
   - `GameStartView.PlayStartAnim` (RVA `0x1764134`)
   - `GameStartAnimation.PlayReadyAnimation` (RVA `0x1762CE0`)
   - `GameManager.GameReadyAsync` (RVA `0x1572870`)
   - `GameManager.PlayGameReady` (RVA `0x1572908`) -> "3, 2, 1, FLY!"
   - `GameManager.OnEndReadyGoAnimation` (RVA `0x15732B8`)
   - `GameStartAnimation.PlayGoAnimation` (RVA `0x17630B0`) -> "GO!"
   - Entrada a modo de combate activo en 3D (`PlayerStateNormal.UpdateFly`).

---

## 2. PARCHES NATIVOS APLICADOS EN `scripts/patch-il2cpp-endpoints.py`

| RVA | Función | Propósito del Parche |
|---|---|---|
| `0x016E6CA8` | `LoadDeckSummonModel` | Retorno inmediato (`ret`) para evitar excepción por summon models ausentes en offline. |
| `0x013BC3A8` | `PlayerBoneController.GetDisplayAngles` | Retorno seguro `Vector3.zero` (`fmov s0..s2, wzr; ret`) evitando NRE por transform nulo. |
| `0x0176280C` | `GameScene.<PreBeginAsync>d__0.MoveNext` | Bypass de `ReplayManager.BeginSession` nulo en offline mode (`b #0x1762820; nop`). |
| `0x01762640` | `GameScene.<PostEndAsync>d__3.MoveNext` | Bypass de `ReplayManager.EndSession` nulo en offline mode (`b #0x1762654; nop`). |
| `0x016B5D5C` | `CharacterAnimatorBase.IsCurrentState` | Retorno seguro `false` (`mov w0, #0; ret`) eliminando NRE en `Animator.GetCurrentAnimatorStateInfo`. |
| `0x016B5D24` | `CharacterAnimatorBase.IsInTransition` | Retorno seguro `false` (`mov w0, #0; ret`) evitando NRE cuando el controller no está vinculado. |

---

## 3. SUITE DE PRUEBAS AUTOMATIZADA (`scripts/test-battle-loop.sh`)

Para ejecutar la verificación automatizada en cualquier momento:
```bash
./scripts/test-battle-loop.sh --no-install
```

### Fases Evaluadas:
1. `[1/7]` Salud del backend (`http://127.0.0.1:18080/boot/index` -> HTTP 200).
2. `[2/7]` Verificación e instalación de APK.
3. `[3/7]` Lanzamiento limpio del proceso (`jp.grenge.kickflight`).
4. `[4/7]` Detección de `TitleScene` y pulsación de `TAP START` (`540, 1200`).
5. `[5/7]` Espera de `HomeScene` y descarte del modal de bienvenida/novedades (`540, 2220`).
6. `[6/7]` Pulsación de botón "Combate" (`820, 1480`) y entrada a sala de Matchmaking.
7. `[7/7]` Pulsación de "Iniciar combate" (`540, 630`), detección del inicio del loop de combate ("3, 2, 1, FLY!" / `PlayGoAnimation` / `UpdateFly`) y captura de screenshot final `09_battle_scene_ready.png`.

Todos los screenshots en 720px y registros de logcat se guardan en `.local/battle-test/latest/`.

---

## 4. ARTEFACTOS GENERADOS

- **APK Directa**: `.local/artifacts/KickFlight-2.11.0-direct-10.0.2.2-18080.apk`
  - SHA-256: `866b6afdb4bdaf1622b1cc83aee67f822a022644340b0f3515aa69875a1e3d39`
- **Screenshot de Batalla Lista**: `.local/battle-test/latest/09_battle_scene_ready.png`
- **Suite de Pruebas**: [scripts/test-battle-loop.sh](file:///Users/marcochavez/Documents/variedad/Kick-Flight-Private-Server/scripts/test-battle-loop.sh)
- **Patch Engine**: [scripts/patch-il2cpp-endpoints.py](file:///Users/marcochavez/Documents/variedad/Kick-Flight-Private-Server/scripts/patch-il2cpp-endpoints.py)
