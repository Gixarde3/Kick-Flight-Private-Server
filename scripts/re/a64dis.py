"""a64dis.py <rva_hex> [max_insns] [--so path]

Annotated arm64 disassembly of libil2cpp.so. `bl` targets are named from Il2CppDumper, and
`adrp`+`ldr`/`add` pairs are resolved through .rela.dyn (run reloc.py once) to the string literal,
TypeInfo or Method* they load. Stops at the first `ret`. Needs capstone (pip install capstone).
"""
import re
import sys
from pathlib import Path

from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs

from _common import SO, binary, relocations, symbols


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    so = Path(sys.argv[sys.argv.index("--so") + 1]) if "--so" in sys.argv else SO
    rva = int(args[0], 16)
    n = int(args[1]) if len(args) > 1 else 120
    syms, strs, meta, mm = symbols()
    rel = relocations()
    data = so.read_bytes() if so != SO else binary()
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    print(f"; {syms.get(rva, '?')} @ 0x{rva:X}")
    pages = {}
    for ins in md.disasm(data[rva:rva + n * 4], rva):
        note = ""
        if ins.mnemonic in ("bl", "b") and ins.op_str.startswith("#0x"):
            t = int(ins.op_str[1:], 16)
            note = syms.get(t) or meta.get(t) or ""
            if not note and ins.mnemonic == "b" and not (rva <= t < rva + n * 4):
                note = "(out of function)"
        if ins.mnemonic == "adrp":
            reg, imm = ins.op_str.split(", ")
            pages[reg] = int(imm[1:], 16)
        elif ins.mnemonic in ("ldr", "add"):
            m = re.match(r"(\w+), \[?(\w+), #(0x[0-9a-f]+)", ins.op_str)
            if m and m.group(2) in pages:
                slot = pages[m.group(2)] + int(m.group(3), 16)
                t = rel.get(slot, slot)
                if t in strs:
                    note = f'str "{strs[t]}"'
                else:
                    name = meta.get(t) or mm.get(t) or syms.get(t)
                    note = f"meta {name}" if name else f"-> 0x{slot:X}"
        line = f"0x{ins.address:X}  {ins.bytes.hex():<8}  {ins.mnemonic:<7} {ins.op_str}"
        print(line + (f"    ; {note}" if note else ""))
        if ins.mnemonic == "ret":
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
