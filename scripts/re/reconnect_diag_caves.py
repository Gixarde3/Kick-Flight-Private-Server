"""DIAG probes for the Photon-disconnect freeze: which GameManager, which null field (2026-09-21).

Why: cutting the network mid-battle makes `GameManager.CallbackDisconnected` raise
NullReferenceException inside `GameManager.<ReconnectAsync>d__175.MoveNext`, thrown from one of the two
null guards in its state-0 path (`_offlineReplayTarget` at +0xc8, `ReconnectInfo` at +0xa0; the two
`<>4__this` guards cannot fire, CallbackDisconnected already dereferenced `this`). Both fields are written
only by `GameManager.InitializeReconnect` (straight-line, called unconditionally by `GameManager.Initialize`,
itself only called from `<BeginAsync>d__71.MoveNext`), and `CallbackDisconnected` only runs when byte +0x50
(`_isInitialized`) is non-zero - which is set by that same `<BeginAsync>` MoveNext. So either the object
that owns the registered Photon callback is not the one Initialize ran on, or the fields get cleared.

`GameManager.UpdateReconnect` dereferences +0xa0 every frame from `ManagedUpdate`, and ManagedUpdate calls
it *before* the `RuleCtr` update (battle timer/logic) - a null +0xa0 there freezes the whole battle.

KFDIAG values:
  8901, cause, this.lo, this.hi, 8902+|(_isInitialized), 8904+|(byte44), 8906+|(_reconnectInfo != null),
        8908+|(_offlineReplayTarget != null)
        GameManager.CallbackDisconnected entry: identity of the object that owns the Photon callback.
  8921, this.lo, this.hi, 8922+|(_isInitialized), 8924+|(_reconnectInfo != null),
        8926+|(_offlineReplayTarget != null)
        GameManager.Initialize, just after it returned from InitializeReconnect: identity of the object
        that booted the retail reconnect state machine, and what it ended up with.
  8961, this.lo, this.hi   GameManager.UpdateReconnect saw _reconnectInfo == NULL (silent while healthy).

    python scripts/re/reconnect_diag_caves.py   # prints the DIAG_PATCHES_ARM64 entries
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from keystone import KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN, Ks  # noqa: E402

LIB = os.path.join(os.path.dirname(__file__), "..", "..", ".local", "re", "lib", "arm64-v8a", "libil2cpp.so")
LOG = 0x13BC348
ks = Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN)

# Minimal cave frame: the shared LOG helper (0x13BC348) preserves x1-x18, so only x0 (its argument
# register) and the link register need saving. Same shape as the region-E "minimal caves".
#
# Invariant (a cave that broke the loading screen): every hook is `b cave` and every cave leaves with
# `b hook+4`. `bl cave` + trailing `ret` also works, but mixing them does not: `b` never writes x30, so a
# trailing `ret` returns to the *hooked function's* caller and silently truncates it. `check_no_ret()`
# enforces the single style.
FRAME = """
stp x29, x30, [sp, #-0x20]!
str x0, [sp, #0x10]
str x1, [sp, #0x18]
"""
FRAME_END = """
ldr x1, [sp, #0x18]
ldr x0, [sp, #0x10]
ldp x29, x30, [sp], #0x20
"""


def asm_body(text: str, base: int) -> bytes:
    """Assemble arm64 source with `label:` support (keystone takes absolute branch targets)."""
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
        txt = ln.replace("LOG", hex(LOG))
        for name, target in labels.items():
            txt = txt.replace(f"#{name}", f"#{target:#x}")
        enc, _ = ks.asm(txt, addr)
        if enc is None:
            raise SystemExit(f"asm failed: {txt}")
        out += bytes(enc)
        addr += 4
    return bytes(out)


def cave(base: int, body: str, displaced: str, hook_addr: int) -> bytes:
    """Cave body + displaced instruction + jump back to hook+4.

    NEVER end a cave with `ret`: the hook is a `b` (no LR write, see `hook()`), so `ret` would return to the
    *caller of the hooked function*, cutting the rest of that function off. That exact bug (a `ret` cave under
    a `b` hook) made `GameManager.Initialize` return right after `InitializeReconnect`: the loading screen
    looped re-initialising the GameManager ~670 times/s and no battle ever loaded.
    """
    return asm_body(FRAME + body + FRAME_END + displaced + f"\nb #{hook_addr + 4:#x}\n", base)


def hook(at: int, target: int) -> bytes:
    """Entry hook = `b` + jump back, NEVER `bl`: a `bl` clobbers x30, and at a function's first
    instruction the caller's return address is not saved on the stack yet, so the function would
    return into the cave's tail (infinite loop) or restore a bogus LR."""
    return asm_body(f"b #{target:#x}", at)


# (cave addr, hook addr, displaced instruction, body, description)
PROBES = [
    (0x13CDFE0, 0x1574028, "sub w8, w20, #7", """
mov w0, #8901
bl LOG
mov w0, w20
bl LOG
mov w0, w19
bl LOG
lsr x0, x19, #32
bl LOG
ldrb w0, [x19, #0x50]
mov w1, #8902
add w0, w0, w1
bl LOG
ldrb w0, [x19, #0x44]
mov w1, #8904
add w0, w0, w1
bl LOG
ldr x0, [x19, #0xa0]
cmp x0, #0
cset w0, ne
mov w1, #8906
add w0, w0, w1
bl LOG
ldr x0, [x19, #0xc8]
cmp x0, #0
cset w0, ne
mov w1, #8908
add w0, w0, w1
bl LOG
""", "CallbackDisconnected: cause, this lo/hi, 8902+isInitialized, 8904+byte44, 8906+_reconnectInfo!=null, 8908+_offlineReplayTarget!=null"),
    (0x13CE0A0, 0x156E8AC, "ldr x20, [x19, #0xa0]", """
ldr x0, [x19, #0xa0]
cbnz x0, #done
mov w0, #8961
bl LOG
mov w0, w19
bl LOG
lsr x0, x19, #32
bl LOG
done:
""", "UpdateReconnect: 8961 + this lo/hi only when _reconnectInfo is NULL (silent while healthy)"),
    (0x13CE160, 0x156FBB8, "mov x0, x19", """
mov w0, #8921
bl LOG
mov w0, w19
bl LOG
lsr x0, x19, #32
bl LOG
ldrb w0, [x19, #0x50]
mov w1, #8922
add w0, w0, w1
bl LOG
ldr x0, [x19, #0xa0]
cmp x0, #0
cset w0, ne
mov w1, #8924
add w0, w0, w1
bl LOG
ldr x0, [x19, #0xc8]
cmp x0, #0
cset w0, ne
mov w1, #8926
add w0, w0, w1
bl LOG
""", "Initialize after InitializeReconnect: this lo/hi, 8922+isInitialized, 8924+_reconnectInfo!=null, 8926+_offlineReplayTarget!=null"),
]


# Second round (2026-09-21): the rejoin now lands (server log "Successfully joined game: battle-..."), but the
# client stays on its "Reconnecting" dialog. `GameManager.UpdateReconnecting` (state 3) only advances to state 4
# (BeginReconnectSuccess) when BOTH `ReconnectInfo.IsReconnectSharedInfo()` and
# `ReconnectInfo.IsReconnectSharedPlayerInfo(ownUserId)` are true, and those two flags are written by the
# `Receive*ReconnectShared*` RPC handlers (i.e. by another peer) - so these probes trace the whole state machine
# plus the four send/receive entry points that feed it.
#
# Entry hooks here are `b cave` at the function's first instruction (or at a scalar prologue store, for the two
# RPC receivers, whose first instructions save d8-d14 and the log helper does NOT preserve those): the cave saves
# x29/x30 in its frame, logs, re-executes the displaced instruction and jumps back. It must never `ret`.
ENTRY_PROBES = [
    (0x15742B0, "stp x20, x19, [sp, #-0x20]!",
     "mov w0, #8950\nadd w0, w0, w1\nbl LOG\n",
     "SetReconnectState(state): 8950+state (0 none, 1 start, 2 wait, 3 reconnecting, 4 success, 5 failed, 6 room failed)"),
    (0x15741CC, "stp x20, x19, [sp, #-0x20]!",
     "mov w0, #8981\nbl LOG\n",
     "GameManager.CallbackRejoinedRoom entered"),
    (0x1578754, "stp x20, x19, [sp, #-0x20]!",
     "mov w0, #8982\nbl LOG\n",
     "GameManager.SendReconnectShared (local player broadcasts its reconnect info)"),
    (0x1578908, "stp x20, x19, [sp, #-0x20]!",
     "mov w0, #8983\nbl LOG\n",
     "GameManager.SendReconnectSharedPlayer"),
    (0x1547740, "stp x29, x30, [sp, #0x80]",
     "mov w0, #8984\nbl LOG\n",
     "ObjectManagerRPCController.ReceiveReconnectSharedInfo (a peer sent its shared info)"),
    (0x1547C48, "stp x29, x30, [sp, #0xb0]",
     "mov w0, #8985\nbl LOG\n",
     "ObjectManagerRPCController.ReceiveReconnectSharedPlayerInfo (a peer sent a player's info)"),
    # Third round: `GameManager.IsReconnectEnable` (0x1576E34) is the gate that stopped the rejoin in state 6.
    # It returns 0 through `AnalysisManager.SetReconnectFailedCause(w1)` with w1 = the cause:
    #   1 = no current room, or roomState != 8 while some player still has PlayerState < 6 (0x1576FB4)
    #   2 = every player in the room has PlayerState >= 6, i.e. nobody is left "in game" (0x1577024)
    #   3 = roomState == 8 but GameManager.IsUser(myPlayerIndex) is false, i.e. my slot is a bot's (0x1576FAC)
    # and returns 1 when roomState == 8 and IsUser(GetMyPlayerIndex()) (0x157701C).
    # These three caves report the cause code plus the two inputs behind it (roomState, every player's
    # PlayerState). Register safety: the LOG helper preserves x0-x18 only, so every mid-function cave that
    # keeps x19-x24 live across the call saves them in its own frame.
    (0x1577044, "mov x0, x19",
     "stp x19, x20, [sp, #-0x20]!\nstr w1, [sp, #0x10]\n"
     "mov w0, #8940\nbl LOG\nldr w0, [sp, #0x10]\nbl LOG\n"
     "ldp x19, x20, [sp], #0x20\n",
     "IsReconnectEnable failure: 8940 then the failed cause (1 no room/roomState!=8, 2 all players state>=6, 3 my slot is a bot)"),
    (0x1576EA0, "mov w20, w0",
     "stp x19, x20, [sp, #-0x20]!\nstr x0, [sp, #0x10]\n"
     "mov w0, #8930\nbl LOG\nldr w0, [sp, #0x10]\nbl LOG\n"
     "ldp x19, x20, [sp], #0x20\n",
     "IsReconnectEnable: 8930 then the room property RoomState (8 is the only accepted value)"),
    (0x1576F18, "cmp w0, #6",
     "stp x19, x20, [sp, #-0x40]!\nstp x21, x22, [sp, #0x10]\nstp x23, x24, [sp, #0x20]\n"
     "str w22, [sp, #0x30]\nstr w0, [sp, #0x34]\n"
     "mov w0, #8971\nbl LOG\nldr w0, [sp, #0x30]\nbl LOG\nldr w0, [sp, #0x34]\nbl LOG\n"
     "ldp x23, x24, [sp, #0x20]\nldp x21, x22, [sp, #0x10]\nldp x19, x20, [sp], #0x40\n",
     "IsReconnectEnable player loop: 8971, player index, that player's PlayerState (roomState comes from 8930)",
     # The production patch (patch-il2cpp-endpoints.py "Photon reconnect recovery") rewrites this same compare to
     # `#8` so a rejoined client's own ReconnectWait(6) still counts as in game; the DIAG build carries that fix
     # as this cave's tail instead, since only one of the two entries can own the instruction.
     "cmp w0, #8"),
    # Fourth round (2026-09-21): with the IsReconnectEnable gate open the machine gets as far as state 2
    # (UpdateReconnectWait) and stays there, and the production "a rejoined master resumes" patch at 0x1576B18
    # never fires - so UpdateReconnectWait is leaving through one of its diagnostic exits instead. Every such
    # exit is a tail call to `AnalysisManager.SetReconnectFailedCause(w1)` (a 2-instruction leaf:
    # `str w1, [x0, #0x40]; ret`), so hooking its entry prints the cause and names the branch:
    #   100 NetworkManager.IsNetworkError, 101 !PhotonManager.IsConnected (UpdateReconnectStart)
    #   110 room not joined but Photon connected, 111 joined AND this client is the room master
    #   112 joined, not master, ReconnectInfo.IsSerializeRead false, 113 ObjectManager not a valid RPC ctr
    #   114 the master player's PlayerCharacter is null, 115 it is in a non-zero state
    #   200 ReconnectAndRejoin returned false (UpdateReconnectStart)
    # Placed explicitly: the UpdateLookTarget gap that hosts the rest of this block is full (the next cave would
    # end at 0x13CE410, past its 0x13CE3DC limit), so this one goes in the free tail of the entry-stubbed
    # HomeSummonModelController.SetModel (0x159DA78-0x159DAB0, right after the production bat-bomb cave).
    (0x1814634, "str w1, [x0, #0x40]",
     "mov w0, #8992\nbl LOG\nldr w0, [sp, #0x18]\nbl LOG\n",
     "SetReconnectFailedCause(cause): 8992 then the cause code - names every UpdateReconnectWait/Start exit",
     None, 0x159DA78),
]


def check_no_ret(c: bytes, hook_addr: int, base: int) -> None:
    """A cave must leave through `b hook+4`, never `ret` (see `cave()`)."""
    tail = base + len(c) - 4
    word = int.from_bytes(c[-4:], "little")
    imm = word & 0x03FFFFFF
    if imm >= 1 << 25:
        imm -= 1 << 26
    assert word >> 26 == 0x5, f"cave at {base:#x} does not end in a b"
    assert tail + imm * 4 == hook_addr + 4, \
        f"cave at {base:#x} branches to {tail + imm * 4:#x}, not {hook_addr + 4:#x}"
    assert b"\xc0\x03\x5f\xd6" not in c, f"cave at {base:#x} contains a ret"


def main():
    lib = open(LIB, "rb").read()
    entries = []
    lo, hi = 0x13CDFE0, 0x13CE3DC  # tail of the entry-stubbed PlayerCharacter.UpdateLookTarget
    prev_end = lo
    for cave_addr, hook_addr, displaced, body, desc in PROBES:
        c = cave(cave_addr, body, displaced, hook_addr)
        check_no_ret(c, hook_addr, cave_addr)
        assert cave_addr >= prev_end, hex(cave_addr)
        prev_end = cave_addr + len(c)
        assert prev_end <= hi, hex(prev_end)
        h = hook(hook_addr, cave_addr)
        assert lib[hook_addr:hook_addr + 4] == asm_body(displaced, hook_addr), \
            f"hook bytes differ at {hook_addr:#x}: {lib[hook_addr:hook_addr+4].hex()}"
        entries.append(f'    {{"description": "DIAG cave: {desc}", "offset": {cave_addr:#x}, '
                       f'"expected": bytes.fromhex("{lib[cave_addr:cave_addr + len(c)].hex()}"), '
                       f'"replacement": bytes.fromhex("{c.hex()}")}},')
        entries.append(f'    {{"description": "DIAG hook: {desc}", "offset": {hook_addr:#x}, '
                       f'"expected": bytes.fromhex("{lib[hook_addr:hook_addr + 4].hex()}"), '
                       f'"replacement": bytes.fromhex("{h.hex()}")}},')
    # Entry-hook caves are laid out sequentially from the end of the probes above.
    for entry in ENTRY_PROBES:
        hook_addr, displaced, body, desc = entry[:4]
        # Optional 5th element: what the cave executes as its tail when that must differ from the displaced
        # instruction (the 8971 probe sits on the compare the production patch rewrites). `None` = same as displaced.
        tail = (entry[4] or displaced) if len(entry) > 4 else displaced
        # Optional 6th element: an explicit cave address, for entries that go in a different dead body because the
        # UpdateLookTarget gap is full. Those do not advance the sequential allocator.
        explicit = entry[5] if len(entry) > 5 else None
        cave_addr = explicit if explicit is not None else (prev_end + 0xF) & ~0xF
        c = cave(cave_addr, body, tail, hook_addr)
        check_no_ret(c, hook_addr, cave_addr)
        if explicit is None:
            prev_end = cave_addr + len(c)
            assert prev_end <= hi, hex(prev_end)
        h = hook(hook_addr, cave_addr)
        assert lib[hook_addr:hook_addr + 4] == asm_body(displaced, hook_addr), \
            f"hook bytes differ at {hook_addr:#x}: {lib[hook_addr:hook_addr+4].hex()}"
        entries.append(f'    {{"description": "DIAG cave: {desc}", "offset": {cave_addr:#x}, '
                       f'"expected": bytes.fromhex("{lib[cave_addr:cave_addr + len(c)].hex()}"), '
                       f'"replacement": bytes.fromhex("{c.hex()}")}},')
        entries.append(f'    {{"description": "DIAG hook: {desc}", "offset": {hook_addr:#x}, '
                       f'"expected": bytes.fromhex("{lib[hook_addr:hook_addr + 4].hex()}"), '
                       f'"replacement": bytes.fromhex("{h.hex()}")}},')
    print("\n".join(entries))


if __name__ == "__main__":
    main()
