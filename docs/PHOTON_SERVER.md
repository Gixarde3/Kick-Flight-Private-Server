# Servidor Photon (LuxonServer) para partidas de 2 a 8 jugadores

Las partidas con varios humanos necesitan un servidor compatible con Photon: tras `/battle/start` el cliente entra a la
sala `battle-NNN` por Photon (NameServer 5058 -> MasterServer 5055 -> GameServer 5056, UDP). Los bots los sigue
poniendo nuestro API (`BattleMatchmakingService.BuildRoster`).

## Despliegue actual (2026-09-21)

* Host: `51.79.241.70` (Ubuntu 24.04), servicio `luxon-server.service` (systemd, `Restart=always`).
* Binario: `/opt/luxon-server/luxon_server`, config `/opt/luxon-server/config.yml` (= `config.yml` del fork con
  `external_address: 51.79.241.70:<puerto>`). Fuente en `~/kickflight/luxonserver` (fork `Gixarde3/luxonserver`
  @ `a84ecc3` + `scripts/luxonserver/000{1..5}-*.patch` aplicados con `git am` en el fork, y `0006`/`0007-*.patch` aplicados dentro del
  submodulo `Luxon/` del fork). En la VM, `0008-*.patch`, `0009-*.patch` y `0010-*.patch` quedaron aplicados en el
  árbol de trabajo sin commit (observado el 2026-09-21); el diff exportado se verificó contra el servidor con
  `git apply --check -R`.
* Estado del fork y del puntero del submodulo, comprobado el 2026-09-22 en este repo: `0001`-`0005` y `0008` ya son
  commits del fork (`1e9f1e4`, `e093b87`, `1bc49a1`, `4320af8`, `d85e14b`, `f0a50b8`), y `f0a50b8` es el puntero que
  fija este repo; `0009` está aplicado sólo en el árbol de trabajo del submodulo (`src/authentication.cpp`, sin
  commit) y `0010` no está aplicado. Un despliegue nuevo no depende del pin: aplica los diez parches de
  `scripts/luxonserver/` con `git am` (ver [RECREATE_FROM_SCRATCH.md](RECREATE_FROM_SCRATCH.md) §6).
* Recompilar y desplegar tras tocar el servidor: `ninja -C build` en `~/kickflight/luxonserver`, y después
  `sudo systemctl stop luxon-server && sudo cp build/luxon_server /opt/luxon-server/ && sudo systemctl start
  luxon-server`. El `cp` falla con "Text file busy" si el servicio sigue arriba. Copia de seguridad del binario
  anterior: `/opt/luxon-server/luxon_server.bak-pre0010`.
* Compilado con `g++-14` (el código usa C++23 "deducing this"; g++ 13 no compila):
  `cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DLUXON_SERVER_USE_SANMAKE=OFF -DCMAKE_C_COMPILER=gcc-14 -DCMAKE_CXX_COMPILER=g++-14 && ninja -C build`.
  Submodulos necesarios: `Luxon` y `tracy` (solo cabeceras).
* ufw: UDP+TCP 5055, 5056, 5058 y 27000-27002.
* Logs: `sudo journalctl -u luxon-server -f`.

## Ventana de emparejamiento normal (2026-09-21)

`/battle/entry` + el stream `openmatch.Frontend/GetAssignments` ya no emparejan exactamente a dos humanos: el primero
abre una **ventana de 20 s** en la que van entrando más humanos, y solo al cerrarse se rellenan con bots los huecos.
La prioridad es que los humanos jueguen juntos; los bots son el relleno, no el disparador.

* Cada humano que entra **alarga** la ventana: el 2º +5 s, el 3º +4.5 s, el 4º +4 s… (0.5 s menos cada vez; el 8º
  +2 s, total 44.5 s). Con 8 humanos (4 por equipo) la partida arranca sin esperar. Ajustable sin recompilar:
  `KF_MATCH_WINDOW_SECONDS` (20) y `KF_MATCH_JOIN_INCREMENT_SECONDS` (5).
* Mientras la ventana siga abierta, el 3º, 4º… jugador entran **en la sala del primero** (`_pendingRoom`), nunca en
  una sala nueva: una entrada no cierra la sala, solo la alarga. La ventana la cierra un `RunMatchWindowAsync` por
  sala que relee el deadline en cada vuelta (`Task.Delay` no se puede alargar).
* Etapas del stream con la ventana abierta: la Etapa 1 pasa a ser "los humanos que hay ya" (sin bots) y cada entrada
  se **retransmite** a los clientes que esperan para que vean llenarse las ranuras. La Etapa 2 (8 ranuras con bots) y
  la Etapa 3 (`Connection = battle-NNN`) llegan cuando la ventana se cierra, igual que antes.
* Replay: una asignación completada solo se repite si la sala está **finalizada** (`IsFinalized`). Con la ventana
  abierta el roster es parcial a propósito y `MatchingInfo` sigue vacío, así que un replay por "roster no vacío"
  repartiría un `Connection` antes de que la partida exista.
* Un stream que muere antes de que la sala arranque (salir de la pantalla de matching destruye `GetAssignments`)
  retira a ese humano; con el último se descarta la sala. `/battle/cancel` no llega a este servicio: es un stub, así
  que el fin del stream es la única señal de retirada.
* Equipos: los humanos alternan Azul/Rojo por orden canónico (`userId`), así que nunca se separan por más de uno, y
  los bots rellenan Azul hasta 4 y luego Rojo. Sale 4v4 con los humanos repartidos para cualquier número de humanos
  de 1 a 8 (espejo en `tests/test_teamtype.py`).

**Sin verificar (Photon)**: el tope de la sala es el `MaxPlayers` que manda el cliente que la crea
(`handler_gameserver.cpp:460-462`) y luxon solo lo aplica si `max_peers > 0` (su `MaxGamePeers` es 0). Ese literal no
aparece en este repo: si el cliente pide 2, el 3er humano recibiría `GameFull` y haría falta un parche luxon
(`0011-*`, todavía sin escribir) que lo suba a 8 en salas `battle-*`. Comprobar con 2 y luego 3 humanos.

**Sin verificar (cliente)**: el cliente despacha cualquier update con `Connection` vacío como `UpdatePlayers` y
refresca las ranuras, así que updates de más son inocuos; pero en este repo nunca se ha enviado un roster intermedio
de 2 a 7 entradas (siempre 1 y luego 8). Si la pantalla de matching se atasca con uno, el plan B es no retransmitir y
dejar a los que esperan con su roster de 1 entrada hasta la Etapa 2.

## Cliente

El literal `ns.exitgames.com` del APK se reemplaza por `--photon-host` / `KF_PHOTON_HOST` (por defecto el host del
`--base-url`). Los APK de sabor Photon se construyen con `KF_PHOTON=1 KF_PHOTON_HOST=51.79.241.70` y se sirven en
`/apk/photon-remote`, `/apk/photon-diag`, `/apk/photon-diag-remote` (`start-client-photon-diag.bat` para el emulador).
Sin `KF_PHOTON=1` el APK usa el puente offline (sala local con bots) y nunca toca Photon.

## Parche `0001-pending-battle-join.patch`

Los dos humanos reciben el id de sala en el Stage 3 a la vez; el segundo `JoinGame` llega al MasterServer antes de
que el creador haya entrado al GameServer (`is_created == false`) y `validate_join` respondía `GameIdNotExists`, que
el cliente trata como desconexion fatal ("Title Disconnect Error" en el jugador 2). El parche deja pasar ese caso para
ids `battle-*`; el handler del GameServer ya crea o une al llegar. Está en el fork (`1e9f1e4`) y el puntero del
submodulo de este repo ya lo incluye.

## Parche `0003-expected-users-join-closed-battle-room.patch`

El cliente maestro cierra la sala (`IsOpen=false`) unos ~100 ms despues de crearla; si el otro humano llega al
GameServer despues de eso, `validate_join` respondia `GameClosed` (32764) y ese jugador (el mas lento, al azar) recibia
"Title Disconnect Error". Ambos humanos entran por el MasterServer y estan en `expected_users`, asi que para ids
`battle-*` la reserva vale aunque la sala ya este cerrada. `0002` solo agrega el log de por que se rechaza un join
(`journalctl -u luxon-server | grep rejected`).

## Parche `0005-replay-room-properties-to-late-joiner.patch`

El maestro escribe las propiedades de sala (estado de batalla) ~40 ms despues de entrar; si el `JoinGame` del otro
humano llega despues, esas propiedades solo viajan en la respuesta del join y el cliente (que sale de MatchingScene
con `CallbackRoomPropertiesUpdate`, es decir con el *evento* PropertiesUpdate) se queda en el lobby. El servidor
reenvia ahora las propiedades actuales a quien entra segundo en una sala `battle-*` como evento, justo despues de
la respuesta del join. `0004` solo registra cada operacion (op code) que manda cada peer del GameServer.

## Parche `0006-luxon-enet-receive-window-4096.patch` (submodulo `Luxon/`)

La reimplementacion ENet de Luxon tenia una ventana de recepcion fiable de 128 secuencias por canal (ENet real usa
4096). Con 8 kickers sincronizados por el maestro, un paquete fiable atrasado desbordaba la ventana en pocos frames,
el servidor tiraba paquetes fiables (`[ENet] Receive window incoming_reliable is too small!`) y el cliente acababa
desconectado: todos los kickers desaparecian y el reloj se paraba (2026-09-21). Ventanas ahora 4096 / 1024 / 256.

## Parche `0007-luxon-enet-resend-tolerance.patch` (submodulo `Luxon/`)

`Client is now stale` en Luxon significa que un comando fiable enviado por el servidor no fue confirmado tras
`max_resends` reintentos o `disconnect_timeout_ms`. Con los valores de Luxon (7 / 10 s) una rafaga de perdida solo en
sentido servidor->cliente bastaba para expulsar al maestro (el emulador seguia vivo y confirmado hasta ese instante,
2026-09-21). Ahora 32 reintentos / 30 s (valores de ENet); el cliente Photon conserva su propio timeout de 10 s.

## Parche `0008-luxon-enet-disconnect-timeout.patch`

`ServerManager::setup()` construye su `EnetPeerConfig` a mano y fijaba `cfg.disconnect_timeout_ms = 5000`, con lo que
anulaba en silencio el valor de cabecera (30000) que subió `0007`: para el timeout de desconexión, `0007` era código
muerto y el valor real seguía siendo 5 s. Cualquier peer con un comando fiable sin confirmar durante 5 s era declarado
`Stale` y expulsado (`disconnect(true)`), y eso es lo que sacaba de la partida a clientes vivos durante cortes breves:
medido en partida, el peer del emulador quedaba `Stale` ~5 s después del último comando confirmado, no a los 30 s que
se creían vigentes. `server_manager.cpp` usa ahora 30000, igual que la cabecera.

Consecuencia práctica (2026-09-21): un corte de red de menos de ~10 s ya no expulsa a nadie por parte del servidor
(el servidor aguanta 30 s). A partir de ahí el que se desconecta es el propio cliente Photon con su timeout, y desde
ese momento la partida depende de que la reconexión del cliente funcione: ver el parche
"skip AnalysisManager.SendGameReconnectBegin" en `scripts/patch-il2cpp-endpoints.py`, que evita que el
`NullReferenceException` de un `GameManager._reconnectInfo` nulo aborte `GameManager.CallbackDisconnected` antes de
`ReconnectAsync` (dejaba la partida congelada para siempre).

## Parche `0009-luxon-token-takeover.patch`

Mientras un cliente está conectado, sus datos persistentes viven solo en `Peer::persistent` y no en el pool, así que
un cliente que reconecta con el token que se le entregó fallaba la autenticación ("Authentication failure: Got no
persistent peer data") hasta que la conexión vieja era reapeada como `Stale`, cosa que con `0008` tarda 30 s de
timeouts de keepalive. Medido en partida: PUN gastaba ~28 s reintentando el rejoin (71 intentos de estado 1 -> 2)
antes de poder volver a entrar a la sala. El parche busca el token entre las conexiones vivas y se queda con sus datos
persistentes, tirando la conexión vieja: un cliente que presenta un token de una sesión viva *es* esa sesión (PUN solo
reconecta con su propio token). `src/authentication.cpp`.

## Parche `0010-luxon-master-on-join.patch`

`Game::add_peer` no tocaba `master_actor`, y `Game::remove_peer` solo lo reasigna cuando la sala **no** queda vacía
(`game.cpp:226-228`). Como una partida sobrevive a sus peers (`empty_game_ttl`), la sala puede quedarse a cero con
`master_actor` apuntando todavía al actor que se fue; y `last_actor_id` nunca rebobina, así que el siguiente peer
recibe otro id y **la sala se queda sin maestro**. El valor por defecto de `master_actor` (`game.hpp:127`, `= 1`)
coincide con el primer actor que reparte `create_peer`, que es lo que hace que en retail el creador sea el maestro.

Es fatal para la reconexión de Kick-Flight: `ReconnectInfo` aprende quién es el maestro del property de sala
`MasterClientId` (248), que viaja en la respuesta de join; un cliente que reconecta a una sala de batalla vaciada
recibe "el maestro es otro", `UpdateReconnectWait` toma su rama no-maestra, sale cada frame por
`ReconnectInfo.IsSerializeRead == false` (esperando un `ReconnectSharedInfo` de un maestro que ya no existe) y acaba
en `BeginReconnectFailed` al agotar el presupuesto. Medido con la sonda 8992 en el cliente: causa **112 x 164**.

El parche asigna el mando al que entra cuando ningún peer vivo lo tiene:
`if (!find_peer(master_actor)) master_actor = fres.actor_id;` — la misma regla que ya aplica `remove_peer` cuando la
sala no está vacía. Con eso el cliente que reconecta es maestro y su propia rama de reanudación funciona (el parche
cliente en 0x1576B18 de `patch-il2cpp-endpoints.py`, que hasta ahora era inerte, pasa a ser el camino activo).
