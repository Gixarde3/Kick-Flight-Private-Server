# Prompt de continuación — discos y modo Vuelo de banderas

Continúa el trabajo en `C:\Users\Gixar\Documentos\Variedad\Kick-Flight-Private-Server`.

## Reporte pendiente de verificar

El usuario reporta que los discos se activan e inician su animación, pero no producen efectos. En el modo **Vuelo de banderas**, tocar la bandera aparentemente no la recoge ni la coloca en la espalda; la entrega en la base enemiga todavía no ha sido probada. No asumas la causa: diagnostica ambos problemas con evidencia reproducible y corrígelos.

## Contexto confirmado

- APK final: `.local/artifacts/KickFlight-2.11.0-direct-10.0.2.2-18080-v31-result-direct-begin-freefix.apk`
- SHA-256: `E370C9BF47CE24EC150CEF008BC2DC865891A77C6A2192660D9C760E8BE39383`
- Evidencia 2PASS `auto59/60`: `.local/gameplay-evidence/automated/v31-result-direct-begin-freefix-auto59` y `auto60`, clientes `emulator-5554/5556`, GameScene HUD y resultados DRAW.
- Las estadísticas muestran 4 personajes animados, sin T-pose, loading, Scudo, SIGABRT, SIGSEGV ni ANR. No se probó pulsar **Aceptar** ni comenzar otra batalla dentro del mismo proceso.
- `scripts/patch-il2cpp-endpoints.py`: ResultScene PreBegin `0x18B18C4 RegisterManagerAsync -> BeginAsync 0x189F808`; predicado real de assets restaurado en `0x18A4924`, eliminando `warmup60updates`; `libunity` free `0x614C00 -> NOP` para evitar `Scudo native_bridge_free` (leak pequeño deliberado; causa de heap inferida).
- Warnings `Animator Invalid Layer Index -1`/NRE considerados no fatales. No activar `EnableExperimentalUnityAllocators` (v29crash).
- Backend: `scripts/start-logged-services.ps1 -Mode Direct -DirectClientHost '10.0.2.2' -HttpPort 18080`.
- Luxon WSL Ubuntu mirrored: `wsl.exe -d Ubuntu --cd /mnt/c/Users/Gixar/Documentos/Variedad/Kick-Flight-Private-Server/submodules/luxonserver ./luxon_server`; logs en `.local/session-logs/luxon-wsl-mirrored.out.log` y `.err.log`.
- Docker está roto: no hacer reset.
- Build: `scripts/build-direct-apk.ps1 -OutputPath '...'`, configuración `config/apk-direct-server.local.json`.
- Automatización: `scripts/run-gameplay-probes.ps1 -ApkPath '...' -RunId 'nuevo' -InstallApk $true -ObserveSeconds 210 -RestartEmulators $true -VisibleEmulators $true -ResetAppData $false -SeedAssetCache $false`; después repetir con `-RestartEmulators $false`. `run-battle-entry.ps1` es subrunner.
- Consultar parámetros antes de ejecutar; escribir los comandos con espacios correctos. Evidencias: logs y screenshots de 720 px.

## Reglas operativas

- El razonamiento, las decisiones ambiguas, la verificación y la síntesis final corresponden al agente Sol; cada turno del loop ADB corresponde a un subagente Luna con razonamiento `max`.
- Releer `.local/adb-loop-notes.md` en cada turno ADB y seguir `docs/ADB_LOOP.md`; escalar después de dos fallos consecutivos contra un criterio explícito.
- Preservar el worktree sucio: patch Python modificado, script de gameplay modificado, archivos de usuarios y submódulo. No usar `git reset --hard` ni `git checkout --`.
- Reverse disponible en `.local/tools/Il2CppDumper-direct-validation/{script.json,dump.cs,il2cpp.h}`; binario en `.local/re/lib/arm64-v8a/libil2cpp.so`; están disponibles Capstone, pyelftools y Python, además de GOT/RELA.
- Hay un falso positivo pendiente: `UDP PhotonServerManager.PingUdpOrTcpPortAsync`.

## Plan de diagnóstico y corrección

1. Revisar patches que puedan cortar discos, animaciones, efectos, eventos o servidores Luxon, sin asumir que alguno sea la causa.
2. Establecer baseline de discos con los recursos objetivo y un observador; seguir la cadena request/state/efecto y comparar contra regresiones.
3. Para banderas, seguir colisión, pickup, propietario, evento de attach y entrega, conforme a las reglas reales del juego; no inventar reglas.
4. Corregir únicamente con evidencia. Repetir en dos clientes y conservar logs/screenshots que demuestren cada transición.

## Criterios de aceptación

- Dos clientes muestran efectos reales de discos adecuados (por ejemplo HP, buff o proyectil, según el tipo verificado), no sólo activación o animación.
- Tras pickup, la bandera aparece en la espalda del personaje portador y ambos clientes observan el mismo propietario y estado; no debe adjuntarse a los dos personajes.
- La entrega y la puntuación ocurren conforme a las reglas verificadas, con respawn correcto.
- Repetir la prueba no rompe resultados, navegación posterior ni el proceso.

Al finalizar, deja la ruta de los cambios/evidencias y un resumen breve de causa, corrección y pruebas realizadas.
