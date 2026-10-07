#!/usr/bin/env python3
"""Assemble v4 ApplyHp before/after SetHP probes into the offline dead-body range.

The existing full-state log helper is at 0x1570240. These caves are only valid
when KF_PHOTON is unset/0, where InitializeReconnect is patched to `ret`.
"""

from __future__ import annotations

from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN

KS = Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN)
LOG = 0x1570240
GET_HP = 0x1754624  # int32 PlayerParameter.get_HP(PlayerParameter*, MethodInfo*)
OLD_HOOK = 0x13D5F1C
OLD_RESUME = 0x13D5F20
AFTER_HOOK = 0x13D5F28
AFTER_RESUME = 0x13D5F2C
OLD_CAVE = 0x15703A0
AFTER_CAVE = 0x1570400


def assemble(code: str, base: int) -> bytes:
    encoding, _ = KS.asm(code, base)
    if encoding is None:
        raise RuntimeError(f"assembly failed at {base:#x}")
    return bytes(encoding)


def branch(at: int, target: int) -> bytes:
    return assemble(f"b #{target:#x}", at)


def old_hp_cave() -> bytes:
    # Save HP old, damage after ExtraHP adjustment, and victim id before logging.
    # The existing helper saves/restores every GPR/Q register and NZCV around logcat.
    code = f"""
        sub sp, sp, #0x20
        str w0, [sp]
        str w20, [sp, #4]
        ldr w0, [x19, #0x28]
        str w0, [sp, #8]
        mov w0, #9810
        bl #{LOG:#x}
        ldr w0, [sp, #8]
        bl #{LOG:#x}
        ldr w0, [sp]
        bl #{LOG:#x}
        ldr w0, [sp, #4]
        bl #{LOG:#x}
        mov w0, #9910
        bl #{LOG:#x}
        ldr w0, [sp]
        add sp, sp, #0x20
        sub w1, w0, w20
        b #{OLD_RESUME:#x}
    """
    return assemble(code, OLD_CAVE)


def hp_after_cave() -> bytes:
    # Save all caller-saved GPRs; x19-x28 are preserved by the getter/helper and
    # the original epilogue restores the saved callee-saved registers from its frame.
    code = f"""
        sub sp, sp, #0xa0
        stp x0, x1, [sp]
        stp x2, x3, [sp, #0x10]
        stp x4, x5, [sp, #0x20]
        stp x6, x7, [sp, #0x30]
        stp x8, x9, [sp, #0x40]
        stp x10, x11, [sp, #0x50]
        stp x12, x13, [sp, #0x60]
        stp x14, x15, [sp, #0x70]
        stp x16, x17, [sp, #0x80]
        str x18, [sp, #0x90]
        ldr w9, [x19, #0x28]
        str w9, [sp, #0x98]
        ldr x0, [x19, #0x180]
        cbz x0, skip_log
        mov x1, xzr
        bl #{GET_HP:#x}
        str w0, [sp, #0x9c]
        mov w0, #9811
        bl #{LOG:#x}
        ldr w0, [sp, #0x98]
        bl #{LOG:#x}
        ldr w0, [sp, #0x9c]
        bl #{LOG:#x}
        mov w0, #9911
        bl #{LOG:#x}
    skip_log:
        ldr x18, [sp, #0x90]
        ldp x16, x17, [sp, #0x80]
        ldp x14, x15, [sp, #0x70]
        ldp x12, x13, [sp, #0x60]
        ldp x10, x11, [sp, #0x50]
        ldp x8, x9, [sp, #0x40]
        ldp x6, x7, [sp, #0x30]
        ldp x4, x5, [sp, #0x20]
        ldp x2, x3, [sp, #0x10]
        ldp x0, x1, [sp]
        add sp, sp, #0xa0
        ldp x29, x30, [sp, #0x80]
        b #{AFTER_RESUME:#x}
    """
    return assemble(code, AFTER_CAVE)


def main() -> None:
    old = old_hp_cave()
    after = hp_after_cave()
    assert OLD_CAVE + len(old) <= AFTER_CAVE, (len(old), hex(OLD_CAVE + len(old)))
    assert AFTER_CAVE + len(after) <= 0x1570560, (len(after), hex(AFTER_CAVE + len(after)))
    print(f"old cave {OLD_CAVE:#x} size={len(old)} end={OLD_CAVE + len(old):#x}: {old.hex()}")
    print(f"after cave {AFTER_CAVE:#x} size={len(after)} end={AFTER_CAVE + len(after):#x}: {after.hex()}")
    print(f"old hook  {OLD_HOOK:#x}: {branch(OLD_HOOK, OLD_CAVE).hex()}")
    print(f"after hook {AFTER_HOOK:#x}: {branch(AFTER_HOOK, AFTER_CAVE).hex()}")


if __name__ == "__main__":
    main()
