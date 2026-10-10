"""Replay-system probes for DIAG builds (handoff/dsh-replay-3) + the Photon `get_ReplayMode` getter cave.

Why
---
`scripts/patch-il2cpp-endpoints.py` used to disable the whole replay system in every flavour, so no build ever
recorded a replay. For `KF_PHOTON=1` the production table now lets `ReplayManager.BeginSession`,
`GameManager.<BeginAsync>` state 11 (`StartSessionUpdate`), `EndSession` and the real `get_ReplayMode` run (see
the replay entries in that file). This script provides two things:

1. **Production (KF_PHOTON only): the real `ReplayManager.get_ReplayMode`.**
   The offline flow stubbed `get_ReplayMode` (RVA 0x1773670) to `mov w0,wzr; ret` so the HUD never took the
   replay/spectator route, and reused the rest of the method's body (0x1773678.., 0x17736D8) for the offline
   `CharacterBase.IsMine` cave and the 940+ `PlayerCharacter.SetState` DIAG probe. The real getter is:

       0x1773670  ReplayManager_TypeInfo (re-init) -> +0xb8 static fields -> ldr w0, [x8]   ; <ReplayMode>

   Because the body is occupied, Photon cannot simply restore the stub. Instead 0x1773670 becomes
   `b GETTER_CAVE` (the same 8 bytes) and the cave re-implements the original getter (class-init + static field
   read) and `ret`s. The `IsMine` cave and the 940+ probe stay untouched after 0x1773678.

2. **DIAG (KF_DIAG=1): KFDIAG probes 9303-9339** (the task's 9300-9399 range; 9300-9302 are already used by
   the bounded `BeginAsync` player wait, scripts/re/begin_async_wait_cave.py):

       9303        ReplayManager.BeginSession entered (GameScene.<PreBeginAsync> calls it)
       9304/9305   ReplayManager.CanBeginSession result: 9304 = false, 9305 = true
       9306        ReplayManager.BeginRecordingSession returned a non-null ReplayRecordingSession
       9307        ReplayManager.EndSession entered (GameScene.<PostEndAsync> or BeginSession's re-entry)
       9310        ResultManager.<UploadReplayDataAsync>d__59.MoveNext state 0 entered
       9311/9312   Upload gate 1 PhotonManager.IsMyPlayerMaster: 9311 = false (no upload), 9312 = true
       9313/9314   Upload gate 2 ArchiveData.IsUploadReplayData: 9313 = false, 9314 = true
       9315/9316   Upload gate 3 BattleInfo.BattleId: 9315 = non-empty (pass), 9316 = empty (abort)
       9329-9332   Upload gate 4 WriteResult.WriteState raw value + 9330 (Invalid=-1 -> 9329, Progress=0 ->
                   9330, FinishSucceeded=1 -> 9331); the upload requires exactly FinishSucceeded (9331)
       9338        ReplayManager.StartPlayback entered

   The probes are `b CAVE` hooks plus compact caves in already return-stubbed dead bodies (verified with a
   whole-.so branch sweep). The caves call the shared DIAG LOG helper at 0x13BC348 (w0 = value; it clobbers
   x0/w0, so each cave saves x0, and the entry hooks also save x30 around their `bl`).

Cave rules honoured (AGENTS.md / scripts/re/README.md)
-----------------------------------------------------
* Hosts are entry-`ret`-stubbed and nothing outside the host function branches into the rewritten window
  (`external_branches_into`, same sweep as scripts/re/replay_upload_cave.py).
* Hooks are `b` (never `bl`); a cave that calls the LOG helper saves/restores x0, and entry-hook caves also
  save/restore x30 before their `bl`.
* Every cave re-executes the displaced instruction and branches to the original continuation (the
  `b <entry+4>` / `b <hook+4>` rule); no cave relies on `ret` to a hook.
* The LOG helper is only `bl`ed, never `UnityEngine.Debug.Log` (crashes under ndk_translation).

    python scripts/re/replay_diag_caves.py     # prints the patch-table entries
"""
from __future__ import annotations

import array
import os
import sys

from keystone import KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN, Ks

_ks = Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN)

LIB = os.environ.get("KF_CLEAN_LIBIL2CPP") or os.path.join(
    os.path.dirname(__file__), "..", "..", ".local", "re", "lib", "arm64-v8a", "libil2cpp.so")
LOG = 0x13BC348                     # DIAG region-A logger: w0 = value
PHOTON_GETTER_HOOK = 0x1773670      # ReplayManager.get_ReplayMode (body reused after this)
PHOTON_GETTER_DISPLACED = bytes.fromhex("f30f1ef8")  # str x19, [sp, #-0x20]! (not used; hook is a full b)

# --- dead-body windows (return-stubbed entry, free in the required flavours) ------------------------------------
# (host_entry, window_lo, window_hi, what_is_stubbed)
HOST_GETTER = (0x2F277B8, 0x2F277C0, 0x2F278A4,
               "System.Collections.Generic.List<LocalClient.InternalMsg>.Contains -> mov w0,wzr; ret")
HOST_B = (0x13ED894, 0x13ED8FC, 0x13ED998,
          "NormalMatchingController.<CallbackBattleStartSuccess>b__46_0 -> mov w0,#1; ret")
HOST_C = (0x156D7D8, 0x156D7E0, 0x156D834,
          "GameManager.get_IsAllPlayerLoaded -> mov w0,#1; ret")

# --- DIAG hook sites --------------------------------------------------------------------------------------------
# (name, hook_rva, displaced_len_bytes_checked, mnemonic_check)
HOOKS = {
    "begin":       0x17748C0,   # BeginSession entry: stp x20,x19,[sp,#-0x20]!
    "canbegin":    0x1774924,   # after `bl CanBeginSession`: tbz w0,#0,#0x1774960
    "recorded":    0x177495C,   # after `bl BeginRecordingSession`: b #0x177496c
    "end":         0x1774BAC,   # EndSession entry: stp x20,x19,[sp,#-0x20]!
    "upload":      0x18A8AEC,   # UploadReplayDataAsync MoveNext state 0: mov w8,#-1
    "master":      0x18A8AFC,   # tbz w0,#0,#0x18a8df0 (IsMyPlayerMaster)
    "uploadflag":  0x18A8B40,   # tbz w0,#0,#0x18a8df0 (IsUploadReplayData)
    "battleid":    0x18A8B9C,   # tbnz w0,#0,#0x18a8df0 (String.IsNullOrEmpty(BattleId))
    "writestate":  0x18A8C14,   # cmp w0,#1 (WriteState)
    "playback":    0x177473C,   # StartPlayback entry: stp x22,x21,[sp,#-0x30]!
}

# The value of each `b <hook>` must fit the host cave window; assembled below in order.
GETTER_SRC = f"""
adrp x8, #0x447a000
ldr  x8, [x8, #0x5c0]
ldr  x0, [x8]
ldrb w9, [x0, #0x127]
tbz  w9, #1, #classok
ldr  w9, [x0, #0xd8]
cbnz w9, #classok
stp  x29, x30, [sp, #-0x10]!
bl   #0x11f7160
ldp  x29, x30, [sp], #0x10
adrp x8, #0x447a000
ldr  x8, [x8, #0x5c0]
ldr  x0, [x8]
classok:
ldr  x8, [x0, #0xb8]
ldr  w0, [x8]
ret
"""

# Probe caves. `{{LOG}}` is the logger; continuations are the pristine instruction after the hook.
CAVE_SRC = {
    "begin": f"""
stp x0, x30, [sp, #-0x10]!
mov w0, #9303
bl  #{{log:#x}}
ldp x0, x30, [sp], #0x10
str x21, [sp, #-0x30]!
b   #0x17748C4
""",
    "canbegin": f"""
str x0, [sp, #-0x10]!
mov w9, #9304
add w0, w0, w9
bl  #{{log:#x}}
ldr x0, [sp], #0x10
tbz w0, #0, #skip
b   #0x1774928
skip:
b   #0x1774960
""",
    "recorded": f"""
str x0, [sp, #-0x10]!
cbz x0, #done
mov w0, #9306
bl  #{{log:#x}}
done:
ldr x0, [sp], #0x10
b   #0x177496C
""",
    "end": f"""
stp x0, x30, [sp, #-0x10]!
mov w0, #9307
bl  #{{log:#x}}
ldp x0, x30, [sp], #0x10
stp x20, x19, [sp, #-0x20]!
b   #0x1774BB0
""",
    "upload": f"""
str x0, [sp, #-0x10]!
mov w0, #9310
bl  #{{log:#x}}
ldr x0, [sp], #0x10
mov w8, #-1
b   #0x18A8AF0
""",
    "master": f"""
str x0, [sp, #-0x10]!
mov w9, #9311
add w0, w0, w9
bl  #{{log:#x}}
ldr x0, [sp], #0x10
tbz w0, #0, #skip
b   #0x18A8B00
skip:
b   #0x18a8df0
""",
    "uploadflag": f"""
str x0, [sp, #-0x10]!
mov w9, #9313
add w0, w0, w9
bl  #{{log:#x}}
ldr x0, [sp], #0x10
tbz w0, #0, #skip
b   #0x18A8B44
skip:
b   #0x18a8df0
""",
    "battleid": f"""
str x0, [sp, #-0x10]!
mov w9, #9315
add w0, w0, w9
bl  #{{log:#x}}
ldr x0, [sp], #0x10
tbnz w0, #0, #skip
b   #0x18A8BA0
skip:
b   #0x18a8df0
""",
    "writestate": f"""
str x0, [sp, #-0x10]!
mov w9, #9330
add w0, w0, w9
bl  #{{log:#x}}
ldr x0, [sp], #0x10
cmp w0, #1
b   #0x18A8C18
""",
    "playback": f"""
stp x0, x30, [sp, #-0x10]!
mov w0, #9338
bl  #{{log:#x}}
ldp x0, x30, [sp], #0x10
stp x22, x21, [sp, #-0x30]!
b   #0x1774740
""",
}


def asm_block(text: str, base: int) -> bytes:
    """Assemble arm64 source with label support (keystone takes absolute branch targets)."""
    lines = [ln.split(";")[0].strip() for ln in text.strip().splitlines()]
    lines = [ln for ln in lines if ln]
    labels, addr = {}, base
    for ln in lines:
        if ln.endswith(":"):
            labels[ln[:-1]] = addr
        else:
            addr += 4
    out, addr = bytearray(), base
    for ln in lines:
        if ln.endswith(":"):
            continue
        txt = ln.replace("{log:#x}", hex(LOG)) if "{log:#x}" in ln else ln
        for name, target in labels.items():
            txt = txt.replace(f"#{name}", f"#{target:#x}")
        enc, _ = _ks.asm(txt, addr)
        if enc is None:
            raise SystemExit(f"asm failed at {addr:#x}: {txt}")
        out += bytes(enc)
        addr += 4
    return bytes(out)


def single(text: str, base: int) -> bytes:
    enc, _ = _ks.asm(text, base)
    if enc is None:
        raise SystemExit("asm failed: " + text)
    return bytes(enc)


def branch_target(pc: int, word: int):
    """Decode b/bl/b.cond/cbz/cbnz/tbz/tbnz; None for anything else (same as check_cave_hosts.py)."""
    op = word >> 26
    if op in (0b000101, 0b100101):
        imm = word & 0x3FFFFFF
        imm -= (1 << 26) if imm & (1 << 25) else 0
        return pc + imm * 4
    if (word & 0xFF000010) == 0x54000000 or (word & 0x7E000000) == 0x34000000:
        imm = (word >> 5) & 0x7FFFF
        imm -= (1 << 19) if imm & (1 << 18) else 0
        return pc + imm * 4
    if (word & 0x7E000000) == 0x36000000:
        imm = (word >> 5) & 0x3FFF
        imm -= (1 << 14) if imm & (1 << 13) else 0
        return pc + imm * 4
    return None


_BRANCHES: list | None = None


def _all_branches(lib: bytes):
    """One whole-.so pass: sorted (target, source) for every branch, reused by every window sweep."""
    global _BRANCHES
    if _BRANCHES is None:
        words = array.array("I")
        words.frombytes(lib[: len(lib) // 4 * 4])
        _BRANCHES = sorted(
            (target, index * 4)
            for index, word in enumerate(words)
            for target in (branch_target(index * 4, word),)
            if target is not None
        )
    return _BRANCHES


def external_branches_into(lib: bytes, lo: int, hi: int, function_lo: int, function_hi: int):
    import bisect
    branches = _all_branches(lib)
    targets = [t for t, _ in branches]
    hits = []
    i = bisect.bisect_left(targets, lo)
    while i < len(branches) and branches[i][0] < hi:
        target, source = branches[i]
        if not (function_lo <= source < function_hi):
            hits.append((source, target))
        i += 1
    return hits


def entry(desc: str, offset: int, code: bytes, lib: bytes) -> str:
    expected = bytes(lib[offset:offset + len(code)])
    return (f'    {{"description": "{desc}", "offset": {offset:#x}, '
            f'"expected": bytes.fromhex("{expected.hex()}"), '
            f'"replacement": bytes.fromhex("{code.hex()}")}},')


def hook(desc: str, offset: int, original: bytes, replacement: bytes) -> str:
    return (f'    {{"description": "{desc}", "offset": {offset:#x}, '
            f'"expected": bytes.fromhex("{original.hex()}"), '
            f'"replacement": bytes.fromhex("{replacement.hex()}")}},')


def main() -> None:
    lib = open(LIB, "rb").read()

    # 1) How many bytes does each cave need? Verify the hook's displaced instruction is what we think.
    expected_hook_bytes = {
        "begin": "f50f1df8", "canbegin": "e0010036", "recorded": "04000014", "end": "f44fbea9",
        "upload": "08008012", "master": "a0170036", "uploadflag": "80150036", "battleid": "a0120037",
        "writestate": "1f040071", "playback": "f657bda9",
    }
    for key, off in HOOKS.items():
        got = lib[off:off + 4].hex()
        assert got == expected_hook_bytes[key], f"{key} @{off:#x}: expected {expected_hook_bytes[key]}, found {got}"

    # 2) Assemble the getter cave and every DIAG cave (placeholder base for sizing only).
    getter = asm_block(GETTER_SRC, HOST_GETTER[1])
    caves: dict[str, bytes] = {}
    for key, src in CAVE_SRC.items():
        caves[key] = asm_block(src, 0x1000)  # placeholder base; reassembled at the final address below

    print("; getter cave", len(getter), "B ->", HOST_GETTER[2] - HOST_GETTER[1], "B window")
    for key in caves:
        print(";", key, "cave", len(caves[key]), "B")

    # 3) Allocate: getter first (Photon production), then DIAG caves after it in the same window, then B, then C.
    allocations: dict[str, int] = {}
    cursor = HOST_GETTER[1] + len(getter)
    for key in ("begin", "canbegin", "recorded", "end", "upload", "master", "uploadflag", "battleid",
                "writestate", "playback"):
        size = len(asm_block(CAVE_SRC[key], 0x1000))
        if cursor + size > HOST_GETTER[2]:
            break
        allocations[key] = cursor
        cursor += size
    # remaining probes -> host B, then host C
    pending = [k for k in CAVE_SRC if k not in allocations]
    for host in (HOST_B, HOST_C):
        cursor = host[1]
        for key in list(pending):
            size = len(asm_block(CAVE_SRC[key], 0x1000))
            if cursor + size > host[2]:
                continue
            allocations[key] = cursor
            cursor += size
            pending.remove(key)
    if pending:
        raise SystemExit("no room for probes: " + ", ".join(pending))

    # 4) Reassemble each cave at its final address (the `bl LOG` and internal branches are PC-relative).
    final: dict[str, bytes] = {}
    for key, off in allocations.items():
        final[key] = asm_block(CAVE_SRC[key], off)

    # 4b) Guard against silent truncation: keystone wraps an out-of-range conditional branch (tbz/tbnz/cbz/cbnz
    # are +/-32 KB) without error. Every conditional must stay inside its own cave; far continuations use `b`.
    for name, code, base in [("getter", getter, HOST_GETTER[1])] + \
            [(k, final[k], allocations[k]) for k in final]:
        for i in range(0, len(code), 4):
            word = int.from_bytes(code[i:i + 4], "little")
            target = branch_target(base + i, word)
            if target is None:
                continue
            is_cond = ((word & 0xFF000010) == 0x54000000 or (word & 0x7E000000) == 0x34000000
                       or (word & 0x7E000000) == 0x36000000)
            if is_cond:
                assert base <= target < base + len(code), \
                    f"{name}: conditional branch @{base + i:#x} -> {target:#x} outside the cave"

    # 5) Verify the rewritten windows and sweep for incoming branches from outside the host function.
    windows = [(HOST_GETTER[1], HOST_GETTER[1] + len(getter), HOST_GETTER[0], 0x2F278A4, "getter")]
    for key, off in allocations.items():
        host = HOST_GETTER if HOST_GETTER[1] <= off < HOST_GETTER[2] else (
            HOST_B if HOST_B[1] <= off < HOST_B[2] else HOST_C)
        windows.append((off, off + len(final[key]), host[0], host[2], key))
    for lo, hi, host_entry, host_hi, name in windows:
        assert hi <= host_hi, f"{name} overflows its host"
        outside = external_branches_into(lib, lo, hi, host_entry, host_hi)
        assert not outside, (f"{name}: incoming branch(es): "
                             + ", ".join(f"{s:#x}->{t:#x}" for s, t in outside))

    # 6) Print the patch-table entries.
    out = []
    out.append("    # ---- (KF_PHOTON only) real ReplayManager.get_ReplayMode: entry -> getter cave ----")
    out.append("    # The offline flow stubs 0x1773670 to `mov w0,wzr; ret`; Photon needs the real static")
    out.append("    # <ReplayMode> (StartPlayback sets it to Playback=1, BeginSession/CanBeginSession read it).")
    out.append("    # Generated by scripts/re/replay_diag_caves.py.")
    out.append("    *([{")
    out.append(entry("cave: ReplayManager.get_ReplayMode re-implementation (class-init + real static <ReplayMode>)"
                     " in the dead body of List<LocalClient.InternalMsg>.Contains", HOST_GETTER[1], getter, lib))
    out.append(hook("ReplayManager.get_ReplayMode entry -> b real-getter cave (Photon; the offline stub keeps the"
                    " body for the IsMine/SetState caves)", PHOTON_GETTER_HOOK,
                    lib[PHOTON_GETTER_HOOK:PHOTON_GETTER_HOOK + 4],
                    single(f"b {HOST_GETTER[1]:#x}", PHOTON_GETTER_HOOK)))
    out.append("    }] if PHOTON_FLOW else []),")
    out.append("")
    out.append("    # ---- DIAG (KFDIAG 9303-9338): replay recording/upload/playback probes ----")
    out.append("    # Generated by scripts/re/replay_diag_caves.py. Hooks are `b cave`; caves save x0 (LOG clobbers")
    out.append("    # it) and entry hooks also save x30; each cave replays its displaced instruction and branches to")
    out.append("    # the original continuation.")
    names = {"begin": "BeginSession entered", "canbegin": "CanBeginSession result (9304 false / 9305 true)",
             "recorded": "recording session created", "end": "EndSession entered", "upload": "UploadReplayDataAsync entered",
             "master": "upload gate IsMyPlayerMaster (9311 false / 9312 true)",
             "uploadflag": "upload gate IsUploadReplayData (9313 false / 9314 true)",
             "battleid": "upload gate BattleId (9315 non-empty / 9316 empty)",
             "writestate": "upload gate WriteState raw (9329 Invalid / 9330 Progress / 9331 FinishSucceeded)",
             "playback": "StartPlayback entered"}
    for key in ("begin", "canbegin", "recorded", "end", "upload", "master", "uploadflag", "battleid",
                "writestate", "playback"):
        off = allocations[key]
        out.append(entry(f"DIAG cave: {names[key]} (dead body reused; {len(final[key])} B)", off, final[key], lib))
        o = lib[HOOKS[key]:HOOKS[key] + 4]
        out.append(hook(f"DIAG hook: {names[key]} @0x{HOOKS[key]:x} -> b cave", HOOKS[key], o,
                        single(f"b {off:#x}", HOOKS[key])))
    out.append("    # ---- END DIAGNOSTIC ----")
    print("\n".join(out))
    print(f"# getter={len(getter)} B at {HOST_GETTER[1]:#x}; "
          f"DIAG caves {sum(len(v) for v in final.values())} B in {len(final)} blocks", file=sys.stderr)


if __name__ == "__main__":
    main()
