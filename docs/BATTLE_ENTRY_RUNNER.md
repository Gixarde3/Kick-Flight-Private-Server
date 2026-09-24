# Automated battle-entry runner

`scripts/run-battle-entry.ps1` drives the two established API 35 emulators through the repeatable path:

`TitleScene -> HomeScene -> MatchingScene -> GameScene`

It preserves application data, installs with `adb install -r`, verifies the installed APK hash, waits for Unity scene markers, fails immediately on native/Android fatal markers, and uses the already validated 1080x1920 tap coordinates only in the corresponding phase. Its preflight requires `http://127.0.0.1:18080/health/ready` to return HTTP 200 and writes Android's explicit `:0` no-proxy sentinel on both test AVDs; the direct APK must reach `10.0.2.2:18080` without the older capture proxy on port 8080. After a cold boot it also gives API 35 twenty seconds to settle, launches the two ARM-translated clients 45 seconds apart by default, and repeatedly selects **Wait** only while an ANR dialog is the current focused window, without terminating System UI or the game. `DownloadScene` is treated as an explicit checkpoint even when it appears late: its confirmation is tapped once and the Home timeout allows up to seven minutes for local cache reconstruction. Because `HomeScene` can be logged while the framebuffer still shows `LOADING`, the runner first waits for either the rendered Combat button or the white first-login modal. It dismisses the known overlays and then requires the actual yellow Combat-button region before continuing. A missed TAP START/Download, Combat, or Iniciar combate tap is retried at most twice, only for the device whose next scene marker is still absent. Once both clients report `GameScene`, it observes them for 90 seconds before the final screenshots so the evidence normally contains the arena/HUD rather than an initial loading frame.

Scene markers are lifecycle hints, not proof that a control is interactive.
The runner therefore requires the rendered TAP START background, the Home
combat/modal regions, and all eight white Matching roster rows before each
corresponding tap. It also aborts immediately when the scene stream contains
the known Octo `AssetBundleManager` `IndexOutOfRangeException`, instead of
consuming the rest of a phase timeout.

## Run

```powershell
& scripts/run-battle-entry.ps1 `
  -ApkPath .local/artifacts/KickFlight-2.11.0-direct-10.0.2.2-18080-online-v8-readiness-restore.apk `
  -RunId v8-readiness
```

Use `-SkipInstall` to rerun the currently installed build, or `-Target MatchingScene` to stop before starting battle. `-LaunchStaggerSeconds` adjusts the default 45-second separation between client launches. Pass `-BackendReadyUrl` only when the direct backend uses a different local readiness endpoint. `-ValidateOnly` checks the runner configuration without issuing ADB commands.

**One-command macOS setup:** `scripts/run-battle-avds-macos.sh` starts the selected existing AVD profiles, checks/starts `luxon-server` and the API when requested, waits for Android boot, and then invokes the multi-device runner. It never wipes userdata or clears app data. Supply either distinct existing IDs or onboard distinct names:

```bash
scripts/run-battle-avds-macos.sh --group 3 --player-ids 1000011,1000012,1000013 \
  --api-log .local/battle-test/current-api.jsonl --start-api-if-needed --start-photon-if-needed
# Or create new human profiles as part of the run:
scripts/run-battle-avds-macos.sh --group 5 --onboard --names Rook,Quill,Flint,Sage,Indigo \
  --manual-checkpoints --start-api-if-needed --start-photon-if-needed
```

`--dry-run` prints the AVD-to-serial plan without starting ADB. `--prepare-only` starts and boots devices, checks the API and exits. The main run owns and monitors any API/AVD processes it starts until the battle runner finishes. `--apk` installation is not currently implemented.

**Experimental on macOS:** use the multi-device Bash runner directly for 3–5 already booted AVDs. It
requires one distinct player ID per serial, in matching list
order, and it never clears app data, reinstalls the APK, restarts an AVD, or
reseeds a cache:

```bash
PLAYER_IDS='replace-with-three-fresh-player-ids'
scripts/run-battle-entry-multi.sh \
  --serials emulator-5554,emulator-5556,emulator-5558 \
  --player-ids "$PLAYER_IDS" \
  --run-id match-3-a \
  --api-log /path/to/current-api.log
```

Replace the example IDs with pre-created player files under
`src/KickFlight.BootstrapApi/data/users/` and provide the current API stdout
log. Repeat with four or five serials and a disjoint set of player IDs. Before any
client launch, it verifies a listener on the selected HTTP port and sends
`POST /boot/index` with `Host: 10.0.2.2`; HTTP 200 is required. It also checks
that the listener PID remains stable during scene waits. Evidence goes to
`.local/battle-test/multi-<RunId>/`. Screenshots are reduced to 720px.

The serial-to-player pairing follows list order. The runner appends every
pairing to `.local/battle-test/multi-run-player-registry.tsv` as an audit trail;
historical entries do not reserve an ID. The same players can enter successive
rooms, including after an earlier run ended or failed. Each run still requires
distinct IDs within its 3–5 player group. Before Combat, it verifies from fresh
logcat captured after clearing the device log that each serial loaded exactly
its paired numeric ID in `Load user profile(id=...)`; a mismatch or missing ID
stops the run.

The same profile check can audit a saved logcat without ADB:

```bash
scripts/run-battle-entry-multi.sh \
  --offline-profile-log .local/battle-test/multi-<RunId>/logcat-<serial>.txt \
  --expected-player-id 1000014
```

At Home, the runner verifies the rendered Combat button and taps `(820,1515)`;
that sends `/battle/entry` and starts the server's fixed 60-second room window.
From then through Stage 1, room close, Stage 2 and Stage 3, it only checks
structured API log lines and passive process/logcat health. It takes no screen
polls or screenshots during those stages. The JSONL parser reads `Message` and
`Timestamp`; it correlates entry and membership logs with the room BattleId,
checks Stage 1 per user during that room's open window, checks Stage 2 per user
after close, and requires every Stage 3 assignment to name that BattleId. It
verifies the entries span less than 60 seconds and precede the room deadline,
and requires room close between 59 and 65 seconds after creation. For 3, 4 or 5
humans, the expected bot fill is 5, 4 or 3 respectively in the 8-player 4v4
room.

The startup Download checkpoint uses each device's newest `DownloadScene` or
`HomeScene` log marker, not whether `DownloadScene` appeared at any earlier
time. While `DownloadScene` remains newest, it polls the current screen for at
most 60 seconds and checks process/API health on each pass. It stores only one
720px checkpoint when the known yellow KickFlight download screen is visible,
then taps the confirmation. If `HomeScene` becomes newest it skips the tap and
continues into Home. If the screen remains unrecognized for 60 seconds, it
stores one final checkpoint and fails without tapping.

After all Stage 3 assignments for that room are logged, it takes exactly one
720px screenshot per serial named
`matching-roster-after-stage3-<serial>-720.png`. The backend events prove room
membership, not what the client rendered: manually verify that each screenshot
actually shows that player's roster row. If it shows loading or GameScene, mark
the visual roster unverified; the runner does not poll or recapture it. The
experimental `(540,350)` prime tap is off by default. `--prime-control` opts in
to one tap after that screenshot checkpoint, and should only be used when the
current screen layout has already confirmed that coordinate is the intended
control. It then waits for `GameScene` and performs the existing movement and
attack gestures; gestures being sent are not proof that they worked.

To audit the local historical API stdout log without ADB or device access:

```bash
scripts/run-battle-entry-multi.sh \
  --offline-api-log .local/battle-test/adb3_20260924T020116Z/api-stdout.log \
  --player-ids 1000011,1000012,1000013 \
  --battle-id battle-790215460
```

That log contains successful 3-human runs; it does not establish a real 4- or
5-human run. The parser accepts 3–5 users, but broader live validation is still
needed. TAP START adapts the older 1080x1920 coordinate; Download and Home
modal/combat taps use the recent 1080x2340 coordinates and scale them to the
current framebuffer. `home-ready-before-combat-<serial>-720.png` records the
post-modal, pre-queue checkpoint. Review all checkpoint images and
`manual-gameplay-checklist.md`; GameScene arrival alone does not verify a
visible roster, movement, or attack controls.

If an emulator remains in a degraded loading/frozen state after a native crash, add `-RestartEmulators`. The runner invokes `scripts/restart-test-emulators.ps1`, which cleanly stops the two known serials, boots `KickFlight_API35` on 5554 and `KickFlight_API35_P2` on 5556 with the established software-rendering/no-snapshot flags, and waits for each boot. It does not uninstall the package or clear application data/cache.

Add `-VisibleEmulators` together with `-RestartEmulators` when the emulator windows should remain visible for observation. Visible mode uses the host GPU and four virtual CPU cores per AVD to keep API 35 System UI responsive; unattended headless mode retains the lower-resource software-GPU/two-core configuration.

## Evidence contract

Every run writes under `.local/gameplay-evidence/automated/<RunId>/`:

- `summary.json`: pass/fail, phase, reason, PIDs, and device state;
- `commands.jsonl`: timestamped ADB command transcript and exit codes, including backend readiness and Android proxy before/after state;
- checkpoint screenshots scaled to 720 pixels wide; raw screenshots are deleted;
- on any failure, full and filtered logcat plus activity, package, and process dumps for both devices.

The ADB-loop subagent runs this script once and inspects only `summary.json`, the 720-pixel failure/checkpoint images, and the filtered log. It reports a concise classification and evidence paths. The primary agent owns binary diagnosis and patch decisions.

## Full gameplay probes

`scripts/run-gameplay-probes.ps1` wraps the battle-entry runner and continues
with a deterministic, single-actor sequence. By default it cold-boots both
known AVDs with visible windows, enters a fresh battle, and uses 5554 as the
actor while 5556 remains the observer:

```powershell
& scripts/run-gameplay-probes.ps1 -RunId gameplay-probes-01
```

The sequence captures both screens before input, after ordinary flight, after
dash, after a slot-1 upward flick, before/after the Tsubame SP attempt, and at
timed checkpoints through the end of the three-minute match. It does not use
manual recovery gestures. `-SkipUltimate` omits the SP tap when a run should
isolate movement and discs; `-ObserveSeconds` controls the post-action
observation interval.

Gameplay probes reset the package data on both emulators by default before
launch. This prevents an abandoned prior battle from contaminating the next
empirical run. Pass `-ResetAppData:$false` only when intentionally testing a
warm-cache continuation.

Probe evidence is stored alongside the entry evidence under
`.local/gameplay-evidence/automated/<RunId>/`. It always includes
`probe-summary.json`, `probe-commands.jsonl`, 720-pixel screenshots, and full
plus filtered logcat for both clients. The filtered logs retain Unity scenes,
Photon activity, disc/special-skill markers, CriAtom/audio activity, and fatal
errors. The nested `<RunId>-entry` directory remains the authoritative trace
for all automated navigation before gameplay input.
