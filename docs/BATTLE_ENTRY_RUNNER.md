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
