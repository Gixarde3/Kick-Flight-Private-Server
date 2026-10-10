"""claude-bots-2: production caves for bot ground/take-off (issue 3) and AI crystal deposit cancel (issue 4).

Run with Windows Python (keystone + capstone):  python scripts/re/bot_ground_deposit_caves.py
Prints patch-table entries (offset / expected from the pristine .so / replacement).

Hosts (verified with handoff/claude-bots-2/scratch/free_windows.py: entry-stubbed in all 8 flavours, no patch in any
flavour writes the window, no pristine or patched b/bl/b.cond/cbz/tbz lands anywhere in the function body):
  WANT_AIR  0x1A830C0  GRE.ResourceManager.AssetBundleUnloadCompleted body (entry = b 0x13CE6D8 full-replacement cave)
  LANDABLE  0x156D7E0  Colorful.GameManager.get_IsAllPlayerLoaded body (entry = mov w0,#1; ret)
  DEPOSIT   0x18A48FC  Colorful.ResultManager.<BeginAsync>b__28_0 body (entry = mov w0,wzr; ret)
"""
from pathlib import Path
from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

SO = (Path(__file__).resolve().parents[2] / ".local/re/lib/arm64-v8a/libil2cpp.so").read_bytes()
ks = Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN)
cs = Cs(CS_ARCH_ARM64, CS_MODE_ARM)

WANT_AIR = 0x1A830C0      # limit 0x1A83144
LANDABLE = 0x156D7E0      # limit 0x156D834
DEPOSIT = 0x18A48FC       # limit 0x18A4924
CANTAKEOFF_SLOT = 0x17331D0   # existing 32-byte production cave slot (hook 0x17E6FFC = bl 0x17331D0 stays)
ISLANDABLE = 0x17E0EF4        # PlayerStateNormal.IsLandable entry: str d8,[sp,#-0x40]!
UPDATEFLY_ISLANDABLE_RET = 0x17E49B0  # return address of `bl IsLandable` at 0x17E49AC in UpdateFly
DEP_INPUT = 0x18D1F10         # PlayerStateDeposit.InputAction entry: stp x20,x19,[sp,#-0x20]!

H_UP = "3.0"                  # take off / stay airborne if destination is > 3 m above the ground under the bot
D2_FAR = 0x4310               # high half of 144.0f: ... or > 12 m away horizontally

def asm(src, base, limit=None):
    enc, _ = ks.asm(src, base)
    b = bytes(enc)
    if limit is not None:
        assert base + len(b) <= limit, (hex(base), len(b), hex(limit))
    return b

def show(name, base, b):
    print(f"# {name} @ {base:#x} ({len(b)} B)")
    for i in cs.disasm(b, base):
        print(f"#   {i.address:#x}  {i.mnemonic} {i.op_str}")

def entry(desc, off, rep):
    exp = SO[off:off + len(rep)]
    print("{" + f'"description": "{desc}", "offset": {off:#x}, "expected": bytes.fromhex("{exp.hex()}"), '
          f'"replacement": bytes.fromhex("{rep.hex()}")' + "},")

# WantAir(x0 = PlayerStateNormal) -> w0. Leaf, no stack, clobbers x8-x10, s0-s3 only.
want_air_src = f"""
    ldr  x8, [x0, #0x10]
    cbz  x8, no
    ldrb w9, [x8, #0xe0]
    cbz  w9, no
    ldr  x9, [x8, #0x210]
    cbz  x9, no
    ldr  s0, [x9, #0x20]
    fcmp s0, #0.0
    b.le no
    ldr  x9, [x8, #0x68]
    ldrb w9, [x9, #0x27]
    cbz  w9, no
    ldr  s0, [x0, #0x1a0]
    ldr  s1, [x0, #0x48]
    fsub s0, s0, s1
    fmov s1, #{H_UP}
    fcmp s0, s1
    b.gt yes
    ldr  s0, [x0, #0x19c]
    ldr  s1, [x0, #0x44]
    fsub s0, s0, s1
    ldr  s2, [x0, #0x1a4]
    ldr  s3, [x0, #0x4c]
    fsub s2, s2, s3
    fmul s0, s0, s0
    fmadd s0, s2, s2, s0
    movz w10, #{D2_FAR:#x}, lsl #16
    fmov s1, w10
    fcmp s0, s1
yes:
    cset w0, gt
    ret
no:
    mov  w0, wzr
    ret
"""
want_air = asm(want_air_src, WANT_AIR, 0x1A83144)

slot = asm(f"mov x0, x19; b {WANT_AIR:#x}; nop; nop; nop; nop; nop; nop", CANTAKEOFF_SLOT)
assert len(slot) == 32

landable_src = f"""
    adrp x10, {UPDATEFLY_ISLANDABLE_RET & ~0xFFF:#x}
    add  x10, x10, #{UPDATEFLY_ISLANDABLE_RET & 0xFFF:#x}
    cmp  x30, x10
    b.ne orig
    stp  x29, x30, [sp, #-0x20]!
    stp  x0, x1, [sp, #0x10]
    bl   {WANT_AIR:#x}
    mov  w9, w0
    ldp  x0, x1, [sp, #0x10]
    ldp  x29, x30, [sp], #0x20
    cbz  w9, orig
    mov  w0, wzr
    ret
orig:
    str  d8, [sp, #-0x40]!
    b    {ISLANDABLE + 4:#x}
"""
landable = asm(landable_src, LANDABLE, 0x156D834)
landable_hook = asm(f"b {LANDABLE:#x}", ISLANDABLE)

deposit_src = f"""
    ldr  x9, [x0, #0x10]
    cbz  x9, orig
    ldrb w9, [x9, #0xe0]
    cbz  w9, orig
    mov  x0, xzr
    ret
orig:
    stp  x20, x19, [sp, #-0x20]!
    b    {DEP_INPUT + 4:#x}
"""
deposit = asm(deposit_src, DEPOSIT, 0x18A4924)
deposit_hook = asm(f"b {DEPOSIT:#x}", DEP_INPUT)

# sanity: displaced instructions are what we think
assert SO[ISLANDABLE:ISLANDABLE + 4] == bytes.fromhex("e80f1cfc")
assert SO[DEP_INPUT:DEP_INPUT + 4] == bytes.fromhex("f44fbea9")
assert SO[0x17E6FFC:0x17E7000] == bytes.fromhex("e0031f2a")

for n, b_, x in (("WantAir", WANT_AIR, want_air), ("CanTakeOff slot", CANTAKEOFF_SLOT, slot),
                 ("IsLandable gate", LANDABLE, landable), ("Deposit input gate", DEPOSIT, deposit)):
    show(n, b_, x)
print()
entry("cave: WantAir(PlayerStateNormal) -> EnableAI && MoveInfo.IsMove && EnableFly && (AutoMoveDestination.y - groundHit.y > 3 || horiz dist > 12) [dead body of AssetBundleUnloadCompleted]", WANT_AIR, want_air)
print("# REPLACES the 0x17331D0 entry (same 32 bytes; its `expected` stays the pristine bytes; hook 0x17E6FFC unchanged):")
entry("cave: PlayerStateNormal.CanTakeOff ground branch -> return WantAir(this)", CANTAKEOFF_SLOT, slot)
entry("cave: PlayerStateNormal.IsLandable called from UpdateFly -> false while WantAir (no plain re-landing of a moving AI bot) [dead body of get_IsAllPlayerLoaded]", LANDABLE, landable)
entry("PlayerStateNormal.IsLandable entry -> b IsLandable gate cave", ISLANDABLE, landable_hook)
entry("cave: PlayerStateDeposit.InputAction -> null for EnableAI players (master's touch Ended no longer cancels bot deposits) [dead body of ResultManager.<BeginAsync>b__28_0]", DEPOSIT, deposit)
entry("PlayerStateDeposit.InputAction entry -> b AI deposit input gate cave", DEP_INPUT, deposit_hook)
