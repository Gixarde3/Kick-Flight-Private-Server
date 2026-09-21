"""Relocate the DIAG region D/E cave block (2026-09-20).

Why: regions D and E (route/PerformMove traces + the safe LOG helper every other DIAG cave funnels through) lived in
the body of LoadManager.LoadDeckSummonModel(DestroyFlag), so the DIAG build had to stub that function - and then no
summon model is ever loaded in DIAG: every disc/KS with a summon (Leorex, MOVE, TRAP, bombs) throws in
SummonCharacter.InitializeAsync -> ModelManager.InstantiateSummonModel, PlayerStateSkill.End ->
ForceFinishSummon -> SummonCharacter.UpdateState NREs on every forced state change afterwards, so the kicker is
stuck in the skill pose and never respawns.

Fix: move the whole block, as one unit, into the dead body of PlayerCharacter.UpdateLookTarget (0x13CD984, entry
stubbed to `ret` in production, 0xA58 bytes, nothing branches into it) and drop the LoadDeckSummonModel stub.
Intra-block branches/adr keep working unchanged; every external `b`/`bl` out of the block and every hook `bl`/`b`
into it is re-encoded. Run once; it rewrites scripts/patch-il2cpp-endpoints.py in place.

    KF_DIAG=1 python scripts/re/relocate_diag_region.py
"""
import importlib.util
import os
import re
import struct

import capstone

os.environ["KF_DIAG"] = "1"
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
SCRIPT = os.path.join(ROOT, "scripts", "patch-il2cpp-endpoints.py")
LIB = os.path.join(ROOT, ".local", "re", "lib", "arm64-v8a", "libil2cpp.so")

OLD_LO, OLD_HI = 0x16E6CC0, 0x16E7310
NEW_LO = 0x13CD990                      # UpdateLookTarget body (entry `ret` at 0x13CD984)
NEW_HI_LIMIT = 0x13CE3DC                # UpdateIdleTypeRate
DELTA = NEW_LO - OLD_LO
STUB_OFFSET = 0x16E6CA8                 # the DIAG-only LoadDeckSummonModel stub to drop

md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)


def dis1(word, addr):
    l = list(md.disasm(word, addr))
    return l[0] if l else None


def target(ins):
    if ins is None:
        return None
    mn = ins.mnemonic
    if mn in ("b", "bl") or mn.startswith("b.") or mn in ("cbz", "cbnz", "tbz", "tbnz", "adrp", "adr") \
            or (mn == "ldr" and "[" not in ins.op_str and "#" in ins.op_str):
        return int(ins.op_str.split("#")[-1], 16)
    return None


def reencode(word, old_addr, new_addr):
    """Re-encode one PC-relative instruction so it still reaches its (external) target from new_addr."""
    ins = dis1(word, old_addr)
    t = target(ins)
    if t is None or OLD_LO <= t < OLD_HI:
        return word
    w = struct.unpack("<I", word)[0]
    mn = ins.mnemonic
    if mn in ("b", "bl"):
        imm = (t - new_addr) // 4
        assert -(1 << 25) <= imm < (1 << 25)
        return struct.pack("<I", (w & 0xFC000000) | (imm & 0x3FFFFFF))
    if mn == "adrp":
        imm = ((t >> 12) - (new_addr >> 12))
        assert -(1 << 20) <= imm < (1 << 20)
        return struct.pack("<I", (w & 0x9F00001F) | ((imm & 3) << 29) | (((imm >> 2) & 0x7FFFF) << 5))
    raise SystemExit(f"cannot relocate {mn} at {old_addr:#x} -> {t:#x} (imm19/imm14 out of reach)")


def main():
    lib = open(LIB, "rb").read()
    spec = importlib.util.spec_from_file_location("p", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    src = open(SCRIPT, encoding="utf-8").read()
    diag = m.DIAG_PATCHES_ARM64
    assert diag, "import with KF_DIAG=1"

    block = [e for e in diag if OLD_LO <= e["offset"] < OLD_HI]
    assert block and max(e["offset"] + len(e["replacement"]) for e in block) <= OLD_HI
    assert NEW_LO + (OLD_HI - OLD_LO) <= NEW_HI_LIMIT

    def sub_entry(offset, new_offset, new_expected, new_replacement, extra_desc=""):
        nonlocal src
        pat = re.compile(r'("description": "[^"]*)(",\s*"offset": )0x0*' + f"{offset:x}" +
                         r'(,\s*"expected": bytes\.fromhex\(")[0-9a-f]*("\),\s*"replacement": bytes\.fromhex\(")[0-9a-f]*("\))',
                         re.IGNORECASE)
        hits = pat.findall(src)
        assert len(hits) == 1, (hex(offset), len(hits))
        src = pat.sub(lambda mm: f"{mm.group(1)}{extra_desc}{mm.group(2)}{new_offset:#x}{mm.group(3)}{new_expected.hex()}"
                      f"{mm.group(4)}{new_replacement.hex()}{mm.group(5)}", src, count=1)

    # 1. the block itself
    for e in block:
        off = e["offset"]
        rep = e["replacement"]
        new_off = off + DELTA
        out = b"".join(reencode(rep[k:k + 4], off + k, new_off + k) for k in range(0, len(rep), 4))
        sub_entry(off, new_off, lib[new_off:new_off + len(out)], out,
                  " [relocated 2026-09-20 from LoadDeckSummonModel to the dead PlayerCharacter.UpdateLookTarget body]")
        print(f"block {off:#x} -> {new_off:#x} ({len(out)} B)")

    # 2. hooks and the region A trampoline that branch into the block
    seen = set()
    for e in diag + m.NATIVE_PATCHES["arm64-v8a"]:
        off = e["offset"]
        if OLD_LO <= off < OLD_HI or off in seen:
            continue
        rep = e["replacement"]
        words = []
        changed = False
        for k in range(0, len(rep), 4):
            wd = rep[k:k + 4]
            t = target(dis1(wd, off + k))
            if t is not None and OLD_LO <= t < OLD_HI:
                ins = dis1(wd, off + k)
                assert ins.mnemonic in ("b", "bl"), ins.mnemonic
                w = struct.unpack("<I", wd)[0]
                imm = (t + DELTA - (off + k)) // 4
                wd = struct.pack("<I", (w & 0xFC000000) | (imm & 0x3FFFFFF))
                changed = True
                print(f"hook {off + k:#x}: {ins.mnemonic} {t:#x} -> {t + DELTA:#x}")
            words.append(wd)
        if changed:
            seen.add(off)
            sub_entry(off, off, e["expected"], b"".join(words))

    # 3. drop the LoadDeckSummonModel stub
    pat = re.compile(r'\n\s*\{\s*"description": "DIAG only: stub LoadDeckSummonModel[^}]*\},', re.S)
    assert len(pat.findall(src)) == 1
    src = pat.sub("", src, count=1)
    open(SCRIPT, "w", encoding="utf-8", newline="\n").write(src)
    print("rewritten", SCRIPT)


if __name__ == "__main__":
    main()
