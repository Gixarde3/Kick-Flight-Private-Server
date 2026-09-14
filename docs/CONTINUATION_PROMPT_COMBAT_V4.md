# Continuation — combat / real devices (2026-09-14, session 4)

Read this first, then `docs/CONTINUATION_PROMPT_COMBAT_V3.md` (previous session) and
`docs/COMBAT_MASTERS_FILL_IN.md`. Repo: `Kick-Flight-Private-Server` (.NET 8, branch `tanuki-discs`);
assets/RE material in `../Kick-Flight-Assets` (`server_revival_analysis/il2cpp/dump.cs`, `base.apk`).

## Rules from the user

* The user stages and commits on GitHub themselves — never `git add` / `git commit`. Leave work in the
  working tree; `git status` at the end of this session was the PR-ready change set (39 files).
* Don't use subagents. Tuning numbers (radii, damage, timeouts) come from the user's in-game feedback.

## State of play

* Server: `src/KickFlight.BootstrapApi`, run from `src/KickFlight.BootstrapApi` with
  `HttpPort=18080 GrpcPort=18081 Harness__PersistCaptures=true Harness__DirectClientHosts__0=192.168.68.55
  Harness__DirectClientHosts__1=kickflightsg.ddns.net dotnet bin/Release/net8.0/KickFlight.BootstrapApi.dll`
  (or `start-server.bat`). Logs: `.local/session-logs/server-<stamp>.log` (JSON per line, UTC). Catalog and
  fixtures hot-reload on file change; C# changes need `dotnet build -c Release` + restart (stop the old
  `dotnet` first: it locks `bin/Release/...dll`). 22 tests: `dotnet test tests/KickFlight.BootstrapApi.Tests`
  (they touch the live saves `data/users/1000001.json` / `1000002.json` and spawn `data/users/<guid>.json`
  strays — delete the strays, restore/keep the saves as the user prefers).
* APKs: `bash .local/build.sh` (LAN, `URL=http://192.168.68.55:18080`) and `bash .local/build-remote.sh`
  (`kickflightsg.ddns.net`) → `.local/KickFlight-2.11.0-current-patches.apk` / `-remote-kickflightsg.apk`,
  built 12:14 with 137 il2cpp patches (`scripts/patch-il2cpp-endpoints.py --dry-run <pristine libil2cpp.so>`)
  + `scripts/patch-octo-http-timeout.py` (classes2.dex). Pristine lib: `zipfile` from `../Kick-Flight-Assets/base.apk`.
* Emulator `KickFlight_A15` (x86_64 + ndk_translation, `emulator -avd KickFlight_A15 -memory 6144`),
  package `jp.grenge.kickflight`, taps 1080x1920: START 780,858 · Download 765,1193 · notification prompt
  "Don't allow" 540,1197 · Combate 818,1239 · Aceptar 540,1454. **No cache seeding any more**: `adb shell pm
  clear jp.grenge.kickflight` → START → Download fetches 2593 files / 728 MB (~2 min on the emulator).
  Emulator time zone was set to Asia/Singapore this session (`adb root; setprop persist.sys.timezone`).
* The user's HONOR phone (arm64) runs the remote APK over `kickflightsg.ddns.net` (double NAT: Huawei ONT
  192.168.100.1 → Deco WAN 192.168.100.3 → PC 192.168.68.55; TCP 18080/18081 forwarded). Full download and
  a solo battle vs bots work on it. This PC's uplink is only ~250 KB/s (Wi-Fi 27 Mbps link) — a first download
  from outside takes ~50 min; `Harness:OctoCdnUrlFormat` exists to move the bundles to a static host.
* Battle: guardians (turrets) take/deal damage (`GuardianParameter` hp 8000 / attack 6000), all special
  skills work except Owlbert's, Kite's shuriken one-shots (`fixedDamage` 999999), Tsubame knock-up ok, Sid
  paralyse + tick damage ok. Training room is unsupported (`PlayerCharacter.Initialize` NRE).

## Fixed this session (all uncommitted, see V3 doc "Real devices / remote play" for details)

1. Octo initial download: unique tag `common`, zh rows dropped, revision 25, **alias-row ordering**
   (`build-title-resource-catalog.py::order_rows`: cache files are named by MD5, twins in flight together =
   "communication error"; primaries-with-aliases largest-first, alias-free primaries, then all aliases).
2. `matchmakingExpirationDatetime` fixed to `2030-01-01 00:00:00` (a UTC "now+30min" string is hours in
   the past on a UTC+8 phone → `/battle/timeout` 230 ms after Stage 1).
3. Remote play: `OctoDatabaseUrl.Rewrite` (url format follows the request host), `DirectClientHosts`,
   `OctoCdnUrlFormat`, dex HTTP timeouts 20/120 s, `MaxParallelDownload` 4, `StallTimeout` 120 s.
4. Guardian damage both ways (`CallbackBattleStartSuccess` copies rank/hp/attack; HP bar waits for
   `IsCreatedGuardian`), `SkillCollision`/`SkillHit` served, `LoadManager.Enqueue` unload bypass off by default.

## BREAKING ISSUES for next session (user's list)

### 1. Owlbert (kicker 5, weaponType 4 Drone) — KS and SS do nothing
* Intended: SS = drones fly out of his backpack to every ally, each ally leaves a smog behind (allies hidden /
  untargetable, enemies inside disturbed); KS = drops a drone as a trap that **silences** enemies.
* Wiring so far (`scripts/generate_combat_masters.py`): SS special id 5 is hard-coded by the client as a
  Smog trap (`PlayerSpecialSkilParameter..ctor`), data = trap type 6 r100 + conditions SmogProtection (20)
  trigger 3 and 6, SmogDisturb (19) trigger 5, `range` 100. KS 20005 "Dron Centinela" actionType 13,
  `KICKER_SKILL_EXTRAS[20005]` = Silent (9) conditions (trigger 5 and 4) + trap type 2 r8;
  `NPCDrone.InitializeAsync` reads `owner.GetWeapon(101).ModelCtr` (Weapon prop 101 row added, bone
  `Prop_Common`) and `KickerSkillParameter.Conditions[0]`. Cut-ins call `HighPlayerCharacter.GetWeapon(201)`
  (prop 201 rows added). Loading crash is gone; the skills fire (cooldown) but no drones/smog appear.
* Start by capturing a logcat while casting each (`capture-logcat.bat` → `.local/logcat-*.txt`; run the
  Unity exception aggregation over `E Unity` + "  at " frames), then check `NPCDrone` / `SmogTrapAction` /
  `DroneSkillAction` in `dump.cs` for what they read (summon table? `Summon` master is served, 70 KB; the
  drones may be `Summon` rows keyed by `skill.summonId`, which is 0 for 20005).

### 2. Buzzy Big (kicker 12) — KS does nothing (SS = unbreakable ally shield 5 s works)
* KS 20012 "Megamartillo": `skillActionType` 18 (= weaponType 9 Shield + 9 per
  `KickerSkillParameter.GetSkillAction`), coolTime 8, range 8, speed 15, coefficient 2.2, summonId 0.
* Lead: `config/masters_kicker_parameter.json` (kickerId 12) says `weaponType` 10, but skill 20012's
  `skillActionType` 18 = weapon type 9 + 9 (generator formula `wt+9`, wt<=11). Same table gives Jay
  (kickerId 9) weaponType 1 and Diatrius (11) weaponType 9, while the user's list is Buzzy Shield 9 /
  Jay Bat 10 / Diatrius PunchGlove 7 (generator enum: Sword 0 … PunchGlove 7, Bowgun 8, Shield 9, Bat 10,
  Nunchaku 11, JapaneseSword 12, Laser 13). Resolve the enum against `Colorful.WeaponType` in `dump.cs`
  and `KickerSkillParameter.GetSkillAction` before editing — special skills work today, so whatever is
  served is at least self-consistent for SS. Then check whether action type 18 needs
  `SkillCollision`/`SkillHit`/`SkillBlowOff` rows (a hammer slam) that the generator does not emit for
  kicker skills — `KICKER_SKILL_EXTRAS` is the place. Logcat first.

## Open / lower priority
* Sid: Paralysis was removed from the Laser conditions while debugging (user later confirmed paralyse +
  tick works — re-check the served rows before touching). Camera unhooks after lock-on with Sid.
* Coco (10x) / Diatrius (100x) SS radii were applied as asked, unverified by feel.
* Jay: KS untargetable (Stealth?) and SS "obscure the map for the enemy" unverified.
* Bot names in `BattleMatchmakingService.BotProfiles` are stale (Kaito/Pit/Yukari/Yui/Eleonora); real names
  are in `config/masters_kicker.json` (1 Tsubame … 12 Buzzy Big, 13 Hitagi, 14 Sid).
* Placeholder audio: 45 `.awb` names map to one afs2 archive (`Ei4139`); real mapping unknown.
* `.local/apk-catalog-entry.json` re-adds the remote APK download route to `catalog.json` if needed.
