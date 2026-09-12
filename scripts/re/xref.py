"""xref.py <target_rva_hex>...

List every `bl`/`b` whose target is one of the given RVAs, naming the containing method.
Virtual and interface calls go through `blr` and will not show up; use slotref.py on the
method's Method* slot for those, or look for the vtable slot offset in the caller.
"""
import sys

from _common import Owner, binary, symbols, words


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    targets = {int(t, 16) for t in sys.argv[1:]}
    syms, *_ = symbols()
    owner = Owner(syms)
    for pc, w in words(binary()):
        op = w >> 26
        if op in (0b100101, 0b000101):
            imm = w & 0x3FFFFFF
            imm -= (1 << 26) if imm & (1 << 25) else 0
            t = pc + imm * 4
            if t in targets:
                kind = "bl" if op == 0b100101 else "b "
                print(f"0x{pc:X}  {kind} -> {syms.get(t, '?')}   in {owner(pc)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
