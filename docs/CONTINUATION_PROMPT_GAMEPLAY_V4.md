# CONTINUATION PROMPT V4: GAMEPLAY VERIFICATION & EMPIRICAL FIX OF 5 IN-BATTLE ISSUES

> **Purpose**: Comprehensive handoff document for a new agent to pick up and empirically verify/fix the 5 remaining gameplay issues in the Kick-Flight 2.11.0 Private Server, running battles on two simultaneous Android emulators.
> **Version**: 4.0 (Successor to `CONTINUATION_PROMPT_BATTLE_CRASH_FIX_V3.md`).
> **Time invested in prior session**: ~20 hours. Infrastructure is fully operational; what remains is empirical gameplay verification and targeted fixes.

---

## 0. CURRENT INFRASTRUCTURE STATE (ALL OPERATIONAL)

### Running Services

| Service | How to start | Port(s) | Status |
|---------|-------------|---------|--------|
| **LuxonServer** (Photon emulator) | Docker container `luxon-server` (already running) | `5055/5056/5058` + `27000/27001/27002` (UDP+TCP) | ✅ Operational |
| **KickFlight.BootstrapApi** (C# backend) | `dotnet run` or `./scripts/run-local.sh` | `18080` (HTTP), `18081` (gRPC) | ⚠️ Verify if still running |
| **frida-server** | `adb -s emulator-5554 shell /data/local/tmp/frida-server &` | N/A | ⚠️ Needs restart if emulators rebooted |
| **Emulator A** | Android Studio AVD `kickflight_api35_arm64` | `emulator-5554` | ⚠️ Verify |
| **Emulator B** | Android Studio AVD (clone) | `emulator-5556` | ⚠️ Verify |

### Emulator-to-Host Connectivity

- Both emulators reach the host via `10.0.2.2` (Android emulator gateway).
- HTTP API: `http://10.0.2.2:18080`
- gRPC: `10.0.2.2:18081`
- Photon NameServer: `10.0.2.2:27000` (UDP) — **verified with `nc -z -u` returning exit code 0**.
- Photon MasterServer: `10.0.2.2:27001` (UDP)
- Photon GameServer: `10.0.2.2:27002` (UDP)

### Patched APK

- Location: `.local/artifacts/KickFlight-2.11.0-direct-10.0.2.2-18080.apk`
- 1,180 lines of ARM64 patches in `scripts/patch-il2cpp-endpoints.py`
- Build command: `SERVER_BASE_URL="http://10.0.2.2:18080" ./scripts/build-direct-apk.sh`

---

## 1. WHAT ALREADY WORKS (DO NOT TOUCH)

The entire flow from cold start to active battle is fully resolved:

```
TitleScene → TAP START → DownloadScene → HomeScene (full 3D, 14 kickers, 126 discs)
  → "Combate" button → MatchingScene (8-slot room, 4v4, 3-stage gRPC streaming)
  → "Iniciar combate" → GameScene → Arena FLD00101 (Crystalmania)
  → Spawn of 8 players (2 humans + 6 bots)
  → Team presentation (3, 2, 1, FLY!) → Active 3D flight ✅
```

Completed critical milestones:
- **Multi-player matchmaking**: Both emulators join the same room (`battle-XXXX`) with an 8-player roster (2 humans, 6 bots).
- **Authentic combat HUD**: 4 disc cards, SP button, ATK/HP stats, radar/minimap, timer, score.
- **3D flight controls**: Touch swipes propel kickers in 3D with booster thrusters and crystal collection.
- **Native crash prevention**: All SIGSEGV during team presentation, spawns, bone controllers, etc. resolved via IL2CPP patches.
- **LuxonServer integrated as submodule**: `submodules/luxonserver` at `https://github.com/Gixarde3/luxonserver.git` (commit `a84ecc3`).
- **PhotonServerManager in C#**: `IPhotonServerManager` with health checks registered as singleton in `Program.cs`.
- **24 unit tests pass**: `dotnet test` green.

---

## 2. THE 5 REMAINING ISSUES

### Issue 1: REAL-TIME MULTIPLAYER SYNCHRONIZATION (CRITICAL)

**Symptom**: Both players enter the arena and fly in 3D, but neither sees the other. Not in the 3D view, not on the minimap/radar. Each client operates in its own isolated world.

**Diagnosed root cause**: The battle network is split into two layers:
1. **Matchmaking (HTTP/gRPC)** → Works ✅ (both reach the same room)
2. **In-battle sync (Photon Realtime PUN)** → Clients fall back to `PhotonManager.CreateOfflineRoom` (RVA `0x18D783C`) because the patch at `MatchingControllerBase.ApplyBattleProperties` (RVA `0x17A2148`) jumped directly to `ChangeGameSceneSync`, bypassing the Photon connection handshake.

**Progress toward solution**:
- LuxonServer (open-source C++ Photon emulator) is running with all 6 ports open.
- Port accessibility verified from both emulators via `nc -z -u`.
- The Photon connection flow has been fully reverse-engineered:
  1. State 3 (`NormalMatchingEntryState`) → State 4 (`NormalMatchingJoinBattleRoomState`)
  2. State 4 calls `MatchingManager.Connect(...)` → NameServer 27000/5058 → MasterServer 27001/5055 → GameServer 27002/5056
  3. When `PhotonNetwork.InRoom == true` → `SendBattleStart()` → `POST /v1/battle/start` → `BattleStart()` → loads `FLD00101`

**What remains to be done**:
1. **Restore the original Photon flow** in the `ApplyBattleProperties` patch: instead of jumping directly to `ChangeGameSceneSync`, allow the client to connect to LuxonServer via the Photon handshake.
2. **Redirect Photon endpoint strings** in `libil2cpp.so`: overwrite `app.realtime.photonengine.cn` / `ns.exitgames.com` to `10.0.2.2` in `scripts/patch-il2cpp-endpoints.py`.
3. **Alternatively**: Use Frida to force `SetState(4)` on `NormalMatchingController` on both emulators to trigger Photon room connection.
4. Verify that `Colorful.PlayerRPCController` and `OnPhotonSerializeView` actually transmit position/rotation between clients.

**Key RVAs**:

| Function | RVA | Purpose |
|----------|-----|---------|
| `MatchingControllerBase.ApplyBattleProperties` | `0x17A2148` | Entry point deciding Photon vs offline |
| `NormalMatchingJoinBattleRoomState.Begin` | `0x13EF3EC` | Calls `MatchingManager.Connect(...)` |
| `NormalMatchingJoinBattleRoomState.Update` | `0x13EF5FC` | Checks `PhotonNetwork.InRoom` → `SendBattleStart` |
| `NormalMatchingController.SendBattleStart` | `0x13E9C64` | POST `/v1/battle/start` |
| `PhotonManager.CreateOfflineRoom` | `0x18D783C` | Isolated fallback (current problem) |
| `MatchingManager.Connect` | find callers of `0x13EF3EC` | Handshake with NameServer |

---

### Issue 2: EXTREMELY SLOW FLIGHT SPEED

**Symptom**: The kicker (Tsubame) moves very slowly, even when dragging the virtual joystick to maximum displacement.

**Root cause**:
1. Base values in `config/masters_kicker_parameter.json` are too low (`speed: 1.2`).
2. Null-safety patches in `PlayerStateNormal.UpdateAction` (`0x017E1858` → `0x017E19D4`) may be skipping the Dash impulse calculation.

**Proposed solution** (documented, not yet implemented/verified):
- Raise `speed` to `24.0`, `moveDashSpeedCoefficient` to `3.2`, `acceleration` to `36.0` in `config/masters_kicker_parameter.json`.
- Audit with Frida/Capstone that `PlayerStateNormal.UpdateFly` (RVA `0x017E136C`..`0x017E1800`) does not jump prematurely to the epilogue before applying velocity.

---

### Issue 3: DISC ACTIVATION VIA SWIPE-UP (LOW PRIORITY)

**Symptom**: Swiping/flicking upward on disc skill cards does not activate them.

**Potential cause**: The patch at `SkillRangeValidator` (RVA `0x18436D0`) uses `b #0x184377c` which may be bypassing target/range assignment entirely, causing the disc to always fail validation.

**Proposed fix**: Change the bypass so `SkillRangeValidator.CreateValidator` returns `true` (range always valid) rather than skipping the validator setup block.

---

### Issue 4: ULTIMATE (SP SKILL) FREEZES POST-CINEMATIC

**Symptom**: Pressing the central SP button triggers Tsubame's ultimate activation pose and cinematic animation correctly. But upon completion, the character remains frozen without executing the tornado/attack effect. After several seconds, normal flight control resumes.

**Root cause**: The special skill has 3 lifecycle phases:
1. ✅ Cinematic/Pose → `PlayerStateSpecialSkill.PlayAnim` → WORKS
2. ❌ Hitbox/Effect spawn → `ObjectManager.InstantiateSkillEffect` or `KickerSkillAction.Execute` → FAILS (likely NRE on effect prefab, or waiting for a Photon RPC confirmation that never arrives in offline mode)
3. ✅ Recovery timeout → Safety timer returns to `PlayerStateNormal`

**Proposed fix**:
- Hook `PlayerStateSpecialSkill.Update` or `TsubameSpecialSkillAction` with Frida.
- Ensure effect instantiation does not throw NRE and does not depend on Photon RPC.
- **NOTE**: If Issue 1 (Photon online) is resolved, this issue may self-resolve because the RPC confirmation would arrive.

---

### Issue 5: BACKGROUND MUSIC (BGM) STOPS AFTER 1-2 MINUTES

**Symptom**: Battle music plays at start but stops completely after 1-2 minutes.

**Root cause (CRIWARE audio engine)**:
1. Missing `.awb` streaming file. Only `bgm_battle01.acb` (metadata) is cataloged, not `bgm_battle01.awb` (streaming audio data).
2. Missing "hurry" last-minute track: `bgm_battle01_hurry.acb/.awb`.

**Proposed fix**:
- Search for `bgm_battle01.awb` in `octo_cache.tar` or extracted assets.
- Add corresponding entries to `config/resources/catalog.json`.
- Rebuild catalog: `python3 scripts/build_complete_catalog.py`

---

## 3. KEY FILE ARCHITECTURE

### C# Server (`src/KickFlight.BootstrapApi/`)

| File | Lines | Function |
|------|-------|----------|
| `DemoSessionApi.cs` | ~1117 | Main API: auth, startup, home, battle, kicker, disc, masters |
| `BattleMatchmakingService.cs` | ~321 | 3-stage gRPC matchmaking, roster builder, multi-client support |
| `PhotonServerManager.cs` | 149 | LuxonServer health check using raw `Socket` (no `TcpClient`/`HttpClient`) |
| `PhotonServerOptions.cs` | 15 | Config: host, ports, container name, repo URL |
| `Program.cs` | ~60 | Routing, DI, middleware |

### Client Patches (`scripts/`)

| File | Lines | Function |
|------|-------|----------|
| `patch-il2cpp-endpoints.py` | 1180 | 86+ ARM64 patches for `libil2cpp.so` + 12 for `libunity.so` |
| `build-direct-apk.sh` | ~100 | Pipeline: decode → patch → rebuild → sign APK |
| `build_complete_catalog.py` | ~200 | Octo protobuf catalog generator |
| `seed-device-cache.py` | ~150 | Pre-seeds 5,160 assets to device cache |
| `test-battle-loop.sh` | ~200 | 7-step automated test (title → home → combat → battle) |

### Local Tools (`.local/`)

| File | Function |
|------|----------|
| `run_multiplayer_match.py` | Automated matchmaking script for 2 emulators |
| `live_trace_battle.py` | Frida tracer injecting `PlayStartAnim` logs and other battle events |
| `frida-venv/bin/python` | Python environment with Frida installed |
| `adb-loop-notes.md` | Persistent ADB loop state (iteration history) |

### LuxonServer (Photon Emulator)

| File | Function |
|------|----------|
| `submodules/luxonserver/config.yml` | Config: 6 listeners (Name/Master/Game × 2), `external_address: 10.0.2.2:PORT` |
| `docker-compose.yml` | Defines `luxon-server` (gcc:14-bookworm) + `kickflight-api` services |
| GitHub repo | `https://github.com/Gixarde3/luxonserver.git` (commit `a84ecc3`) |

### Game Configuration (`config/`)

| File | Function |
|------|----------|
| `masters_kicker_parameter.json` | Speed/acceleration/dash parameters for all 14 kickers |
| `resources/catalog.json` | Full Octo catalog (~2,579 resources) |
| `resources/title-minimum.json` | Minimum catalog for title screen |
| `masters_kicker.json` | 14 kickers with roles, costs, abilities |
| `masters_disc.json` | 126 discs with stats, cooldowns, elements |

---

## 4. D2C ENCRYPTION

```
Key:  "1a837b9ee2ae11a07a0f529a4cd4b61c" (32 bytes UTF-8 = AES-256)
IV:   First 16 bytes of payload
Data: bytes[16..] decrypted with AES-256-CBC, PKCS7 padding
```

Both requests and responses are encrypted. Masters are encrypted with `EncryptMaster()` (random IV + same key).

---

## 5. STRICT OPERATIONAL RULES

### Screenshots
```bash
adb -s $DEVICE exec-out screencap -p > /tmp/raw.png && sips --resampleWidth 720 /tmp/raw.png --out /tmp/720.png
```
**ALWAYS** resample to ~720px width. **NEVER** use native emulator resolution.

### Code Constraints
- **FORBIDDEN**: Using `TcpClient` or `HttpClient` in `KickFlight.BootstrapApi`. Use raw `Socket` instead.
- Persistent state goes in `.local/adb-loop-notes.md`.
- Hard ceiling of 250,000 tokens; compact before 240,000.

### Build & Test Commands
```bash
# Rebuild APK with all patches
SERVER_BASE_URL="http://10.0.2.2:18080" ./scripts/build-direct-apk.sh

# Full automated test (single player)
./scripts/test-battle-loop.sh --build

# Quick test without reinstalling
./scripts/test-battle-loop.sh --no-install

# C# server
cd src/KickFlight.BootstrapApi && dotnet run

# Unit tests
dotnet test  # (from project root)

# LuxonServer (already running in Docker)
docker compose up -d luxon-server

# Multiplayer match runner
.local/frida-venv/bin/python .local/run_multiplayer_match.py

# Frida live trace
.local/frida-venv/bin/python .local/live_trace_battle.py
```

---

## 6. RECOMMENDED EXECUTION PLAN

### Phase 0: Verify Infrastructure is Still Operational
```bash
# 1. Verify Docker (LuxonServer)
docker ps | grep luxon-server

# 2. Verify emulators
adb devices

# 3. Verify C# server (may need restart)
curl -s http://127.0.0.1:18080/boot/index | head -c 100

# 4. Verify Photon accessibility from emulator
adb -s emulator-5554 shell "echo | nc -w1 -u 10.0.2.2 27000 && echo OK || echo FAIL"
```

### Phase 1: Fix Issue 2 (Flight Speed) — QUICK, NO PHOTON REQUIRED
1. Edit `config/masters_kicker_parameter.json`: raise `speed` to `24.0`, `moveDashSpeedCoefficient` to `3.2`, `acceleration` to `36.0` for all kickers.
2. Restart the C# server.
3. Relaunch the game on one emulator.
4. Enter battle and verify the kicker flies at a reasonable speed.
5. Capture 720px screenshot as evidence.

### Phase 2: Fix Issue 5 (BGM Audio) — QUICK
1. Search for `.awb` files in assets: `tar tf octo_cache.tar | grep -i awb`
2. If found, catalog them in `config/resources/catalog.json`.
3. If not found, verify whether the `.acb` includes embedded (non-streaming) audio.
4. Rebuild catalog: `python3 scripts/build_complete_catalog.py`
5. Verify with logcat: `adb logcat | grep -i CriAtom`

### Phase 3: Fix Issue 1 (Photon Synchronization) — REQUIRES CAREFUL PATCHING
1. In `scripts/patch-il2cpp-endpoints.py`, find Photon server strings (`ns.exitgames.com`, `app.realtime.photonengine.cn`, etc.) and overwrite them to `10.0.2.2`.
2. Evaluate whether the patch at `ApplyBattleProperties` (RVA `0x17A2148`) can be restored to allow Photon connection instead of jumping to offline mode.
3. Alternatively, use Frida to intercept `PhotonManager.ConnectToMaster` and redirect to the local LuxonServer.
4. Rebuild APK, install on both emulators.
5. Launch both → Combat → Verify both players see each other in 3D and on the radar.

### Phase 4: Fix Issue 4 (Ultimate Freeze) — MAY SELF-RESOLVE WITH PHASE 3
- If Photon is online, RPC confirmations for skill activation will arrive and the ultimate should work.
- If still failing, hook `PlayerStateSpecialSkill.Update` with Frida to find where the cinematic → attack transition stalls.

### Phase 5: Evaluate Issue 3 (Disc Activation) — LOW PRIORITY
- Adjust `SkillRangeValidator` bypass at `0x18436D0` to return `true`.
- Test swipe-up on disc slot 1: `adb shell input swipe 200 2050 200 1600 200`

---

## 7. ACCEPTANCE CRITERIA (REQUIRED TO CLOSE)

Each issue requires **empirical evidence** (720px screenshot + logcat excerpt):

| Issue | Criterion | Required Evidence |
|-------|-----------|-------------------|
| 1. Sync | Both players see each other move in 3D and on the radar in real time | Screenshots from both emulators showing the other player at a different position |
| 2. Speed | Flight at reasonable speed with dash noticeably faster | Screenshot + logcat with speed values |
| 3. Disc | Swipe-up activates a disc and the effect is visible | Screenshot of activated disc |
| 4. Ultimate | Tsubame executes tornado post-cinematic with hitbox/speed boost | Screenshot of active tornado effect |
| 5. BGM | Music plays continuously throughout the full 3:00 match | Logcat showing CriAtom without interruptions |

---

## 8. REPOSITORY REFERENCE & CLONING

```bash
# Clone the main repo
git clone https://github.com/Gixarde3/Kick-Flight-Private-Server.git
cd Kick-Flight-Private-Server

# Initialize LuxonServer submodule
git submodule update --init --recursive

# LuxonServer is pulled from:
# https://github.com/Gixarde3/luxonserver.git (commit a84ecc3)
```

---

## 9. ABOUT LUXONSERVER

**LuxonServer** is an open-source Photon Server emulator written in C++. It implements the Photon Realtime protocol (NameServer, MasterServer, GameServer) sufficiently for PUN2 clients to connect, create rooms, and relay game data between peers.

- **Repository**: `https://github.com/Gixarde3/luxonserver.git`
- **Registered as submodule** in `.gitmodules` under `submodules/luxonserver`
- **Configuration**: `submodules/luxonserver/config.yml` defines 6 listeners with `external_address: 10.0.2.2:PORT`
- **Docker**: Runs on `gcc:14-bookworm` image with pre-compiled `luxon_server` binary
- **C# integration**: `PhotonServerManager.cs` performs TCP/UDP health checks on all 3 primary ports
- **Project commits**:
  - `485d0d0`: Initial patch for Kick-Flight battle synchronization compatibility
  - `a84ecc3`: Binding of on-premise fallback ports (27000-27002)

---

## 10. PRIOR SESSION ITERATION HISTORY (SUMMARY)

The prior session went through 29+ iterations documented in `.local/adb-loop-notes.md`. Key milestones:

| Iteration | Achievement |
|-----------|-------------|
| 1-20 | Title → Home → Kickers/Discs screens fully operational |
| 21-26 | Battle entry, asset loading, SIGSEGV crash resolution |
| 27 | Automated test runner (`test-battle-loop.sh`) created and validated |
| 28 | "3, 2, 1, FLY!" presentation sequence fully working (green run with Frida tracer) |
| 29 | Spectator mode → real HUD fix, 2-emulator matchmaking, active 3D flight on both devices |
| 30+ | Photon port binding fix (LuxonServer), submodule registration, C# PhotonServerManager, UDP accessibility verification |

The 5 gameplay issues in Section 2 were identified during Iteration 29's dual-emulator validation and remain the final blockers before declaring full battle functionality.
