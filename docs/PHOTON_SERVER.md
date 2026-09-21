# Servidor Photon (LuxonServer) para partidas de 2 jugadores

Las partidas con dos humanos necesitan un servidor compatible con Photon: tras `/battle/start` el cliente entra a la
sala `battle-NNN` por Photon (NameServer 5058 -> MasterServer 5055 -> GameServer 5056, UDP). Los bots los sigue
poniendo nuestro API (`BattleMatchmakingService.BuildRoster`).

## Despliegue actual (2026-09-21)

* Host: `51.79.241.70` (Ubuntu 24.04), servicio `luxon-server.service` (systemd, `Restart=always`).
* Binario: `/opt/luxon-server/luxon_server`, config `/opt/luxon-server/config.yml` (= `config.yml` del fork con
  `external_address: 51.79.241.70:<puerto>`). Fuente en `~/kickflight/luxonserver` (fork `Gixarde3/luxonserver`
  @ `a84ecc3` + `scripts/luxonserver/000{1..5}-*.patch`, aplicados en ese orden con `git am`).
* Compilado con `g++-14` (el código usa C++23 "deducing this"; g++ 13 no compila):
  `cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DLUXON_SERVER_USE_SANMAKE=OFF -DCMAKE_C_COMPILER=gcc-14 -DCMAKE_CXX_COMPILER=g++-14 && ninja -C build`.
  Submodulos necesarios: `Luxon` y `tracy` (solo cabeceras).
* ufw: UDP+TCP 5055, 5056, 5058 y 27000-27002.
* Logs: `sudo journalctl -u luxon-server -f`.

## Cliente

El literal `ns.exitgames.com` del APK se reemplaza por `--photon-host` / `KF_PHOTON_HOST` (por defecto el host del
`--base-url`). Los APK de sabor Photon se construyen con `KF_PHOTON=1 KF_PHOTON_HOST=51.79.241.70` y se sirven en
`/apk/photon-remote`, `/apk/photon-diag`, `/apk/photon-diag-remote` (`start-client-photon-diag.bat` para el emulador).
Sin `KF_PHOTON=1` el APK usa el puente offline (sala local con bots) y nunca toca Photon.

## Parche `0001-pending-battle-join.patch`

Los dos humanos reciben el id de sala en el Stage 3 a la vez; el segundo `JoinGame` llega al MasterServer antes de
que el creador haya entrado al GameServer (`is_created == false`) y `validate_join` respondía `GameIdNotExists`, que
el cliente trata como desconexion fatal ("Title Disconnect Error" en el jugador 2). El parche deja pasar ese caso para
ids `battle-*`; el handler del GameServer ya crea o une al llegar. Pendiente: subirlo al fork `Gixarde3/luxonserver` y
actualizar el puntero del submodulo.

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
