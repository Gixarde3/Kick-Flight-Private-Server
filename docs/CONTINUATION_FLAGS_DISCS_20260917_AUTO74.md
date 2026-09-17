META COMPLETA: Continúa el diagnóstico y la corrección basada en evidencia del servidor privado Kick-Flight en este computador. El usuario reporta discos que se activan y animan sin producir efectos, y banderas que aparentemente no se recogen ni aparecen en la espalda al tocarlas. Debes reproducir y seguir la cadena completa de discos (request, estado, proyectil/buff/HP/impacto apropiado) y de Vuelo de banderas (proximidad/colisión, pickup, propietario único, attach bilateral, entrega, puntuación y respawn), corregir únicamente causas demostradas y validar en dos clientes. Además, resultados, Aceptar, navegación y otra batalla dentro del mismo proceso deben sobrevivir. La prioridad inmediata y explícita es exclusivamente **Vuelo de banderas**; no volver a probar Cristalmanía como si validara banderas. No inventar reglas ni declarar éxito sólo por animación, cooldown, eventos enviados o PASS del harness. Al finalizar deja rutas de cambios y evidencias y un resumen breve de causa, corrección y pruebas, con sus limitaciones.

# Prompt de continuación — estado auto74, 17 de septiembre de 2026

## Alcance de este handoff

El usuario pidió preparar este prompt para otro agente en el mismo computador y **NO CORREGIR NADA durante su preparación**. Este turno sólo detuvo/consultó agentes, leyó estado y escribió este documento. No se ejecutaron nuevos comandos ADB, no se inició batalla, no se modificó código ni se construyó/instaló APK durante la preparación. Los cambios de código descritos más abajo son de turnos anteriores. No confundas lo pendiente con lo ya resuelto.

Repositorio: `C:\Users\Gixar\Documentos\Variedad\Kick-Flight-Private-Server`.
Shell: PowerShell; `login:false` ha funcionado. Windows, WSL Ubuntu mirrored.
Fecha del handoff: 2026-09-17, zona America/Mexico_City, UTC−6.

## Estado actual: empezar aquí

- **Auto74 terminó antes de preparar el handoff.** Ambos emuladores están en Home, pestaña Combate, tarjeta **Vuelo de banderas** seleccionada. El botón grande Combate **no se pulsó** en auto74.
- Últimas capturas verificadas por Sol: `.local/gameplay-evidence/automated/v33-flags-before-battle-auto74/final-home-emulator-5554-720.png` y `final-home-emulator-5556-720.png`, tomadas aproximadamente 09:58:21 local. Ambas muestran la tarjeta correcta.
- Últimos PIDs Android reportados: `emulator-5554=4702`, `emulator-5556=5081`. Fueron preservados desde auto71; no force-stop, launcher, reinicio ni cacheclear en auto73/74. Revalida el estado vivo mediante un turno Luna antes de actuar; estos son últimos valores observados, no garantía indefinida.
- APK instalada: **v33**, descrita abajo. Datos y caché intactos.
- El agente `flags_before_battle` ya había completado su paquete al pedir detenerlo. No queda ningún operador ADB autorizado ejecutando otro paquete; los anteriores agentes fueron interrumpidos o terminaron. No reutilices a ciegas tareas antiguas pendientes.
- `.local/adb-loop-notes.md` fue compactado por Luna a ocho líneas con el estado auto74. **Releerlo en cada turno ADB.** No contiene todo el histórico; este prompt lo complementa.
- Auto74 evidencias: `actions.txt`, `final-delta-emulator-5554.txt`, `final-delta-emulator-5556.txt`, capturas iniciales/Result/Home/modal/finales. Se reportó ausencia de SIGSEGV/SIGABRT/FATAL/ANR en el delta final. Esto no valida pickup ni entrega.

## Correcciones del usuario: instrucciones persistentes

1. «Para avanzar solo debes dar click en cualquier punto de la pantalla». El tap en un punto libre `raw(540,1200)` ya demostró avance XZ bilateral. **No usar hold/flick/drag inferidos para iniciar el avance.** La forma de detener y dirigir el vuelo aún no se verificó; se preguntó mediante una pregunta opcional asíncrona, sin respuesta registrada. No inventar ese control ni confundir un gesto de cámara con desplazamiento.
2. «You're testing wrongly. You're playing Cristalmanía, el modo que nos debemos enfocar ahora es Vuelo de banderas». **Auto70 y auto71 fueron rule1 Cristalmanía; quedan excluidos de la validación de banderas.** Sólo sirven como evidencia de control/activación de discos en ese modo.
3. «Antes de entrar a batalla, cambia el modo usando el boton negro en la esquina». Usa el **botón negro en la esquina de la tarjeta Home** para seleccionar Vuelo de banderas en ambos, confirma con Aceptar, comprueba la tarjeta antes de Combate y la nueva entrada `rule=2` en backend antes de inputs de gameplay. No confiar en selección de otra sesión.

Coordenadas históricas verificadas (pantallas nativas 1080×1920; evidencia escalada 720×1280). Verificar UI actual antes de usarlas:

| Acción | Coordenada raw | Coordenada en imagen 720 |
| --- | --- | --- |
| Selector negro de reglas en tarjeta Home | 968,797 | aproximadamente 645,531 |
| Fila Vuelo de banderas en modal | 540,945 | 360,630 |
| Aceptar modal de reglas | 540,1388 | 360,925 |
| Botón grande Combate de Home | 820,1240 | aproximadamente 547,827 |
| Pestaña inferior Combate | 540,1810 | 360,1207 |
| ResultScene Aceptar | 540,1812 | 360,1208 |
| Aceptar popup bonus de nivel | 540,1269 | 360,846 |
| Volver a Inicio tras bonus | 432,1812 | 288,1208 |
| Tap para avanzar en GameScene | 540,1200 | 360,800 |
| Swipe slot2 Geckosaurus usado en probes | 310,1740 → 310,1380, 400 ms | — |

Las flechas laterales Home (`raw1040,715`, etc.) cambian combate normal/ranking, **NO la regla**. No son el selector requerido. El modal mostraba «Faltan 23h» en Flags, pero la fila sí se pudo seleccionar y el backend aceptó rule2: no asumir bloqueo sólo por ese texto.

Primer tutorial Flags: cuatro páginas, título correcto pero contenido blanco; Next `raw980,990` en las primeras tres, última página cerrar `raw540,1785`. Confirmar dots/layout por captura antes de cada acción. Auto73 lo completó; no asumir que reaparecerá. En auto74 no se inició combate.

## Contrato operativo obligatorio

- Sol en hilo primario: planificación, arquitectura, decisiones ambiguas, resolución de conflictos, verificación y síntesis final.
- **Cada turno del loop ADB: subagente Luna, razonamiento `max`.** El primario no ejecuta ADB. Hay autorización explícita del usuario/AGENTS.md para esta delegación. Se pueden usar subagentes nuevos con contexto mínimo y estado en disco.
- Leer `AGENTS.md`, `docs/ADB_LOOP.md` y `.local/adb-loop-notes.md`. Cada iteración: captura → escalar a aproximadamente720px de ancho → delta relevante logcat → decisión con criterio explícito → una acción → comprobar/anotar. No enviar imágenes nativas.
- Dos fallos consecutivos contra el mismo criterio explícito: escalar a Sol con resumen breve, no historial. No repetir sin límite ni declarar éxito por el harness.
- Un solo operador ADB a la vez. Comprobar que no quede subrunner/exec viejo antes de reemplazar un agente. Interrumpir un agente no garantiza que un comando externo ya iniciado desaparezca.
- Techo contexto250000, compactar antes240000; preservar system y primeros turnos fijos, podar sólo cola mutable. Notas breves actuales en disco, evidencia cruda fuera del prompt.
- Los paquetes largos de deliberación agotaron el reloj de batalla varias veces. Preparar pruebas acotadas/atómicas desde HUD real; no gastar minutos interpretando entre acciones cuando hay un timer de tres minutos. No reportar pickup si nunca se llegó a la bandera.
- Una tarea de orientación enviada a `flags_mode` terminó repitiendo observación Matching; **no se ejecutó ni se demostró calibración de orientación**. No asumir que followups viejos se cumplieron: verificar artefactos/comandos.

## Servicios y captura: dejar vivos, verificar antes de reiniciar

Última comprobación de host durante handoff, aproximadamente10:01 local: procesos backend, WSL Luxon y qemu seguían vivos; WSL escuchaba UDP5055/5056/5058/27000/27001/27002.

- Backend Direct, puerto18080: `.local/session-logs/kickflight-services.json`.
  - pwsh18852; dotnet14584.
  - `.local/session-logs/server-20260917-091126.out.log` y `.err.log`.
  - Arranque autorizado si hace falta: `scripts/start-logged-services.ps1 -Mode Direct -DirectClientHost '10.0.2.2' -HttpPort 18080`.
  - `/health/ready` dio200 a15:12:01UTC; primer calentamiento de29fixtures/2600resources tardó≈11s. HTTP readiness no prueba UDP.
- Luxon WSL Ubuntu mirrored: proceso host wsl15632. Comando:
  `wsl.exe -d Ubuntu --cd /mnt/c/Users/Gixar/Documentos/Variedad/Kick-Flight-Private-Server/submodules/luxonserver ./luxon_server`
  - Logs NUEVOS `.local/session-logs/luxon-wsl-mirrored-20260917-091133.out.log` y `.err.log`.
  - Nombres genéricos `luxon-wsl-mirrored.out.log/.err.log` corresponden a sesiones anteriores y no deben confundirse.
  - Si se lanza un helper con Start-Process, usar ventana oculta salvo emuladores visibles solicitados.
- Captura Photon NUEVA **todavía activa**: WSL tcpdump PID**377** confirmado mediante `pgrep -af tcpdump`. Tool session original45869 puede no estar disponible en otro hilo; no depender sólo de ese ID.
  - Archivo `.local/gameplay-evidence/diagnostic/discs-flags-v32/photon-tap-20260917.pcap`.
  - Último tamaño observado11713387bytes a10:01:37local; sigue creciendo.
  - `tcpdump -i any -U -s0 -w /mnt/c/Users/Gixar/Documentos/Variedad/Kick-Flight-Private-Server/.local/gameplay-evidence/diagnostic/discs-flags-v32/photon-tap-20260917.pcap 'udp and (port 5055 or port 5056 or port 5058 or portrange 27000-27002)'`.
  - Es captura SLL2. No sobrescribirla ni iniciar otra sobre el mismo archivo. Si necesitas detenerla al final, verificar PID/ruta y detener sólo ese tcpdump de forma normal; no matar Luxon/WSL en bloque.
- Emuladores visibles actuales qemu12524/14088; wrappers anteriores21780/10620. AVDs se iniciaron **read-only** mediante `restart-test-emulators.ps1 -Visible`, sin snapshots, gpu host, cores4. Instalar una APK en overlay no garantiza persistencia tras cerrar AVD; comprobar o reinstalar si reinicias.
- Docker está roto: **no hacer reset**. No encender `EnableExperimentalUnityAllocators` (v29crash).
- ADB absoluto: `.local/android-sdk/platform-tools/adb.exe`. `adb` no está garantizado en PATH.

## APKs y correcciones ya realizadas: no confundir candidatas con validación total

Actual instalada:
`.local/artifacts/KickFlight-2.11.0-direct-10.0.2.2-18080-v33-flag-score-null-guards.apk`
SHA256 `CFABF8C6D6F650E0AE0014C8CE2D931080510FF38712BA831F95FCEFBEEC87A5`.
Build/signature: `.local/v33-build.log`. Configuración `config/apk-direct-server.local.json`, host10.0.2.2:18080, ForceGameScene true, allocatorexperimental false. No existe una v34 instalada en este trabajo.

Anterior v32:
`.local/artifacts/KickFlight-2.11.0-direct-10.0.2.2-18080-v32-disc-targeting-guards.apk`
SHA256 `D43F7CDBAB30FD00E874984AC309F43CB41425CB2BB05A145D7B00F3D0287994`.

Baseline v31:
`.local/artifacts/KickFlight-2.11.0-direct-10.0.2.2-18080-v31-result-direct-begin-freefix.apk`
SHA256 `E370C9BF47CE24EC150CEF008BC2DC865891A77C6A2192660D9C760E8BE39383`.
Auto59/60 2PASS GameScene/resultadosDRAW, cuatro personajes animados, sin T-pose/Scudo/SIGABRT/SIGSEGV/ANR en esas pruebas. Originalmente no se había probado Aceptar/rebatalla.

Patches preservados de v31:
- `scripts/patch-il2cpp-endpoints.py`: ResultScene PreBegin0x18B18C4 RegisterManagerAsync → BeginAsync0x189F808.
- Predicado real de assets restaurado0x18A4924, eliminado `warmup60updates`.
- libunity free0x614C00 → NOP para evitar `Scudo native_bridge_free`; leak pequeño deliberado. La causa de heap se infirió, no quedó completamente demostrada.

v32 targeting:
- v18/v31 anulaban **todo** `PlayerStateSkill.UpdateActionTargeting`0x17F31FC (`mov w0,0;ret`), eliminando targeting válido y transiciones Ready/Cancel además de evitar NRE.
- Se restauró el cuerpo original y sólo tres rutas nulas saltan al epílogo existente0x17F32C4, conservando GetPlayerActionInfo:
  -0x17F3214 expected `740000b5e0031faaf483e897` → `940500b41f2003d51f2003d5`.
  -0x17F3260 expected `750000b5e0031faae183e897` → `350300b41f2003d51f2003d5`.
  -0x17F327C expected `550000b5db83e897` → `550200b41f2003d5`.
- No cave ni anulación de mascota para este cambio. Proyectil real observado, pero no se ha demostrado daño/slow bilateral ni resuelto todo el reporte de discos.

v33 flags personal score:
- Manifest backend omite `BattleRuleFlagFlightScore`; GetScore original lanza NRE por frame y en BattleEnd/CreateResultInfo, cortando progreso. Auto64 mostró6132/6258 errores GetScoreNRE, incluyendo7/900 desde BattleEnd.
- Guardas de excepción devuelven **puntuación personal neutral0** cuando falta master; fórmula válida original intacta. No se tocaron goals/pickup/respawn ni se inventaron filas/pesos.
  -0x15F24D8 `e0031faa4487f097` → `e0031f2aa2000014`.
  -0x15F2518 `e0031faa3487f097` → `e0031f2a92000014`.
  -0x15F27B0 `8f86f097` → `edffff17`.
- Rutas hacia epílogo0x15F2764 verificadas con Capstone. V32/v33 sólo14bytes distintos en esos tres sitios; libunity idéntica.
- GetScoreNRE pasó a0 en auto65. **No significa restaurar bonos personales originales** ni validar scoring/entrega de flags.

Build disponible: `scripts/build-direct-apk.ps1 -OutputPath '...'`. Consultar parámetros antes de ejecutar. No construir de nuevo sin un cambio sustentado y necesario.

## Scripts: estado y trampas importantes

`scripts/run-gameplay-probes.ps1` está modificado y contiene:
- `-FlightDiagnostic`: espera HUD real, tap libre ambos, captures paired+1s/+5s. PASS sólo inputs/vida del harness.
- `-DiscImpactDiagnostic`: tap en ambos, espera2700ms, swipe Gecko slot2 raw3101740→3101380 400ms por cliente, capturas inmediatas/+2s. Auto71 probó esto en rule1, HP sin cambio.
- **`-ExpectedBattleRuleId 2`** agregado antes de este handoff: lee `entry/server-stdout.txt`, exige registros nuevos de dos usuarios y RuleId esperado antes de gameplay. Falta evidencia o modo distinto → aborta. Default0 desactiva el check. **Verifica; no selecciona modo.** Validación offline rechazó logs rule1 reales auto71 y aceptó dos líneas rule2 reales extraídas de sesión16; fixture `.local/gameplay-evidence/diagnostic/discs-flags-v32/rule-gate-flags-evidence/server-stdout.txt`. Parse PowerShell OK.
- Detector de HUD real por HP verde (rawx600..1050,y1800..1890); un marcador GameScene puede aparecer antes de HUD mientras está Cargando.
- Rama normal histórica todavía contiene swipes antiguos; no usarla como control confirmado para iniciar avance.

**ADVERTENCIA OPERATIVA CONCRETA:** `scripts/run-battle-entry.ps1` hace force-stop/launcher en su rama launch **incluso con SkipInstall y sin RestartEmulators**. `run-gameplay-probes.ps1` lo invoca. Por eso no usar esos runners sin revisar si se pretende conservar PIDs y demostrar repetición dentro del mismo proceso. Auto73/74 fueron navegación manual Luna y sí conservaron4702/5081. `LaunchStaggerSeconds45` ayudó entrada en sesiones previas; no obliga a relanzar la sesión actual.

Consultar param antes de cualquier invocación, escribir comandos con espacios correctos. Preservar caché/datos: `ResetAppData false`, `SeedAssetCache false` salvo necesidad sustentada. El ejemplo antiguo de automatización con restart/install no es próximo paso apropiado para los procesos vivos actuales.

## Evidencia y cronología relevante

Todas las rutas son relativas al repo; conservar capturas de720px y logs completos.

- Auto61 v31: cooldown/animación, prueba tardía inconclusa, sin objetivo controlado. No prueba ausencia general de efectos.
- Auto62 v32: paquetes de targeting en `.local/gameplay-evidence/automated/`. Actor mostró Geckosaurus/proyectil verde real y ReceiveAddBullet bilateral a19:20:40.980898UTC. Observer en base opuesta, HP11656, sin impacto. Otro tiro también generó proyectil. ResultDRAW en ambos y reentradaHUD observada, pero sin prueba explícita de PIDs constantes.
- Auto63: el harness relanzó apps; no prueba repetición en el mismo proceso.
- `.local/gameplay-evidence/automated/v32-flags-auto64`: primera entrada real rule2, battle789585934 a04:01:30UTC, HUDFlags bilateral. Flick tardío sin acercamiento demostrable. GetScoreNRE masivo. Bloqueo posterior Cargando5554/bonus5556 con PIDs6305/6249; dos fallos Home/Result y recuperación force-stop autorizada. Logs porPID y evidencias de bloqueo allí. No atribuir pickup a TitleView/AIGetSkillCategoryNRE.
- Auto65 v33: rule2, battle789585935, GetScoreNRE0, backend end/result200; 5556DRAW, 5554Cargando. Flick tardío; no prueba movimiento/pickup.
- Auto66: entrada5556 falló por timeout150s; 5554 lanzó `SceneManager.SetActiveScene FLD00101 is not loaded` desde LoadFieldAsync. La misma excepción en auto65 precedió a HUD posterior, así que no demuestra por sí sola una causa fatal. No hubo inputs de diagnóstico.
- Auto67: HUDFlags bilateral, pero gestos sólo elevaronY≈6 y XZ quedó casi inmóvil; no recogida. Antecedente del error de control corregido por el usuario.
- Auto69: primer boot falló150s; segundo intento auto70 arrancó AVDs visibles. No resetDocker.
- `.local/gameplay-evidence/automated/v33-flags-tap-auto70`: **rule1**, battle789658345; v33 instalada sin reset. Tap09:21:06local=15:21:06UTC comprobó avanceXZ en ambos: z±90→±54→±20→centro→base opuesta, aproximadamente35unidades/s. No Flags ni pickup. Una nota antigua puso09:21Z incorrectamente: usar UTC15:21.
- `.local/gameplay-evidence/automated/v33-disc-impact-auto71`: **rule1**, battle789658346, PIDs4702/5081. Tap15:27:50.266/.340UTC; swipes15:27:53.553/54.039. Mascotas/cooldown28/27 y RPC de proyectil/SyncEffect en ambos, HP11656 antes/después. Distancia inferior a40 no garantiza orientación, lock-on ni trayectoria libre alrededor del pilar. Daño/slow NO probados; primer fallo de ese criterio. `probe-summary.json` PASS significa harness completo, no impacto.
- `.local/gameplay-evidence/automated/v33-flags-select-auto73`: mismos PIDs4702/5081. ResultDRAW→Aceptar→bonus→Volver a Inicio→Home; botón negro→Flags; tutorial de cuatro páginas; backend **15:46:11UTC rule2 para ambos**, battle**789658347**, Stage3 a15:46:14. HUDFlags bilateral timer2:00/1:58, luego0:27/0:25. Sin movimiento/pickup demostrado. `flags-matching-*` fue sobrescrito en la observación posterior: no asumir timer inicial en el archivo actual. Calibración solicitada NO ejecutada.
- `.local/gameplay-evidence/automated/v33-flags-before-battle-auto74`: ResultDRAW bilateral de esa partida Flags, Aceptar15:53:15UTC, Volver a Inicio15:55:32, Home; pestaña Combate15:56:29; selector negro15:56:53; fila Flags15:57:18; Aceptar modal15:58:16; HomeFlags final en ambos09:58:21local. Mismos PIDs, ninguna batalla nueva. Es la evidencia actual más importante.

Esto sustenta navegación/resultados/reentrada entre Cristalmanía y Flags dentro de los procesos4702/5081 en esa sesión. **No cumple toda la aceptación**: pickup/attach/entrega/score/respawn y efectos apropiados siguen sin probar.

## Reglas y RE ya verificadas: guiar diagnóstico, no reemplazar prueba runtime

Herramientas: Python, Capstone, pyelftools, GOT/RELA. Dumper `.local/tools/Il2CppDumper-direct-validation/{script.json,dump.cs,il2cpp.h}`; binario original `.local/re/lib/arm64-v8a/libil2cpp.so`. `scripts/re/a64dis.py --all` sigue tras returns internos. Recursos extraídos con UnityPy de aed_001/aed_master; árboles y desensamblados en `.local/gameplay-evidence/diagnostic/discs-flags-v32/`.

Discos actuales, nivel10:

- 3010001 Leorex, skill10001, MoveAttack tipo3: no asumir curación.
- 3010002 Geckosaurus, skill10002, ShotAttack tipo1: daño medio a enemigo frontal y ralentización5s según descripción verificada.
- 3010003 Bombster, skill10003, ShotAttack tipo1; 3010004 RedBlaster, skill10004, ShotAttack tipo1.
- Gecko bullet101: alcance40, velocidad50, homing100; collision169 esfera radio0.75, hitLayer4864; hit177 knockback effect2. Referencias existentes en catálogo/disco no prueban carga runtime. Mascota y proyectil del actor sí observados.

Flags:

- Datos de campo `Field00101_2`/`ITE00101_2`: spawnBlue(0,6.6,-91) yaw0, Red(0,6.6,91) yaw180.
- BanderaBlue0(70,18,26), Red1(-70,18,-26), elevadas y laterales. No están en el centro ni en spawn contrario.
- Zonas goalBlue(-71.3,15,26.5), Red(71.3,15,-26.5), radio4XZ. No asumir entrega en posición spawn±91.
- ItemManager.UpdateCheckOwnership nativo: radio6.5 (sqr42.25), enabled, IsMine, no muerto/disabled, sin bandera, sin estados6/7/9/10/14/condition25; filtros de equipo/inicial y nearest. La ruta permite bandera propia y filtra enemiga en posición inicial.
- SetOwnerToPlayer0x1517350 → propiedad índice3 OwnerObjectId, CAS expected0, RoomItemState2/substate3, RoomSetCustomProperties.
- **Propiedades runtime de FLAGS son `Crystal0.*` y `Crystal1.*`**, no necesariamente `FlagN.*`: `.1type2`, `.2team0/1`, `.3owner0` inicial, `.4vector posición`, `.10visibletrue`, `.8index0/1`.
- Player.UpdateFlagBattle0x13E1E08 → FlagCarriedPlayer.SetVisible0x15F09A0. Initialize0x15F0620 parenta al transform propio y llama InstantiateFlagModel original. Comprobar propietario/attach bilateral y que no se adjunte a dos personajes.
- IsFlagStand0x17E19F8: item transportado del mismo equipo del jugador, IsInGoalArea con ownteam. Seguir estas reglas nativas; no inventar CTF convencional de recoger bandera enemiga. El usuario describió entrega enemiga; resolver la nomenclatura con reglas reales verificadas.
- FlagStandEvent0x17D87BC → FlagGoalRequest0x1515540 → SetRespawnWaitFlag0x151B040; goals<3 en ambos, roomstate<=6, evento con gate único. EX_TIME90, MAXflags2, flagAmount3 goals para victoria.
- Luxon CAS operación252/GameFlags35 soporta expectedvalues y broadcast; no hay evidencia de falloC++ ni se hizo cambioC++. No inyectar CAS ni pickup simulado como prueba de colisión.
- BattleEnd0x156F0E4 llama CreateResultInfo0x1573828 antes de UpdateRoomState; el throw de GetScore cortaba progreso.
- InputFly0x17E1FE4 distingue Swipe/Flick/LookAround; CanStayLookAround0x17E6D78 en reposo devuelve true. Swipes pueden sólo cambiar cámara. InputActionAdvance0x17E936C, InputActionBrake0x17E7C78, InputActionLookAround0x17E9BD8 disponibles para RE; controles stop/steer aún no demostrados.
- GetDisplayAngles0x13BC3A8 stubzero y SetDisplayAngles0x13BC314RET son guards históricos. Revisarlos si evidencia apunta a orientación; no se atribuyó falta de impacto/pickup a ellos.

## Parches de diagnóstico peligrosos y prototipo rechazado

- **NO activar `KF_DIAG`/`KF_RESULT_DIAG` tal como están**: loggerRegionE vive en LoadDeckSummonModel y lo anula, rompiendo mascotas/discos.
- `KF_UNLOAD_BYPASS` puede introducir races load/unload; no usar a ciegas.
- Prototipo result-safe-trace rechazado estáticamente: el supuesto cuerpo muerto de GetMenuType contiene **cave de producción0x1570EF8**, llamada desde0x17630EC CompleteGameReady. No sobrescribirla. Nunca se construyó/instaló ese tracer.
- Helper movido a `.local/gameplay-evidence/diagnostic/discs-flags-v32/result-trace-rejected-prototype.py`; integración productiva eliminada. No hay `KF_RESULT_SAFE_DIAG` en producción. No reutilizar el prototipo.
- Rangos estudiados, no garantía automática para caves: SetDisplayAngles dead0x13BC318..0x13BC3A8=144; BeginAsync b1 dead0x1579948..0x157999C=84, b3 dead0x1579A40..0x1579AC8=136, b4 dead0x1579AD0..0x1579B80=176. GetDisplayAngles y b2/b5/b6 son rutas vivas. __android_log_print PLT0x10D6270; UnityDebug provocó unwind/crash en otros ensayos. Validar todas las referencias antes de decidir.
- Warnings Animator InvalidLayerIndex−1, TitleViewNRE y errores AIGetSkillCategory observados pueden ser no fatales; no asumirlo para cualquier stack nuevo ni usarlos como causa sin seguir la cadena.
- Falso positivo pendiente PhotonServerManager.PingUdpOrTcpPortAsync: convierte10.0.2.2 a127.0.0.1, timeoutTCP, UDP Send de cuatro ceros devuelve true sin reply. Healthready o ese check no prueban Luxon. Verificación independiente UDP mediante ss/logs/captura. No priorizar ese arreglo sin relación con el objetivo principal.

## Decodificación de red y posiciones

`scripts/re/read-photon-pcap.py`: ENet/PhotonProtocol18, reensambla fragments, errores explícitos por cifrado/tipos no soportados; `--rpc-list` usa71 nombres de Photonsettings. No inferir ausencia desde mensajes no decodificables. `scripts/re/read-transform-sync.py`: eventkind4/code201, params245 observables, requiere **viewIDs explícitos**; sólo primer buffer custom66 de jugador ya identificado. No todos los custom66 son transforms.

Prefijo transform verificado en nativo: ReadMask0x18DE700 usa UshortLE para maskoffset, byte para masklength y maskLSB; GetNext2 en0x18DE918; ReadFloat0x18DEF70 tipos0=0,1=1,2=floatmax sentinel,3=rawfloatLE; Serialize0x18E0F78 enabled bit0 yXYZ bits1..6. El parser deja campos posteriores opacos. View4/5 mostraron posiciones de jugadores, pero mapear player/actor/team en cada nueva partida; no asumir que view4 corresponde siempre al mismo cliente. Floatmax sentinel no es posición real.

Ejemplos PowerShell para refrescar snapshots de captura activa (read-only, noADB):

```powershell
python scripts/re/read-photon-pcap.py .local/gameplay-evidence/diagnostic/discs-flags-v32/photon-tap-20260917.pcap --rpc-list .local/gameplay-evidence/diagnostic/discs-flags-v32/photon-settings.json > .local/gameplay-evidence/diagnostic/discs-flags-v32/photon-tap-20260917.jsonl
python scripts/re/read-transform-sync.py .local/gameplay-evidence/diagnostic/discs-flags-v32/photon-tap-20260917.jsonl --views 4 5 > .local/gameplay-evidence/diagnostic/discs-flags-v32/positions-tap-views4-5.jsonl
```

También hay captura antigua `photon.pcap`, `positions-views4-5.jsonl`, logsRE de transform/buffers/flageligibility/goals. No mezclar hora local/UTC; PowerShell ConvertFromJson puede deserializar fechas y formatearlas localmente.

## Preservar el worktree sucio

No `git reset --hard`, no `git checkout --`, no limpiar usuarios ni submódulo. No stage/commit incidental.

Último gitstatus durante handoff: `MM scripts/patch-il2cpp-endpoints.py`, pyc de patchPython modificado, `scripts/re/a64dis.py`, `scripts/run-gameplay-probes.ps1`, `src/KickFlight.BootstrapApi/data/users/1000003.json`, submódulo Luxon modificado; docs y parsers untracked; muchos usuarios1000006/7/9/10 yUUID untracked. Son estado existente, no basura autorizada. Luxon tuvo índice interno extraño (D/untracked) en revisiones anteriores; preservar. Backup histórico de notas `.local/adb-loop-notes-history-20260916-pre-v32.md`, SHA256 `0e9558921281b3d83a8144160ac6a52f554089c5ace76905b0609d3ab72e93d0`.

Documentación complementaria `docs/DISCS_FLAGS_V32_DIAGNOSTIC.md` tiene cambiosv32/v33 y evidencias, aunque parte del texto inicial es anterior alauto74. `docs/CONTINUATION_DISCS_FLAG_FLIGHT.md` es handoff viejo basado en v31; **este prompt/estadoauto74 prevalecen**.

## Próximo trabajo y aceptación pendiente

1. Leer contrato/notas, comprobar estados mediante Luna. Mantener PIDs/caché vivos si es posible. Confirmar selección con botón negro antes de Combate en AMBOS y entrada NUEVA rule2 (la entrada15:46 pertenece a la partida ya finalizada; no sirve para una batalla nueva).
2. Preparar prueba Flags desde HUD real y recursos reales, con observador y logs/captura en marcha. Verificar controles/orientación y acercamiento XZ/Y a la bandera propia. Demostrar distancia dentro de6.5 y elegibilidad antes de atribuir falta de pickup al backend/patch.
3. Seguir pickup→CASowner→estado→attach en ambos; nunca adjuntar a dos personajes. Sólo entonces entrega en goal verificado→goals/score→respawn. Comparar roomprops y visuales de ambos.
4. Corregir sólo causalidad reproducida; validar dos clientes y repetición. No inventar pesos master para esconder recursos faltantes. La puntuación personal0 de v33 sigue siendo una limitación.
5. Discos siguen en la meta completa, pero **no desviarse ahora a Cristalmanía**. Cuando corresponda, probar efecto real apropiado y objetivo controlado en ambos, no cooldown/mascota únicamente. Aceptación: HP/buff/proyectil real adecuado, cadena request/state/effect e impacto según tipo; no afirmar daño Gecko sin prueba.
6. Resultados/navegación/rebatalla en el mismo proceso y sin crash; registrar PIDs y no usar un harness que hace force-stop como prueba de continuidad.

Pendientes: bandera en la espalda de un único portador visible bilateralmente, owner/state coherentes, entrega/puntuación/respawn conforme a reglas reales y efectos de discos validados adecuadamente. No hay causa demostrada del reporte de pickup ni de ausencia de impacto. La meta no está completa.
