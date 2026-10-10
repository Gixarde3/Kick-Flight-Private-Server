"""handoff/claude-replay-5: KF_PHOTON-only caves for replay issues 1 and 2 (+ issue 5 one-word patch).

Host: dead body of NormalMatchingJoinBattleRoomState.GetDelayTime (0x13EFE74). Its entry is
`fmov s0, wzr; ret`-stubbed ONLY when PHOTON_FLOW, so these caves must be emitted only for KF_PHOTON=1
(non-Photon tables stay byte-identical; the body is live code there and is never touched).

Issue 1 (home map overlaid on replay): ResultScene.<PostEndAsync> state that unregisters ResultManager
(0x18B14C0..0x18B1514). Because production starts ResultManager.BeginAsync directly (0x18B18C4) it is never
in SystemManager, so UnregisterManagerAsync is a no-op and ResultManager.<EndAsync> (0x18A80AC: ...
PhotonManager.Disconnect + PhotonManager.Reset) never runs. Cave R re-adds exactly those two calls.
  hook 0x18B1500 `mov x0, x20` -> b caveR ; caveR: Disconnect(); Reset(); mov x0,x20; b 0x18B1504

Issue 2 (playback clock starts under the intro): READY_SCENE GameStartPresenter gate cave (0x1579AD0) is
IsAllPlayerLoaded && RoomState >= Playing. In playback RoomState=Playing arrives with the pre-start replay
frames at BeginAsync state 11, so READY/GO + PlayerState 4 + RoomStartTime fire ~15 s early. Cave G wraps it:
  gate = caveA() && (!ReplayManager.IsPlaybackSession || localPlayer.PlayerState >= Readied(3))
  hook: the existing READY_SCENE call-site patch 0x1763FE0 becomes `bl caveG` for PHOTON_FLOW.

Issue 5 (flag-rule replay hangs): b__6 calls IsCreatedGuardian(this, 1) (the leftover `mov w1,#1` of the
original IsCreatedCommonObject(true) call). Flag rules have guardianAmount 0 -> GetNpcs().Count never >= 1.
Patch 0x1579C60 `mov w1, #1` -> `mov w1, #-1` (use the field's guardian-point count: 0 for fldNNNNN_2).

Run with Windows python (keystone + capstone): python scripts/re/replay5_caves.py
"""
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN

REPO = Path(__file__).resolve().parents[2]
LIB = (REPO / ".local/re/lib/arm64-v8a/libil2cpp.so").read_bytes()
ks = Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN)
cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)

HOST_ENTRY, HOST_END = 0x13EFE74, 0x13F016C
CAVE_R = 0x13EFE80
CAVE_G = 0x13EFEA0

DISCONNECT, RESET = 0x18D6A80, 0x18D603C
GATE_A = 0x1579AD0
CLASS_INIT = 0x11F7160
IS_PLAYBACK = 0x17738F0
GET_LOCAL_PLAYER = 0x18D6BFC
GET_PLAYER_PROP = 0x19F5C5C           # PhotonUtil.GetPlayerProperty<Int32Enum>
SLOT_REPLAY_TYPEINFO = 0x447A5C0       # Colorful.ReplayManager_TypeInfo (as in 0x157A3B4)
SLOT_STR_PLAYERSTATE = 0x4491410       # "PlayerState" (as in GameManager.UpdateState 0x156EAFC)
SLOT_M_GETPLAYERPROP = 0x4416738       # Method$PhotonUtil.GetPlayerProperty<PhotonPlayerStateType>() (0x156EB00)


def asm(lines, base):
    out = b""
    for ln in lines:
        enc, _ = ks.asm(ln, base + len(out))
        out += bytes(enc)
    return out


def page(a):
    return a & ~0xFFF


cave_r = asm([
    "mov x0, xzr",
    f"bl {DISCONNECT:#x}",
    "mov x0, xzr",
    f"bl {RESET:#x}",
    "mov x0, x20",                 # displaced instruction
    "b 0x18b1504",
], CAVE_R)

g = CAVE_G
cave_g_src = [
    "stp x29, x30, [sp, #-0x10]!",
    "mov x29, sp",
    f"bl {GATE_A:#x}",
    "cbz w0, #DONE",
    f"adrp x8, {page(SLOT_REPLAY_TYPEINFO):#x}",
    f"ldr x8, [x8, #{SLOT_REPLAY_TYPEINFO & 0xFFF:#x}]",
    "ldr x0, [x8]",
    "ldrb w8, [x0, #0x127]",
    "tbz w8, #1, #INITED",
    "ldr w8, [x0, #0xd8]",
    "cbnz w8, #INITED",
    f"bl {CLASS_INIT:#x}",
    "INITED: mov x0, xzr",
    f"bl {IS_PLAYBACK:#x}",
    "tbz w0, #0, #TRUE",
    "mov x0, xzr",
    f"bl {GET_LOCAL_PLAYER:#x}",
    f"adrp x8, {page(SLOT_STR_PLAYERSTATE):#x}",
    f"ldr x8, [x8, #{SLOT_STR_PLAYERSTATE & 0xFFF:#x}]",
    f"adrp x9, {page(SLOT_M_GETPLAYERPROP):#x}",
    f"ldr x9, [x9, #{SLOT_M_GETPLAYERPROP & 0xFFF:#x}]",
    "mov w2, wzr",
    "ldr x1, [x8]",
    "ldr x3, [x9]",
    f"bl {GET_PLAYER_PROP:#x}",
    "cmp w0, #3",
    "cset w0, ge",
    "b #DONE",
    "TRUE: mov w0, #1",
    "DONE: ldp x29, x30, [sp], #0x10",
    "ret",
]


def asm_labels(src, base):
    # two-pass: resolve labels by index (every instruction is 4 bytes)
    labels, body = {}, []
    for i, ln in enumerate(src):
        if ":" in ln.split()[0]:
            lab, ln = ln.split(":", 1)
            labels[lab.strip()] = base + 4 * i
        body.append(ln.strip())
    out = b""
    for i, ln in enumerate(body):
        for lab, addr in labels.items():
            ln = ln.replace(f"#{lab}", f"{addr:#x}")
        enc, _ = ks.asm(ln, base + 4 * i)
        assert len(enc) == 4, ln
        out += bytes(enc)
    return out


cave_g = asm_labels(cave_g_src, CAVE_G)
assert CAVE_R + len(cave_r) <= CAVE_G and CAVE_G + len(cave_g) <= HOST_END


def bl_to(src, dst, link=True):
    imm = ((dst - src) >> 2) & 0x3FFFFFF
    return struct.pack("<I", (0x94000000 if link else 0x14000000) | imm)


def branch_target(pc, w):
    op = w >> 26
    if op in (0b000101, 0b100101):
        imm = w & 0x3FFFFFF
        imm -= (1 << 26) if imm & (1 << 25) else 0
        return pc + imm * 4
    if (w & 0xFF000010) == 0x54000000 or (w & 0x7E000000) == 0x34000000:
        imm = (w >> 5) & 0x7FFFF
        imm -= (1 << 19) if imm & (1 << 18) else 0
        return pc + imm * 4
    if (w & 0x7E000000) == 0x36000000:
        imm = (w >> 5) & 0x3FFF
        imm -= (1 << 14) if imm & (1 << 13) else 0
        return pc + imm * 4
    return None


def sweep(lo, hi, host_lo, host_hi):
    """Branches from outside [host_lo, host_hi) into [lo, hi) anywhere in .text."""
    hits = []
    n = len(LIB) & ~3
    for pc in range(0x1000000, min(n, 0x3300000), 4):
        if host_lo <= pc < host_hi:
            continue
        t = branch_target(pc, struct.unpack_from("<I", LIB, pc)[0])
        if t is not None and lo <= t < hi:
            hits.append((pc, t))
    return hits


def dis(code, base):
    return "\n".join(f"    {i.address:#x}  {i.mnemonic:6s} {i.op_str}" for i in cs.disasm(code, base))


def entry(desc, off, rep):
    exp = LIB[off:off + len(rep)]
    return f'{{"description": "{desc}", "offset": {off:#x}, "expected": bytes.fromhex("{exp.hex()}"), "replacement": bytes.fromhex("{rep.hex()}")}},'


hook_r = bl_to(0x18B1500, CAVE_R, link=False)
hook_g = bl_to(0x1763FE0, CAVE_G, link=True)
issue5 = asm(["mov w1, #-1"], 0x1579C60)

assert LIB[0x18B1500:0x18B1504] == bytes.fromhex("e00314aa")       # mov x0, x20
assert LIB[0x1763FE0:0x1763FE4] == bytes.fromhex("fe25f897")       # pristine bl get_IsAllPlayerLoaded
assert LIB[0x1579C60:0x1579C64] == bytes.fromhex("e1030032")       # mov w1, #1
assert LIB[HOST_ENTRY:HOST_ENTRY + 8] == bytes.fromhex("ff4302d1e82300fd")

print("# caveR\n" + dis(cave_r, CAVE_R))
print("# caveG\n" + dis(cave_g, CAVE_G))
print("# branch sweep into the cave window from outside GetDelayTime:",
      sweep(CAVE_R, CAVE_G + len(cave_g), HOST_ENTRY, HOST_END) or "none")
print()
print(entry("Photon cave: ResultScene.PostEndAsync -> PhotonManager.Disconnect + Reset (what the never-run ResultManager.EndAsync does) (dead body of GetDelayTime, Photon-stubbed)", CAVE_R, cave_r))
print(entry("Photon hook: ResultScene.<PostEndAsync> ResultManager-unregister state `mov x0, x20` -> b Disconnect/Reset cave", 0x18B1500, hook_r))
print(entry("Photon cave: GameStartPresenter gate -> ready-gate cave && (!IsPlaybackSession || local PlayerState >= Readied) (dead body of GetDelayTime, Photon-stubbed)", CAVE_G, cave_g))
print(f"# READY_SCENE hook 0x1763FE0 replacement for PHOTON_FLOW: {hook_g.hex()}  (non-Photon keeps bc56f897)")
print(entry("Photon: <BeginAsync>b__6 IsCreatedGuardian(this, 1) -> (this, -1): wait for the field's guardian points (0 on flag fields)", 0x1579C60, issue5))
