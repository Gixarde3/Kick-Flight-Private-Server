"""Generate DIAG region E (dead body of LoadManager.LoadDeckSummonModel, 0x16E6ED0..0x16E731C):
  - safe LOG helper (preserves x0-x18, q0-q7, q16-q31) that 0x13BC348 branches to
  - PerformMove destination-selection trace caves (1000+active / 1100+AIOption, 1300+count / 2000+goal, 3000+|segment|)
"""
from mkcave import cave, hook, asm, SAVE, RESTORE

from _common import binary
data = binary()
BASE = 0x16E6ED0
END = 0x16E731C

addr = BASE
blob = bytearray()
hooks = []

# --- safe log helper ---------------------------------------------------------
helper_body = SAVE + """
mov w3, w0
mov w0, #3
adr x1, #TAG
adr x2, #FMT
bl #0x10d6270
""" + RESTORE + "ret\n"
tmp = asm(helper_body.replace("TAG", hex(addr)).replace("FMT", hex(addr)), addr)
tag_off = addr + len(tmp)
fmt_off = tag_off + 8
helper = asm(helper_body.replace("TAG", hex(tag_off)).replace("FMT", hex(fmt_off)), addr)
helper += b"KFDIAG\x00\x00" + b"v=%d\x00\x00\x00\x00"
blob += helper
addr += len(helper)
hooks.append((0x13BC348, data[0x13BC348:0x13BC34C].hex(), asm(f"b #{BASE:#x}", 0x13BC348).hex()))

# --- PerformMove trace caves -------------------------------------------------
caves = [
    # H1: after get_TargetActive -> 1000+active
    (0x13BF8B4, "add w0, w0, #1000\nbl LOG\n", "mov w8, w0"),
    # H2: after route count check -> 1100+AIOption, 1300+count, raw _aiAutoMoveDefaultGoalDistance bits
    (0x13BF8F4, """
ldr w0, [x19, #0xe4]
add w0, w0, #1100
bl LOG
ldr w0, [sp, #0x10]
add w0, w0, #1300
bl LOG
ldr w0, [x19, #0xe8]
bl LOG
""", "ldrb w8, [x19, #0xe1]"),
    # H3: per route segment -> 2000+int(goal), 3000+int(|segment|)
    (0x13BFA10, """
fcvtzs w0, s0
add w0, w0, #2000
bl LOG
fmul s1, s8, s8
fmul s2, s11, s11
fadd s1, s1, s2
fmul s2, s12, s12
fadd s1, s1, s2
fsqrt s1, s1
fcvtzs w0, s1
add w0, w0, #3000
bl LOG
""", "mov v3.16b, v0.16b"),
]
for at, body, disp in caves:
    c = cave(addr, body, disp)
    exp_disp = data[at:at + 4]
    assert asm(disp, at) == exp_disp, (hex(at), exp_disp.hex(), asm(disp, at).hex())
    hooks.append((at, exp_disp.hex(), hook(at, addr).hex()))
    blob += c
    addr += len(c)

assert addr <= END, hex(addr)
print("region E", hex(BASE), "-", hex(addr), len(blob), "bytes")
print("expected:", data[BASE:addr].hex())
print("replacement:", blob.hex())
for h in hooks:
    print("hook", hex(h[0]), h[1], "->", h[2])
