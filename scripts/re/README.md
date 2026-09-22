# Static RE helpers for `libil2cpp.so` (arm64)

Used to trace the offline battle-start handshake and the AI blockers (see
`docs/CONTINUATION_PROMPT_BATTLE_CRASH_FIX_V2.md` §7). Everything works on the **pristine**
`libil2cpp.so` from `base.apk` plus the Il2CppDumper output in
`Kick-Flight-Assets/server_revival_analysis/il2cpp/` (RVA == file offset for this binary).

Setup (once):

```bash
pip install capstone
python -c "import zipfile;zipfile.ZipFile('../Kick-Flight-Assets/base.apk').extract('lib/arm64-v8a/libil2cpp.so','.local/re')"
python scripts/re/a64dis.py 0x156E8E0 40   # first run builds .local/re-cache/symbols.pkl from script.json (slow, once)
python scripts/re/reloc.py                 # builds .local/re-cache/reloc.pkl so string/metadata slots resolve
```

`KF_CLEAN_LIBIL2CPP` / `KF_SCRIPT_JSON` override the default input paths.

| Tool | What it does |
| --- | --- |
| `a64dis.py <rva> [n]` | annotated disassembly: method names on `bl`, string literals / TypeInfo / Method* on `adrp`+`ldr` |
| `xref.py <rva>...` | who `bl`/`b`s to these RVAs (virtual calls are `blr` and do not show up) |
| `reloc.py [--find "Text"]` | parse `.rela.dyn`; `--find` prints the slots that point at a string literal |
| `slotref.py <slot>...` | which code materialises a data slot (feed it the slots from `reloc.py --find`) |
| `bundle_tree.py <logical> [--filter re] [--all]` | transform hierarchy (local pos/rot/scale) of every prefab in a catalog bundle (`player/pc_005/pc_005_001`, `weapon/wp_005/wp_005_001_001`); repairs the Octo header via `../Kick-Flight-Assets/reconstruct_unity_bundles.py` |
| `anim_paths.py <kicker> --weapons 001_001,001_201` | clip generic bindings are CRC32 of the full transform path: explains the body bones and brute-forces `<bone>/<rootName>/<weapon node>` for animated weapons → the `Weapon` master bone + rootName |
| `meta_fields.py <Class>...` | il2cpp class fields straight out of `global-metadata.dat` (`--search`, `--dump-fields`): the served master JSON keys are the client's own field names, so this is the table that answers what a master row looks like |
| `served_master.py <Table>` | fetch and decrypt a served master from the running server (uses the direct-client Host header) |
| `bot_special_skill_cave.py` | keystone source of the production "AI casts its special skill" cave (prints replacement/expected hex for the patch table) |

Vtable slot N of an object is at `[klass + 0x128 + N*16]` (the `ldp x9, x1, [x8, #0x178]; blr x9` pattern
is slot 5). IL2CPP class-init boilerplate (`ldrb w8,[x0,#0x127]` ... `bl 0x11f7160`) can be filtered out.

## Runtime tracing

Build with `KF_DIAG=1` to include `DIAG_PATCHES_ARM64` from `patch-il2cpp-endpoints.py`, then read
`adb logcat -s KFDIAG` (values: 1xx UpdateRoomState, 2xx UpdatePlayerState, 3xx BeginAsync coroutine state,
4xx RoomState per UpdateState tick, 6xx `_enableAi` store, 700 AIPlayerEngine.Start, plus the return addresses of
every NRE raise). Resolve addresses with `/proc/<pid>/maps` (low 32 bits of the logged value minus the module base).

Rules learned the hard way:

- Never call `UnityEngine.Debug.Log*` from patched code on the x86_64 AVD: its stack-trace capture walks the
  cave frames (no unwind info) and crashes in `libunity.so+0x34426c`. `__android_log_print` (PLT `0x10D6270`)
  is safe.
- Function-entry hooks must use `b` (a `bl` clobbers the caller's LR before the prologue saves it) and the cave
  jumps back to entry+4 after re-executing the displaced instruction. Mid-function hooks may use `bl`+`ret`.
- Free dead code for caves: body of `PlayerBoneController.SetDisplayAngles` (0x13BC318-0x13BC3A8) and
  `GameManager.GetMenuType` (0x1570EB0-0x15710A4); both are stubbed at their entry by existing patches and
  nothing branches into them (verified). `HomeSummonModelController.SetModel` (0x159D1BC-0x159DAB0, entry-stubbed)
  holds the production bot-special-skill cave from 0x159D200 (376 bytes); the rest of its body is free.

## DIAG probe sets (attack, warp, bombs, reconnect)

* `scripts/re/attack_diag_caves.py` — KFDIAG 8100-8600: combo index of every swing (`8100+n`), target lost (`8200`),
  search-distance result (`8300/8301`), the four `IsAttack` angle checks with |delta| and limit (`8320-8323`),
  `IsAttack` true (`8310`), and which "in" animation played (`8400/8500/8600 + combo`). Minimal caves in the dead
  bodies of the entry-stubbed `PlayerBoneController.InterpolationUpdate` / `SetPose`.
  Read them with `python scripts/re/attack_diag_read.py [logcat.txt]` (collapses per-frame repeats).
* `scripts/re/warp_diag_caves.py` — KFDIAG 7700-7830: `JapaneseSwordSkillAction` no-target end position vs the
  player position, `WarpSkillAction.UpdateFinish` gates, `PlayerCharacter.SetVisible` pointers.
* `scripts/re/reconnect_diag_caves.py` — KFDIAG 8901-8992, the Photon-disconnect freeze. `CallbackDisconnected`
  entry on the object that owns the registered Photon callback: `8901` then the cause, `8902+|_isInitialized`,
  `8904+|byte44`, `8906+|_reconnectInfo != null`, `8908+|_offlineReplayTarget != null`. The same four on the object
  `GameManager.Initialize` ran on, just after `InitializeReconnect` returned: `8921` then `8922`/`8924`/`8926` (the
  pair 8901/8921 is what tells "the callback owner is not the object Initialize ran on" from "its fields were
  cleared"). `8961` marks every frame `UpdateReconnect` saw `_reconnectInfo == NULL` (silent while healthy).
  Also `SetReconnectState` (`8950+n`), the reconnect RPC round trip (`8981` `CallbackRejoinedRoom`, `8982`/`8983`
  the two `SendReconnectShared*`, `8984`/`8985` the two `ReceiveReconnectShared*`), `IsReconnectEnable` (`8930` +
  the room `RoomState`, `8940` + the failing cause, `8971` + each player's index and `PlayerState`) and `8992` +
  `SetReconnectFailedCause`, which named the empty-room mastership bug (patch `0010` in `docs/PHOTON_SERVER.md`). The docstring in the script carries the full reasoning, including why the two
  `<>4__this` guards cannot fire.
* Regenerate entries with the script and paste them before `# ---- END DIAGNOSTIC ----` in
  `patch-il2cpp-endpoints.py` (replace the whole previous block: caves are re-packed and move); build with
  `KF_DIAG=1 OUT=.local/KickFlight-2.11.0-DIAG.apk bash .local/build.sh` (Tanuki's machine) or
  `KF_DIAG=1 scripts/build-direct-apk.sh` / `.ps1` anywhere. `KF_NRE_LR=1` adds the NRE-origin hook (cave H).
  Values 8790+state (current PlayerStateType) and 8800+destroy type / 8810+hits (`CollisionBase.OnDestroy`) were
  added 2026-09-20; the latter pinned the 1-1-1 combo bug to `collisionHitType All` (see AGENTS.md).
* Dead bodies in use (all entry-stubbed in production, nothing branches into them): `HomeSummonModelController.SetModel`
  (0x159D200-0x159DAB0: gym/AI cave, GetDisplayAngles cave, warp probes), `UnloadModel` (region F),
  `PlayerBoneController.InterpolationUpdate` / `SetPose` / `LateUpdate` (attack probes),
  `PlayerCharacter.UpdateLookTarget` (0x13CD990-0x13CDFE0: regions D + E incl. the safe LOG helper, moved there by
  `scripts/re/relocate_diag_region.py` on 2026-09-20 — they used to sit in `LoadManager.LoadDeckSummonModel`, which
  forced the DIAG build to stub it and so no summon model ever loaded: Leorex/MOVE/TRAP froze the kicker in the
  skill state and it never respawned). `UpdateIdleTypeRate` (0x13CE3E0-0x13CE7C8): DIAG attack probes at
  0x13CE3E0-0x13CE4B0, the **production** bat-bomb TrapInfo cave (`BatAbilityParameter..ctor` tail, 60 bytes) at
  0x13CE500-0x13CE540 (64 bytes); DIAG bomb probes (`bomb_diag_caves.py`, 9001-9041) at 0x13CE540-0x13CE7B0.
  `HomeSummonModelController.SetModel` tail 0x159DA48-0x159DA78 holds the production bat-bomb HitInfo fallback cave
  (0x159DA78-0x159DAB0 free).
* `scripts/re/_disfull.py` = `a64dis.py` that does not stop at the first `ret` (whole-function listings).
