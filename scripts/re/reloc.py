"""reloc.py [--find <string literal>]

Parse .rela.dyn R_AARCH64_RELATIVE entries of the pristine libil2cpp.so into a slot -> target map
(cached in .local/re-cache/reloc.pkl) so a64dis.py can resolve `adrp`+`ldr` slots to strings and
metadata. With --find, print the .data.rel.ro slots that point at the given string literal
(pass them to slotref.py to find the code that uses it).
"""
import pickle
import struct
import sys

from _common import CACHE_DIR, binary, symbols

R_AARCH64_RELATIVE = 1027


def build(data: bytes) -> dict:
    e_shoff = struct.unpack_from("<Q", data, 0x28)[0]
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", data, 0x3A)
    secs = [struct.unpack_from("<IIQQQQIIQQ", data, e_shoff + i * e_shentsize) for i in range(e_shnum)]
    shstr = secs[e_shstrndx]

    def name(n: int) -> str:
        s = data[shstr[4] + n:]
        return s[:s.index(b"\0")].decode()

    rel = {}
    for sec in secs:
        if sec[1] == 4 and name(sec[0]) == ".rela.dyn":  # SHT_RELA
            for k in range(sec[5] // 24):
                r_off, r_info, r_add = struct.unpack_from("<QQq", data, sec[4] + k * 24)
                if r_info & 0xFFFFFFFF == R_AARCH64_RELATIVE:
                    rel[r_off] = r_add
    return rel


def main() -> int:
    cache = CACHE_DIR / "reloc.pkl"
    if cache.exists():
        rel = pickle.load(open(cache, "rb"))
    else:
        rel = build(binary())
        pickle.dump(rel, open(cache, "wb"))
    print(f"relative relocations: {len(rel)}")
    if "--find" in sys.argv:
        want = sys.argv[sys.argv.index("--find") + 1]
        _, strs, _, _ = symbols()
        targets = {a for a, v in strs.items() if v == want}
        slots = sorted(s for s, t in rel.items() if t in targets)
        print(want, "->", [hex(s) for s in slots] or "not found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
