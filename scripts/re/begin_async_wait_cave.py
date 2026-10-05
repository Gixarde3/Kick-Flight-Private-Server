"""Source of the bounded BeginAsync player wait (production) and its exit probe (DIAG) in patch-il2cpp-endpoints.py.

GameManager.<BeginAsync>d__71.MoveNext waits with WaitWhile(<>c__DisplayClass71_0.<BeginAsync>b__3), i.e.
`!IsSkipBeginAcyncWait() && !IsCreatedPlayer()`, before InitializeObject / InitializeUI (InGameUIPresenter.Initialize
builds PlayerLook / PlayerInfo / KillLog / TeamScore presenters once, from the players that exist then). We used to
stub b__3 to `return false` (no wait at all), so those presenters were built before the remote players existed:
missing lock-on icons / untargetable players, HUD placeholders, and SetListener(null) (the audio bug that 15e2957
works around). The wait was stubbed because IsCreatedPlayer is a strict players.Count == PlayerBattleInfos.Count and
the disconnect timer is stubbed too, so one peer that never shows up would hang the loading screen for good.

Production: b__3 rewritten in place (0x1579A38-0x1579AC8, pristine prologue kept byte-for-byte at the same addresses
so the function's .eh_frame CFI still describes the frame):
  return false  if IsSkipBeginAcyncWait (0x156E574)
  return false  if GameManagerBase<GameManager>.IsCreatedPlayer (0x1A247B4, Method* slot 0x43B9820; needs b__3's own
                method-metadata init: flag 0x46CA5F0, token slot 0x43C2F58, bl 0x11E9E10)
  otherwise keep waiting until Time.realtimeSinceStartup (0x27886E8) >= first-poll time + TIMEOUT.
The deadline lives in the display class `roomState` int (+0x18), stored as float bits. That field is NOT free:
b__2 / b__5 pass `ref roomState` to PhotonPropertyManagerBase.IsRoomStateComplete, which writes the room's RoomState
into it on every poll, and MoveNext hands it to the stubbed CheckInitializeError. So "no deadline yet" is detected
as "int value < 0x1000" (a RoomState enum or the 0 from MoveNext 0x1579DB4), never as == 0; a deadline is a float
>= TIMEOUT whose bits are >= 0x41200000. b__5 rewrites the field after this wait, and nothing reads it as a room
state in between except the stubbed CheckInitializeError.
The first-poll branch (store the deadline) lives in the free tail of the <BeginAsync>b__1 body (0x1579984), after
the rush-pursuit cave. x20 is set to 1 once IsCreatedPlayer said no, so the DIAG exit probe can tell a timeout from
the other exits; the production epilogue does not care (x20 is restored from the stack).

DIAG (KF_DIAG=1): the single `eor w0, w0, #1` at `fin` becomes `b DIAG_FIN` (0x1570FB8, dead GetMenuType body).
DIAG_FIN (it returns to the epilogue past the `and`) logs once when the wait ends: KFDIAG 9300 = players created, 9301 = timed out, 9302 = IsSkipBeginAcyncWait
(re-checked there), and keeps the production return value (1 = keep waiting, 0 = done).

    python scripts/re/begin_async_wait_cave.py   # prints expected/replacement hex for the patch table
"""
import os

from keystone import KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN, Ks

B3 = 0x1579A38
B3_END = 0x1579AC8
SET_DEADLINE = 0x1579984          # free tail of <BeginAsync>b__1 (rush pursuit cave ends here)
SET_DEADLINE_END = 0x157999C
DIAG_FIN = 0x1570FB8              # dead GetMenuType body, 0x1570FB8-0x1570FF0
DIAG_FIN_END = 0x1570FF0
LOG = 0x13BC348                   # DIAG region A logger (w0 = value)
TIMEOUT = 10.0
LIB = os.environ.get("KF_CLEAN_LIBIL2CPP") or os.path.join(
    os.path.dirname(__file__), "..", "..", ".local", "re", "lib", "arm64-v8a", "libil2cpp.so")

MAIN = f"""
stp x20, x19, [sp, #-0x20]!
stp x29, x30, [sp, #0x10]
add x29, sp, #0x10
adrp x20, #0x46ca000
ldrb w8, [x20, #0x5f0]
mov x19, x0
tbnz w8, #0, init_done
adrp x8, #0x43c2000
ldr x8, [x8, #0xf58]
ldr w0, [x8]
bl #0x11e9e10
mov w8, #1
strb w8, [x20, #0x5f0]
init_done:
ldr x20, [x19, #0x10]
mov x0, x20
bl #0x156e574
tbnz w0, #0, fin
mov x0, x20
adrp x8, #0x43b9000
ldr x8, [x8, #0x820]
ldr x1, [x8]
bl #0x1a247b4
tbnz w0, #0, fin
mov x20, #1
bl #0x27886e8
ldr w9, [x19, #0x18]
ldr s1, [x19, #0x18]
cmp w9, #0x1000
b.lt #{SET_DEADLINE:#x}
have_deadline:
fcmp s0, s1
cset w0, pl
fin:
{{FIN}}
and w0, w0, #1
epilogue:
ldp x29, x30, [sp, #0x10]
ldp x20, x19, [sp], #0x20
ret
"""

DIAG_SRC = """
cbz w0, keep
mov w0, #9301
cmp x20, #1
b.eq log
mov x0, x20
bl #0x156e574
and w0, w0, #1
mov w9, #9300
add w0, w9, w0, lsl #1
log:
bl #{log:#x}
mov w0, wzr
b #{epi:#x}
keep:
mov w0, #1
b #{epi:#x}
"""

ks = Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN)


def asm(src: str, base: int) -> bytes:
    return bytes(ks.asm(src, base)[0])


def build() -> dict[str, bytes]:
    prod = asm(MAIN.replace("{FIN}", "eor w0, w0, #1"), B3)
    fin_off = prod.index(asm("eor w0, w0, #1", 0), 0x60)
    fin = B3 + fin_off
    epi = fin + 8                     # past `and w0, w0, #1` (bools come back with only the low bits defined)
    diag = prod[:fin_off] + asm(f"b #{DIAG_FIN:#x}", fin) + prod[fin_off + 4:]
    have_deadline = fin - 8
    set_deadline = asm(f"fmov s1, #{TIMEOUT}\nfadd s1, s0, s1\nstr s1, [x19, #0x18]\nb #{have_deadline:#x}",
                       SET_DEADLINE)
    diag_fin = asm(DIAG_SRC.format(log=LOG, epi=epi), DIAG_FIN)
    assert B3 + len(prod) <= B3_END, hex(B3 + len(prod))
    assert SET_DEADLINE + len(set_deadline) <= SET_DEADLINE_END
    assert DIAG_FIN + len(diag_fin) <= DIAG_FIN_END, hex(DIAG_FIN + len(diag_fin))
    so = open(LIB, "rb").read()
    pad = so[B3 + len(prod):B3_END]   # keep the pristine tail word(s) so expected == replacement length
    return {"prod": prod + pad, "diag": diag + pad, "set_deadline": set_deadline, "diag_fin": diag_fin,
            "fin": fin.to_bytes(4, "little")}


def main() -> None:
    so = open(LIB, "rb").read()
    out = build()
    print("b__3 expected   ", so[B3:B3_END].hex())
    print("b__3 prod       ", out["prod"].hex())
    print("b__3 diag       ", out["diag"].hex())
    print("set_deadline @0x%X expected %s replacement %s" % (
        SET_DEADLINE, so[SET_DEADLINE:SET_DEADLINE + len(out["set_deadline"])].hex(), out["set_deadline"].hex()))
    print("diag_fin @0x%X expected %s replacement %s" % (
        DIAG_FIN, so[DIAG_FIN:DIAG_FIN + len(out["diag_fin"])].hex(), out["diag_fin"].hex()))


if __name__ == "__main__":
    main()
