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
  nothing branches into them (verified).
