"""DIAG probes for the silent in-match character voices / SFX (2026-10-05).

Symptom: during a battle no kicker voice or character SE is heard, while the 2D countdown SE (in_game_se) and the
results screen (2D, local) play. In-match voices/SE are 3D and played only on RPC receipt:
  PlayerCharacter.AcceptPlayVoice3d -> PlayerRPCController.SendPlayVoice -> SendRPC("ReceivePlayVoice", All)
  -> ReceivePlayVoice -> PlayerCharacter.PlayVoice3d -> AudioManager.PlayVoice3d -> Play3d(GameObject) -> Play3d(source)
  (SE: SendPlayPlayerSe[WithCueSheet] / CharacterRPCControllerBase.SendPlayCharacterSE -> Receive* -> PlaySe3d -> Play3d)
These probes tell apart (a) RPC never sent / received, (b) cue sheet not registered (or AudioManager.IsLockPlay),
(c) the sound starts but the CRI 3D listener is not where the player is.

KFDIAG values (all fixed integers, no account data):
  9200  PlayerRPCController.ReceivePlayVoice entry           9210  PlayerRPCController.SendPlayVoice entry
  (9201-9203 / 9211-9213 = the SE send/receive entries and 9224/9225 = PlayVoice3d/PlaySe3d IsLockPlay returns were
  retired after run 1 of 2026-10-05: every Send had its Receive and no lock path ever fired.)
  9220+lock   Play3d(GameObject) returned 0 early: gameObject null (9220) or IsLockPlay (9221)
  9222+lock, TAG   Play3d(source) returned 0: cue sheet TAG not registered (9222) or IsLockPlay (9223)
  9230+bad, TAG, cueId, 9240+L, [Lx, Lz, Lptr], Sx, Sz, 9248+valid
        Play3d(source) reached CriAtomSource.Play: bad = playback id == -1 (CRI refused it); TAG = cue sheet;
        L = (CriAtomListener.activeListener != null) + 2*(sharedNativeListener != null) (9240..9243, 9239 = class
        not initialised); Lx/Lz = activeListener.lastPosition x/z, Sx/Sz = source lastPosition x/z, both as RAW IEEE
        float bits (decode with struct.unpack('<f', struct.pack('<i', v))); Lptr = activeListener low 32 bits (Lx/Lz/Lptr
        only when activeListener != null); 9248+valid = source hasValidPosition.
  9250+hasPlayer, ptr  GameManager.SetListener entry (reparents the 'Listener' GameObject under the player; with
                  player == null (9250) it returns before doing anything); ptr = player low 32 bits
  9252, ptr       CriAtomListener.ActivateListener entry, this low 32 bits
  9256, ptr, x, z CriAtomListener.LateUpdate when the active listener's x changed: this low32, new x/z raw float bits
  9254+wasActive  CriAtomListener.OnDisable entry (9255 = the active listener is being disabled -> native listener
                  reset to the origin and activeListener = null)
TAG = c0<<24 | c4<<16 | c5<<8 | length of the cue-sheet string ("pc_005_001" -> 'p','0','5',10 = 0x7030350a;
"se_..." starts with 0x73, "in_game_se" with 0x69 = 'i').

Caves live in the dead body of PlayerCharacter.UpdateNoInputTime (0x13CE88C-0x13CEB10; production stubs its entry
0x13CE888 to `ret`, no external branch targets the body - checked with a b/bl/b.cond/cbz/tbz sweep of the whole .so)
and the free gap 0x13CE0E0-0x13CE160 of the entry-stubbed UpdateLookTarget body. Every hook is a `b` (never `bl`) on a
non-branch, non-PC-relative instruction that the cave replays before `b hook+4`; each cave saves/restores x29/x30 and
every scratch register around `bl LOG` (LOG preserves all registers); flags are dead at every hook site.

    python scripts/re/audio_diag_caves.py   # prints the DIAG_PATCHES_ARM64 entries
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from mkcave import LOG, ks  # noqa: E402

LIB = os.path.join(os.path.dirname(__file__), "..", "..", ".local", "re", "lib", "arm64-v8a", "libil2cpp.so")
REGIONS = [(0x13CE88C, 0x13CEB10), (0x13CE0E0, 0x13CE160), (0x13CE070, 0x13CE0A0), (0x13CE4D0, 0x13CE500),
           (0x1570FB8, 0x1570FF0), (0x1570EF8, 0x1570F1C)]
LISTENER_TYPEINFO_PAGE, LISTENER_TYPEINFO_OFF = 0x4458000, 0x840  # meta CriAtomListener_TypeInfo slot

PRO = """
stp x29, x30, [sp, #-0x40]!
stp x0, x1, [sp, #0x10]
stp x9, x10, [sp, #0x20]
stp x11, x12, [sp, #0x30]
"""
EPI = """
ldp x11, x12, [sp, #0x30]
ldp x9, x10, [sp, #0x20]
ldp x0, x1, [sp, #0x10]
ldp x29, x30, [sp], #0x40
"""


PRO_MIN = """
stp x29, x30, [sp, #-0x20]!
str x0, [sp, #0x10]
"""
EPI_MIN = """
ldr x0, [sp, #0x10]
ldp x29, x30, [sp], #0x20
"""


def simple(value):
    return f"mov w0, #{value}\nbl LOG\n"


def tag(reg):
    """Log the packed cue-sheet tag of the il2cpp String* in `reg` (0 if null). Uses x0, x9, x10."""
    return f"""
mov w0, wzr
cbz {reg}, tag_end
ldrh w9, [{reg}, #0x14]
ldrh w10, [{reg}, #0x1c]
lsl w9, w9, #24
orr w9, w9, w10, lsl #16
ldrh w10, [{reg}, #0x1e]
orr w9, w9, w10, lsl #8
ldrb w10, [{reg}, #0x10]
orr w0, w9, w10
tag_end:
bl LOG
"""


PLAY_OK = f"""
cmn w0, #1
cset w0, eq
mov w1, #9230
add w0, w0, w1
bl LOG
{tag("x23")}
mov w0, w19
bl LOG
mov w0, #9239
adrp x9, #{LISTENER_TYPEINFO_PAGE:#x}
ldr x9, [x9, #{LISTENER_TYPEINFO_OFF:#x}]
ldr x9, [x9]
cbz x9, no_listener
tbnz x9, #0, no_listener
ldr x9, [x9, #0xb8]
cbz x9, no_listener
ldr x10, [x9]
ldr x11, [x9, #8]
cmp x10, #0
cset w0, ne
cmp x11, #0
cset w1, ne
add w0, w0, w1, lsl #1
mov w1, #9240
add w0, w0, w1
bl LOG
cbz x10, source_pos
ldr w0, [x10, #0x1c]
bl LOG
ldr w0, [x10, #0x24]
bl LOG
mov w0, w10
bl LOG
b source_pos
no_listener:
bl LOG
source_pos:
ldr w0, [x20, #0x28]
bl LOG
ldr w0, [x20, #0x30]
bl LOG
ldrb w0, [x20, #0x34]
mov w1, #9248
add w0, w0, w1
bl LOG
"""

ON_DISABLE = f"""
mov x12, x0
mov w0, #9254
adrp x9, #{LISTENER_TYPEINFO_PAGE:#x}
ldr x9, [x9, #{LISTENER_TYPEINFO_OFF:#x}]
ldr x9, [x9]
cbz x9, dis_log
tbnz x9, #0, dis_log
ldr x9, [x9, #0xb8]
cbz x9, dis_log
ldr x10, [x9]
cmp x10, x12
cset w1, eq
add w0, w0, w1
dis_log:
bl LOG
"""

PROBES = [
    # (hook addr, displaced instruction, body, description)
    (0x18BB26C, "str x21, [sp, #-0x30]!", simple(9200), "PlayerRPCController.ReceivePlayVoice entry -> 9200"),
    (0x18BB174, "str x21, [sp, #-0x30]!", simple(9210), "PlayerRPCController.SendPlayVoice entry -> 9210"),
    (0x1BD8E64, "mov x0, xzr", """
ldrb w0, [x24, #0xd1]
mov w1, #9220
add w0, w0, w1
bl LOG
""", "AudioManager.Play3d(GameObject) early return -> 9220 + IsLockPlay"),
    (0x1BD8FA0, "mov x0, xzr", """
ldrb w0, [x24, #0xd1]
mov w1, #9222
add w0, w0, w1
bl LOG
""" + tag("x23"), "AudioManager.Play3d(source) cue sheet missing / locked -> 9222 + IsLockPlay, cue-sheet tag"),
    (0x1BD907C, "and x0, x0, #0xffffffff", PLAY_OK,
     "AudioManager.Play3d(source) after CriAtomSource.Play -> 9230+(id==-1), tag, cueId, 9240+listener, Lx, Lz, Sx, Sz, 9248+valid"),
    (0x1570C14, "str x21, [sp, #-0x30]!", """
cmp x1, #0
cset w0, ne
mov w9, #9250
add w0, w0, w9
bl LOG
mov w0, w1
bl LOG
""", "GameManager.SetListener entry -> 9250 + (player != null), player ptr low32"),
    (0x2720494, "stp d15, d14, [sp, #-0x70]!", """
mov x12, x0
mov w0, #9252
bl LOG
mov w0, w12
bl LOG
""", "CriAtomListener.ActivateListener entry -> 9252, this low32"),
    (0x2720A18, "stp s11, s12, [x19, #0x1c]", """
fmov w9, s10
fmov w10, s11
cmp w9, w10
b.eq lu_same
mov w0, #9256
bl LOG
mov w0, w19
bl LOG
fmov w0, s11
bl LOG
fmov w0, s13
bl LOG
lu_same:
""", "CriAtomListener.LateUpdate position store -> 9256, this low32, new x, new z (only when x changed)"),
    (0x27206FC, "str x21, [sp, #-0x30]!", ON_DISABLE, "CriAtomListener.OnDisable entry -> 9254 + (this == activeListener)"),
]


def asm(text, base):
    out = bytearray()
    lines = [ln.split(";")[0].strip() for ln in text.strip().splitlines()]
    lines = [ln.replace("LOG", hex(LOG)) for ln in lines if ln]
    # keystone resolves local numeric labels only within one call, so assemble the whole block at once
    enc, _ = ks.asm("\n".join(lines), base)
    if enc is None:
        raise SystemExit("asm failed")
    out += bytes(enc)
    return bytes(out)


def build():
    lib = open(LIB, "rb").read()
    entries = []
    regions = [list(r) for r in REGIONS]
    # biggest caves first so the small ones fill the leftover gap
    for hook_addr, displaced, body, desc in sorted(PROBES, key=lambda p: -len(p[2])):
        assert lib[hook_addr:hook_addr + 4] == asm(displaced, hook_addr), (desc, lib[hook_addr:hook_addr + 4].hex())
        small = body == simple(int(body.split("#")[1].split()[0])) if body.startswith("mov w0, #") else False
        text = (PRO_MIN + body + EPI_MIN if small else PRO + body + EPI) + displaced + f"\nb #{hook_addr + 4:#x}\n"
        for reg in regions:
            code = asm(text, reg[0])
            if reg[0] + len(code) <= reg[1]:
                break
        else:
            raise SystemExit(f"no room for {desc}")
        cave_addr = reg[0]
        reg[0] = (cave_addr + len(code) + 3) & ~3
        h = asm(f"b #{cave_addr:#x}", hook_addr)
        entries.append(f'    {{"description": "DIAG cave: {desc}", "offset": {cave_addr:#x}, '
                       f'"expected": bytes.fromhex("{lib[cave_addr:cave_addr + len(code)].hex()}"), '
                       f'"replacement": bytes.fromhex("{code.hex()}")}},')
        entries.append(f'    {{"description": "DIAG hook: {desc}", "offset": {hook_addr:#x}, '
                       f'"expected": bytes.fromhex("{lib[hook_addr:hook_addr + 4].hex()}"), '
                       f'"replacement": bytes.fromhex("{h.hex()}")}},')
    sys.stderr.write("free after packing: " + ", ".join(f"{a:#x}-{b:#x}" for a, b in regions) + "\n")
    return entries


if __name__ == "__main__":
    print("\n".join(build()))
