"""slotref.py <slot_hex>...

Find code that materialises a data slot with `adrp` + `ldr`/`add` (within 5 instructions).
Combine with reloc.py: pick the .data.rel.ro slots whose relocation target is the metadata-usage
entry of a string literal / TypeInfo / Method*, then feed those slots here to find the users.
Example (which code writes "RoomStartTime"): python reloc.py --find RoomStartTime, then slotref.py <slots>.
"""
import struct
import sys

from _common import Owner, binary, symbols, words


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    targets = {int(t, 16) for t in sys.argv[1:]}
    syms, *_ = symbols()
    owner = Owner(syms)
    data = binary()
    for pc, w in words(data):
        if (w & 0x9F000000) != 0x90000000:  # adrp
            continue
        rd = w & 0x1F
        imm = (((w >> 5) & 0x7FFFF) << 2) | ((w >> 29) & 3)
        imm -= (1 << 21) if imm & (1 << 20) else 0
        page = (pc & ~0xFFF) + (imm << 12)
        for k in range(1, 6):
            w2 = struct.unpack_from("<I", data, pc + k * 4)[0]
            if (w2 & 0xFFC00000) == 0xF9400000 and ((w2 >> 5) & 0x1F) == rd:  # ldr x, [rd, #imm*8]
                a = page + (((w2 >> 10) & 0xFFF) << 3)
            elif (w2 & 0xFF800000) == 0x91000000 and ((w2 >> 5) & 0x1F) == rd:  # add x, rd, #imm
                a = page + ((w2 >> 10) & 0xFFF)
            else:
                continue
            if a in targets:
                print(f"0x{pc:X}  slot 0x{a:X}  in {owner(pc)}")
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
