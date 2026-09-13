"""Assemble diag caves with keystone. Each cave: full caller-saved register save, user body
(may call LOG=0x13bc348 with w0), restore, displaced instruction(s), ret."""
from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN
ks = Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN)
LOG = 0x13BC348

SAVE = """
sub sp, sp, #0x240
stp x29, x30, [sp]
stp x0, x1, [sp, #0x10]
stp x2, x3, [sp, #0x20]
stp x4, x5, [sp, #0x30]
stp x6, x7, [sp, #0x40]
stp x8, x9, [sp, #0x50]
stp x10, x11, [sp, #0x60]
stp x12, x13, [sp, #0x70]
stp x14, x15, [sp, #0x80]
stp x16, x17, [sp, #0x90]
str x18, [sp, #0xa0]
stp q0, q1, [sp, #0xb0]
stp q2, q3, [sp, #0xd0]
stp q4, q5, [sp, #0xf0]
stp q6, q7, [sp, #0x110]
stp q16, q17, [sp, #0x130]
stp q18, q19, [sp, #0x150]
stp q20, q21, [sp, #0x170]
stp q22, q23, [sp, #0x190]
stp q24, q25, [sp, #0x1b0]
stp q26, q27, [sp, #0x1d0]
stp q28, q29, [sp, #0x1f0]
stp q30, q31, [sp, #0x210]
"""
RESTORE = """
ldp q30, q31, [sp, #0x210]
ldp q28, q29, [sp, #0x1f0]
ldp q26, q27, [sp, #0x1d0]
ldp q24, q25, [sp, #0x1b0]
ldp q22, q23, [sp, #0x190]
ldp q20, q21, [sp, #0x170]
ldp q18, q19, [sp, #0x150]
ldp q16, q17, [sp, #0x130]
ldp q6, q7, [sp, #0x110]
ldp q4, q5, [sp, #0xf0]
ldp q2, q3, [sp, #0xd0]
ldp q0, q1, [sp, #0xb0]
ldr x18, [sp, #0xa0]
ldp x16, x17, [sp, #0x90]
ldp x14, x15, [sp, #0x80]
ldp x12, x13, [sp, #0x70]
ldp x10, x11, [sp, #0x60]
ldp x8, x9, [sp, #0x50]
ldp x6, x7, [sp, #0x40]
ldp x4, x5, [sp, #0x30]
ldp x2, x3, [sp, #0x20]
ldp x0, x1, [sp, #0x10]
ldp x29, x30, [sp]
add sp, sp, #0x240
"""

def asm(text: str, base: int) -> bytes:
    out = bytearray()
    addr = base
    for line in text.strip().splitlines():
        line = line.split(";")[0].strip()
        if not line:
            continue
        line = line.replace("LOG", hex(LOG))
        if line.startswith("adr "):  # adr xN, #absolute  (keystone rejects the absolute form)
            rd = int(line.split()[1].rstrip(",")[1:])
            imm = int(line.split("#")[1], 16) - addr
            assert -(1 << 20) <= imm < (1 << 20)
            w = 0x10000000 | ((imm & 3) << 29) | (((imm >> 2) & 0x7FFFF) << 5) | rd
            enc = list(w.to_bytes(4, "little"))
        else:
            enc, _ = ks.asm(line, addr)
        if enc is None:
            raise SystemExit(f"asm failed: {line}")
        out += bytes(enc)
        addr += len(enc)
    return bytes(out)

def cave(base: int, body: str, displaced: str) -> bytes:
    return asm(SAVE + body + RESTORE + displaced + "\nret\n", base)

def hook(at: int, target: int) -> bytes:
    return asm(f"bl #{target:#x}", at)

if __name__ == "__main__":
    import sys
    print(asm(sys.argv[1], int(sys.argv[2], 16)).hex())
