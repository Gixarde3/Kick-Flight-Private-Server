"""Cave generator for the custom-battle replay-upload flag (handoff/dsh-replay-2).

Goal
----
The stock client only uploads a replay when `ArchiveData.IsUploadReplayData` is true. `/battle/end` carries
`BattleEndResponseData.replayUploadFlag` and `GameManager.CallbackBattleEndSuccess` (0x156CEB8) copies it:

    0x156CF18  bl  Colorful.ColorfulManager.get_Archive      -> x21 = ArchiveData
    0x156CF2C  ldrb w20, [x20, #0x10]                        ; response.replayUploadFlag
    0x156CF3C  cmp  w20, #0
    0x156CF40  cset w1, ne
    0x156CF48  bl  Colorful.ArchiveData.set_IsUploadReplayData (0x31F52C0)

`/customBattle/end` answers the field-less `CustomBattleEndResponseData`, and its callback
`GameManager.CallbackCustomBattleEndSuccess` (0x156D5A0) never calls the setter (it only tail-calls
`UpdateRoomState`). This cave sets the flag itself at the callback entry, using the **same** ArchiveData
instance the normal path uses: `ColorfulManager.get_Archive()` (0x31DC818), nothing else.

Cave (entry hook: `b` + jump back, no `bl` from the hook itself)
----------------------------------------------------------------
    ; 0x156D5A0 is hooked:  stp x20, x19, [sp, #-0x20]! -> b CAVE
    stp x0, x1, [sp, #-0x20]!      ; preserve the callback's argument registers
    stp x2, x30, [sp, #0x10]
    bl  ColorfulManager.get_Archive ; x0 = ArchiveData
    mov w1, #1
    bl  ArchiveData.set_IsUploadReplayData
    ldp x2, x30, [sp, #0x10]       ; restore x30 (the cave called) and x2
    ldp x0, x1, [sp], #0x20
    stp x20, x19, [sp, #-0x20]!    ; displaced instruction, re-executed
    b   0x156D5A4                  ; resume after the displaced instruction

Dead body (entry-stubbed in EVERY flavour, no incoming branch)
--------------------------------------------------------------
`PlayerBoneController.SetPose` 0x13BA8F4 is return-stubbed at its entry in production (0x13BA8F4 -> `ret`).
Its tail 0x13BAA50-0x13BAA7C (44 B) is free in every build flavour: the DIAG attack-probe caves end at
0x13BAA50 and nothing else writes there. A branch sweep over the whole pristine .so finds no branch from
outside the function into the tail. `SetPose` is one of the dead bodies listed in `scripts/re/README.md`
("PlayerBoneController.InterpolationUpdate / SetPose / LateUpdate (attack probes)").

    python scripts/re/replay_upload_cave.py   # prints the production entries to paste
"""
from __future__ import annotations

import array
import os
import sys

from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN

_ks = Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN)

# --- client symbols ---------------------------------------------------------------------------------------------
CALLBACK_CUSTOM_END = 0x156D5A0     # Colorful.GameManager.CallbackCustomBattleEndSuccess
CALLBACK_CUSTOM_RESUME = 0x156D5A4  # after the displaced `stp x20, x19, [sp, #-0x20]!`
DISPLACED = bytes.fromhex("f44fbea9")  # stp x20, x19, [sp, #-0x20]!
GET_ARCHIVE = 0x31DC818             # Colorful.ColorfulManager.get_Archive() -> ArchiveData
SET_UPLOAD_FLAG = 0x31F52C0         # Colorful.ArchiveData.set_IsUploadReplayData(bool)

# --- dead body --------------------------------------------------------------------------------------------------
# PlayerBoneController.SetPose is return-stubbed at 0x13BA8F4; its tail after the DIAG attack caves is free.
CAVE_BODY = 0x13BAA50
CAVE_END = 0x13BAA7C
FUNCTION_ENTRY = 0x13BA8F4
FUNCTION_END = 0x13BAA7C

LIB = os.environ.get("KF_CLEAN_LIBIL2CPP") or os.path.join(
    os.path.dirname(__file__), "..", "..", ".local", "re", "lib", "arm64-v8a", "libil2cpp.so")

CAVE_SRC = f"""
stp x0, x1, [sp, #-0x20]!          ; preserve the callback arguments
stp x2, x30, [sp, #0x10]           ; ... and x30: the cave calls, so it must save/restore the caller's LR
bl  {GET_ARCHIVE:#x}               ; x0 = ColorfulManager.get_Archive()
mov w1, #1
bl  {SET_UPLOAD_FLAG:#x}           ; ArchiveData.IsUploadReplayData = true
ldp x2, x30, [sp, #0x10]
ldp x0, x1, [sp], #0x20
stp x20, x19, [sp, #-0x20]!        ; displaced instruction
b   {CALLBACK_CUSTOM_RESUME:#x}
"""


def asm_block(text: str, base: int) -> bytes:
    lines = [ln.split(";")[0].strip() for ln in text.splitlines()]
    src = "\n".join(ln for ln in lines if ln)
    encoded, _ = _ks.asm(src, base)
    if encoded is None:
        raise SystemExit("asm failed at " + hex(base) + ":\n" + src)
    return bytes(encoded)


def single(text: str, base: int) -> bytes:
    encoded, _ = _ks.asm(text, base)
    if encoded is None:
        raise SystemExit("asm failed: " + text)
    return bytes(encoded)


def branch_target(pc: int, word: int) -> int | None:
    """Decode b/bl/b.cond/cbz/cbnz/tbz/tbnz, else None (same decoder as check_cave_hosts.py)."""
    op = word >> 26
    if op in (0b000101, 0b100101):
        imm = word & 0x3FFFFFF
        if imm & (1 << 25):
            imm -= 1 << 26
        return pc + imm * 4
    if (word & 0xFF000010) == 0x54000000 or (word & 0x7E000000) == 0x34000000:
        imm = (word >> 5) & 0x7FFFF
        if imm & (1 << 18):
            imm -= 1 << 19
        return pc + imm * 4
    if (word & 0x7E000000) == 0x36000000:
        imm = (word >> 5) & 0x3FFF
        if imm & (1 << 13):
            imm -= 1 << 14
        return pc + imm * 4
    return None


def external_branches_into(lib: bytes, lo: int, hi: int, function_lo: int, function_hi: int) -> list[tuple[int, int]]:
    """Branches whose source is outside [function_lo, function_hi) and whose target is in [lo, hi)."""
    words = array.array("I")
    words.frombytes(lib[: len(lib) // 4 * 4])
    hits = []
    for index, word in enumerate(words):
        target = branch_target(index * 4, word)
        if target is not None and lo <= target < hi and not (function_lo <= index * 4 < function_hi):
            hits.append((index * 4, target))
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

    # 1. the hook site must hold the displaced instruction.
    got = lib[CALLBACK_CUSTOM_END:CALLBACK_CUSTOM_END + 4]
    assert got == DISPLACED, f"{CALLBACK_CUSTOM_END:#x}: expected {DISPLACED.hex()}, found {got.hex()}"

    # 2. assemble and check the window.
    cave = asm_block(CAVE_SRC, CAVE_BODY)
    assert CAVE_BODY + len(cave) <= CAVE_END, f"cave {len(cave)} B overflows {CAVE_BODY:#x}..{CAVE_END:#x}"
    hook_code = single(f"b {CAVE_BODY:#x}", CALLBACK_CUSTOM_END)

    # 3. no branch from outside the (entry-stubbed) function reaches the bytes this cave rewrites.
    outside = external_branches_into(lib, CAVE_BODY, CAVE_BODY + len(cave), FUNCTION_ENTRY, FUNCTION_END)
    assert not outside, "incoming branch(es) into the dead body: " + ", ".join(f"{s:#x}->{t:#x}" for s, t in outside)

    out = []
    out.append("    # ---- Custom-battle replay upload: set ArchiveData.IsUploadReplayData in the custom end callback ----")
    out.append("    # GameManager.CallbackCustomBattleEndSuccess (0x156D5A0) never sets the flag (CallbackBattleEndSuccess")
    out.append("    # does, via ColorfulManager.get_Archive 0x31DC818 -> ArchiveData.set_IsUploadReplayData 0x31F52C0).")
    out.append("    # Entry hook + cave rebuild the normal path's store; both callbacks share the same ArchiveData instance.")
    out.append("    # Dead body: entry-stubbed PlayerBoneController.SetPose 0x13BA8F4, free tail 0x13BAA50-0x13BAA7C (all flavours).")
    out.append(entry(
        "cave: CallbackCustomBattleEndSuccess entry -> ArchiveData.set_IsUploadReplayData(true) so custom-battle replays "
        "upload (dead tail of PlayerBoneController.SetPose)",
        CAVE_BODY, cave, lib))
    out.append(hook(
        "GameManager.CallbackCustomBattleEndSuccess `stp x20,x19,[sp,#-0x20]!` -> b custom-battle upload-flag cave",
        CALLBACK_CUSTOM_END, got, hook_code))
    print("\n".join(out))
    print(f"# sizes: cave={len(cave)} B, hook={hook_code.hex()}", file=sys.stderr)


if __name__ == "__main__":
    main()
