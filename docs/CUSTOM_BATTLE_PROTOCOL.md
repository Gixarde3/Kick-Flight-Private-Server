# Custom battle server contract

This note records the retail DTO contract verified against
`.local/adb-device-test/20260929-baseline/installed-base.apk` with
`scripts/re/meta_fields.py`, and the custom-room flow observed through
2026-09-30.

## Masters

`CustomBattleRuleFieldMasterData` inherits `id` and declares `battleRuleType`,
`fieldId`, and `sortOrder`. The server serves this table from
`config/masters_custom_battle_rule_field.json`. The current pool exposes the
six stages with catalog-backed custom variants (101, 301, 401, 601, 701, 901)
for rule types 1–3; trial field 801 has no matching custom variants.

`CustomBattleKickerAiMasterData` inherits `id` and declares
`kickerAiParameterId` and `kickerAiDiscDeckId`. The server serves the valid
parameter IDs 1–14 and existing deck ID 1 from
`config/masters_custom_battle_kicker_ai.json`.

Both tables are encrypted in the normal master response. The running server
returned both from `/demo-master/CustomBattleRuleField` and
`/demo-master/CustomBattleKickerAi` with HTTP 200 after the master hash changed;
no app data clear was needed.

## HTTP DTOs

- `CustomBattlePrepareRequestData` has no fields; its response contains only
  `assetList`, a list of `ResponseAsset` values with `platform` and `revision`.
  The handler returns the request's `x-app-asset-platform` and
  `x-app-asset-revision` values. `ResponseAsset.IsSameAssetRevision` compares
  that revision to `ArchiveData.AppAssetRevision`; this is separate from the
  CDN `title-minimum.json` revision (27).
- `CustomBattleStartRequestData` contains `battleRuleType`, `fieldId`,
  `fixedDiscLevel`, `gearAvailableFlag`, `customBattlePlayerList`, and
  `spectatorUserIdList`. Each `RequestCustomBattlePlayer` contains `userId` and
  `teamType`.
- `CustomBattleStartResponseData` contains `customBattleId` and
  `guardianParameter`. `ResponseGuardianParameter` contains `id` and `rank`.
  The handler validates the requested rule/stage pair, uses guardian parameter
  row 2 for rule type 3 and row 1 otherwise, and returns rank 1. The returned
  `customBattleId` is prefixed `custom-` and is a recording/correlation ID used
  by later end/result requests. The client has already created or joined its
  Photon lobby room by `RoomName`; this ID is neither the Photon `GameId` nor
  the four-digit invite code.
- `CustomBattleEndRequestData` carries `customBattleId`, `teamScoreList`, and
  `userScoreList`; `CustomBattleResultRequestData` also carries battle
  statistics. Both response DTOs have zero fields, so `{}` is valid.

## Invite-code boundary

The retail `CustomBattleStartRequestData` has no invite-code field. Static
client analysis found that the code is formatted from
`ArchiveData.LastMatchingCode` and passed to `SetLobbyName`; code entry calls
`MatchingManager.SearchRoomAsync(11)`. The room row's separate `RoomName` is
passed to `JoinRoomAsync`, which uses the Photon room identity. Luxon treats
room properties as generic replicated properties and has no built-in
four-digit-code lookup. These HTTP handlers do not create or resolve invite
codes. Team assignment must use the persisted `teamType` from the custom
roster; a spectator must be represented as a room actor with Photon
`TeamColorType=2` and excluded from `customBattlePlayerList`/the battle roster.

## Photon lobby properties

Static client analysis found that `CreateRoom` fills
`RoomOptions.CustomRoomProperties` with `RoomCode`, `RoomName`, region/host
details, team-join flags, secret flag, rule type, and battle-rule info. It does
not fill `CustomRoomPropertiesForLobby`, whose constructor value is empty.
Luxon therefore uses a narrow fallback only for rooms containing `RoomCode`
when the explicit `lobby_props` list is empty: it exposes whitelisted custom
property keys that are actually present in the room properties. Existing
explicit lobby lists and non-custom rooms stay on their original path. Room
list delivery and lobby updates both use the same game-property projection.

## Custom battle spectator menu guard

On the pristine client, `GameManager.GetMenuType` (RVA `0x1570EA8`) uses the
`HomeInfo.BattleModeType == 1` branch (`0x157104C`) before checking
`BattleUtil.GetMyTeamType` and `TeamColorTypeExtensions.IsSpectator`; that
branch returns menu type 5 for a normal player and 6 for a spectator. Other
battle modes return 0. `BattleDisplayPresenter.ChangeMatchingScene` (RVA
`0x1440710`) sets `HomeInfo.BattleModeType=1` and copies the custom battle type
when `BattleRuleViewInfo.CustomBattleType != -1` (`0x1440770`–`0x1440864`);
the `-1` path sets mode 0 (`0x14409C4`). This confirms custom matching reaches
the existing spectator-aware menu guard. Runtime validation covered custom
room creation, four-character-code join to the host's actual room, team changes,
and creation/join as spectator. In the three-peer Photon-flow match, all peers
reached `GameScene` and rendered the HUD without the earlier battle-initialization
NREs; the spectator reached observer mode outside the combat roster. The match
reached `ResultScene` with a `DRAW`, and end/result both returned HTTP 200. A
short swipe in the clear arena area moved a player in flight. The user later
confirmed that manual spectator camera target selection works in their test.
That user-run validation is separate from the earlier ADB taps below, which did
not reach the instrumented presenter callback.

The client control path is `SpectatorInfoPresenter.Initialize` →
`SpectatorInfoView.AddIcon` → `SpectatorCharacterChangeIconView` click callback.
That member-icon callback calls `SpectatorInfoModel.SetTarget`, then calls
`ReplayManager.SetMainPlayer` in replay mode or `GameManager.InitializeSpectatorPlayer`
for a live spectator. The live initializer sets `ObjectManager`'s spectator and main
player and updates the camera state. The blue/red
team arrows only switch the roster panel layout; `All` opens the all-player
view. On the 720×1560 emulator capture, `All` is centered near `(547,1493)`
(native 1080×2340 `(821,2239)`). After opening it, tap the desired member icon
in the roster. In our earlier ADB attempts, tapping the small opposing
scoreboard portrait and visible red roster portrait did not change the
displayed target. A DIAG build logs
`9101` at the presenter member-selection callback, `9102` at
`InitializeSpectatorPlayer`, and `9103` at `SetMainPlayer`. In the active-HUD
tap, none of these values appeared, so no presenter target-change callback was
observed in those ADB attempts. The user subsequently confirmed successful
manual camera selection; the ADB taps are not the evidence for that
confirmation. The tags do not log account data. Their caves use the free tail of
the entry-stubbed `UpdateIdleTypeRate` body after the costume-refresh cave.

The optional target-selection DIAG build is
`.local/artifacts/KickFlight-2.11.0-spectator-camera-DIAG.apk` (SHA-256
`0d7b573897b055b8c7dd9e352cdd87725c7aed9764ddd476f5be453f5716c95e`). It is
`KF_PHOTON=1` and `KF_DIAG=1`; use it on the host only and leave guest peers on
the final Photon-flow APK. Its fixed KFDIAG values are `9101` member callback,
`9102` live spectator initialization, and `9103` manager target setter.

## Build the Photon matchmaking client

The patcher defaults to its offline matchmaking bridge. Custom-room tests with
Luxon must explicitly set `KF_PHOTON=1` when building; the direct APK script
does not set this flag. Without it, the offline patch replaces
`MatchingControllerBase.ApplyBattleProperties`, stores battle data only in the
local archive, and jumps directly to `ChangeGameSceneSync`. It skips the
Photon `RoomBattleInfo` property write and `RoomState=3` update required for
peers to initialize the same battle data. A Photon room can still report later
state writes as successful while guests receive guardian/player instantiates
without `BattleInfo`.

On macOS, build the emulator APK with:

```sh
KF_PHOTON=1 SERVER_BASE_URL=http://10.0.2.2:18080 OUTPUT_APK=.local/artifacts/KickFlight-2.11.0-custom-photon-flow-final.apk scripts/build-direct-apk.sh
```

Install the same Photon-flow artifact on every peer. A filename containing
`PHOTON` does not prove which matchmaking branch was compiled; inspect the
patcher output or verify that RVA `0x17A2148` retains the pristine
`ApplyBattleProperties` prologue. In the 2026-09-29 repro, the old c44
spectator-compatible APK and the c802 costume-refresh APK both contained the
offline stub there. The replacement artifact
`KickFlight-2.11.0-custom-photon-flow-final.apk` was built with
`KF_PHOTON=1` and verified to retain the original method while keeping the
costume-refresh and spectator-menu patches. Its SHA-256 is
`5580ab9b7f530920da5916d0798cb78e6070c1fc3f6ed543f12c51601bfb6370`.

The first three-peer run with this artifact verified Photon room-state updates
`3 → 4 → 5 → 6`; each update passed compare-and-swap and produced an Event253
property update with all three actor IDs as recipients. All three clients
entered `GameScene` and displayed the HUD without the earlier
`NPCGuardian.InitializeAsync`/`PlayerCharacter.SetModel` NREs. The match reached
`ResultScene` with `DRAW`. `/customBattle/end` returned HTTP 200 at
`2026-09-30T03:01:49.487Z`; `/customBattle/result` returned HTTP 200 at
`2026-09-30T03:01:52.047Z` and `2026-09-30T03:01:52.527Z`. The original cause
was the offline `ApplyBattleProperties` stub skipping the Photon
`RoomBattleInfo` and `RoomState=3` write. Manual spectator camera target
selection was subsequently validated by the user; the prior ADB probe did not
reach the target-change callback.

The Linux aarch64 Luxon binary was rebuilt after removing temporary
`[KFRoomState]` diagnostic logging and only the `luxon-server` container was
restarted. The active binary SHA-256 is
`29d91245cd11b7d631a399b76401aa7809a1339b7e2cba180c6eeda60e616c3e`. The API
was not restarted; `/health/photon` returned HTTP 200 at
`2026-09-30T15:51:09.233196Z`, with Master, Game, and Name reachable at
`10.0.2.2` on ports 5055, 5056, and 5058. The container is running with restart
count 0 and publishes TCP/UDP 5055, 5056, 5058, and 27000–27002. The live Photon GameList payload was not decoded
as raw bytes, but runtime code `2563` resolved to the host's real `Crystal
Scramble`/`FLD00101` room; the client displayed both `waba` (Blue) and `waba2`
(Red), and the three-peer run then reached gameplay. This verifies the
observable room lookup, roster, and start flow.

## Additional client evidence

### Client-side asset revision gate (static IL2CPP evidence)

The custom create callback constructs `List<ResponseAsset>` from
`CustomBattlePrepareResponseData.assetList`, stores it as
`ArchiveData.ApplicationAssetRevisionList`, then calls
`PhotonUtil.IsSameAssetRevision` before connecting (`SendCreateRoom` callback
RVA `0x1852EF0`; setter call `0x31F51D0`; comparison call `0x18E37E4`). A false
result takes the `CommonWindow` path at `0x18530C0`, which is the “New Data to
Download” gate; it then proceeds through Photon connect.

The predicate (`PhotonUtil.<>c.<IsSameAssetRevision>b__120_0`, RVA
`0x18E464C`) only accepts a list entry with `platform == 3` and
`revision == ArchiveData.AppAssetRevision`. That getter (RVA `0x31F48BC`)
reads `[this+0x30]`. The same getter feeds
`NetworkManager.AddRequestHeaderAssetRevision` (RVA `0x31B5A10`), which emits
`x-app-asset-revision`. Thus the observed request value `0` means the matching
custom prepare response is `{platform:3,revision:0}`; the title/catalog path
revision `27` is a separate value and would fail this client-side equality
check. An empty `assetList` also fails. The API now echoes the request's
platform/revision pair; with `{platform:3,revision:0}`, the host created the
room and the second client joined without seeing the update/restart popup.

This is distinct from the CDN Octo catalog revision: `config/resources/title-minimum.json`
sets revision `27`, and `scripts/build-title-resource-catalog.py` uses it to
generate `/v1/list/{assetVersion}/{fromRevision}` resources. The client's app
archive revision instead comes from the response header `x-app-asset-revision`:
`NetworkManager.UpdateResponseHeader` (RVA `0x31B7734`) parses it and calls
`ArchiveData.CheckAppAssetRevision` (`0x31F592C`), which stages a changed value
at `[ArchiveData+0x27c]`. `DownloadScene.<DownloadAsync>d__26.MoveNext`
(`0x149BE50` onward) later persists that staged revision through
`ArchiveData.UpdateAppAssetRevision` (`0x31F5964`) and `WriteArchive`. The
observed client sends app archive revision `0`; the CDN list/catalog request
for revision `27` does not imply that the installed app archive revision
should be changed to `27`.

The backend build and master-download path have been verified. Two host taps
reached `/customBattle/prepare` with HTTP 200 while the response still contained
`assetList:[]`; captured request headers carried app-asset platform 3 and
revision 0. Each tap was followed by `/v1/list/12345/27` and a fresh
`/auth/prepare`, `/auth/index`, `/startup/index`, `/download/master`, and
`/home/index` sequence. This confirms the old handler led into the client's
data-update/restart path. The handler now returns the platform/revision pair
from the request (`3/0` in the captured client). The A/B check passed: host and
guest entered the same room with no update loop, and a host drag moved `waba2`
from Red to Blue; the second client showed both users in Blue afterwards. The
later three-peer matches verified battle start, HUD rendering, flight movement,
`ResultScene`, and successful end/result responses. Manual spectator camera
target selection remains unverified; see the section above.

Screenshot `.local/custom-rooms-runtime/invite-after-accept2-720.png` shows the
custom create modal rendered with rule `Crystal Scramble`, stage `FLD00101`,
player-count controls, and separate `Create Battle` / `Create Battle
Spectator` buttons. `FLD00101` is the literal `Field.name` in the currently
served master; `masters_translation.json` has no map-name key. The rule-field
master contains six stage rows per supported rule type. Runtime confirmed
`FLD00101` and the lobby/game flow; visual paging through every stage was not
part of the completed run.

## Verified runtime acceptance

- Created a custom room and joined it from other clients by its four-character
  code; the clients resolved to the host's Photon room and shared its roster.
- Changed a joined player's team and observed the updated team on clients.
- Created and joined as a spectator. The spectator appeared as a room peer,
  entered observer mode, and stayed outside the combat roster.
- Started a three-peer match. Photon `RoomState` updates 3→4→5→6 were observed
  with successful compare-and-swap and updates addressed to all three actors.
  All peers rendered the battle HUD, and the spectator remained an observer.
- Finished at `ResultScene` with `DRAW`; `/customBattle/end` and
  `/customBattle/result` returned HTTP 200. A clear-arena swipe moved a player
  in flight.
- Manual spectator camera target selection: validated by the user in a separate
  test. Our prior ADB taps did not reach the instrumented callback.
- Visual paging through every stage was not verified in this run.
