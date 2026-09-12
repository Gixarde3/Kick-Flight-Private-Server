"""Shared setup for the static RE helpers (see README.md in this directory).

Inputs (override with env vars):
  KF_CLEAN_LIBIL2CPP  pristine lib/arm64-v8a/libil2cpp.so extracted from base.apk
  KF_SCRIPT_JSON      Il2CppDumper script.json produced for that same binary
Caches (built on first use): .local/re-cache/symbols.pkl, .local/re-cache/reloc.pkl
"""
import bisect
import json
import os
import pickle
import struct
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SO = Path(os.environ.get("KF_CLEAN_LIBIL2CPP", REPO / ".local" / "re" / "lib" / "arm64-v8a" / "libil2cpp.so"))
SCRIPT = Path(os.environ.get(
    "KF_SCRIPT_JSON",
    REPO.parent / "Kick-Flight-Assets" / "server_revival_analysis" / "il2cpp" / "script.json"))
CACHE_DIR = REPO / ".local" / "re-cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# il2cpp code lives in this RVA window; scanning outside it only costs time
CODE_LO, CODE_HI = 0x1000000, 0x3400000


def binary() -> bytes:
    if not SO.exists():
        raise SystemExit(f"pristine libil2cpp.so not found at {SO}; set KF_CLEAN_LIBIL2CPP")
    return SO.read_bytes()


def symbols():
    """(methods, strings, metadata, metadata_methods) dicts keyed by RVA / slot address."""
    cache = CACHE_DIR / "symbols.pkl"
    if cache.exists():
        return pickle.load(open(cache, "rb"))
    if not SCRIPT.exists():
        raise SystemExit(f"script.json not found at {SCRIPT}; set KF_SCRIPT_JSON")
    j = json.load(open(SCRIPT, encoding="utf-8"))
    syms = {m["Address"]: m["Name"] for m in j["ScriptMethod"]}
    strs = {s["Address"]: s["Value"] for s in j.get("ScriptString", [])}
    meta = {m["Address"]: m["Name"] for m in j.get("ScriptMetadata", [])}
    mm = {m["Address"]: m["Name"] for m in j.get("ScriptMetadataMethod", [])}
    pickle.dump((syms, strs, meta, mm), open(cache, "wb"))
    return syms, strs, meta, mm


def relocations():
    """slot -> target for R_AARCH64_RELATIVE entries (empty until reloc.py has run)."""
    cache = CACHE_DIR / "reloc.pkl"
    return pickle.load(open(cache, "rb")) if cache.exists() else {}


class Owner:
    """Map an RVA to 'Method+0xoff' using the sorted method table."""

    def __init__(self, syms):
        self.syms = syms
        self.addrs = sorted(syms)

    def __call__(self, rva: int) -> str:
        i = bisect.bisect_right(self.addrs, rva) - 1
        if i < 0:
            return "?"
        return f"{self.syms[self.addrs[i]]}+0x{rva - self.addrs[i]:x}"


def branch_target(pc: int, word: int):
    """Decode b/bl/b.cond/cbz/cbnz/tbz/tbnz targets; None for other instructions."""
    op = word >> 26
    if op in (0b000101, 0b100101):
        imm = word & 0x3FFFFFF
        imm -= (1 << 26) if imm & (1 << 25) else 0
        return pc + imm * 4
    if (word & 0xFF000010) == 0x54000000 or (word & 0x7E000000) == 0x34000000:
        imm = (word >> 5) & 0x7FFFF
        imm -= (1 << 19) if imm & (1 << 18) else 0
        return pc + imm * 4
    if (word & 0x7E000000) == 0x36000000:
        imm = (word >> 5) & 0x3FFF
        imm -= (1 << 14) if imm & (1 << 13) else 0
        return pc + imm * 4
    return None


def words(data: bytes, lo: int = CODE_LO, hi: int = CODE_HI):
    for pc in range(lo, hi, 4):
        yield pc, struct.unpack_from("<I", data, pc)[0]
