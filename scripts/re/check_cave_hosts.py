"""Cave-host checker for the Kick-Flight 2.11.0 patcher (handoff/dsh-patch-3).

Why
---
A "cave" (a block of patched code placed inside some function's dead body) is only safe if, in the
SAME build flavour, the function that contains it is made unreachable at its entry. Several flavours
exist (`KF_PHOTON` off/on, `KF_DIAG` off/on, ready scene off/on), and a body that is `ret`-stubbed in
one flavour can be LIVE in another. The dsh-patch-2 smog caves lived in `GameManager.BeginReconnectRoomFailed`,
stubbed only when `KF_PHOTON` is unset; in the `KF_PHOTON=1` builds that the VPS serves, the functions
are live and the caves overwrote live code. This script loads `scripts/patch-il2cpp-endpoints.py` under
every flavour and asserts:

  (a) for every cave blob (a patch whose description mentions "cave"/"dead body" and whose replacement is
      not a single branch hook), the *containing function's entry* is patched in that flavour by a
      return-stub (`... ret`) or by an unconditional `b` that leaves the body unreachable;
  (b) no two patches write overlapping byte intervals (so "no other patch writes into the window");
  (c) no 4-byte branch hook points into a different function whose target is not written by a patch in
      that same flavour (catching a cave gated out while its hook stayed in);
  (d) an **entry-hook** DIAG cave that writes x0/w0 for its first `bl LOG` must have stored x0 to the
      stack first (handoff/dsh-patch-4: `DIAG_TRAP_SRC`/`DIAG_R15_SRC` passed the probe value in w0
      without saving the real first argument, so the hooked function ran with a fake `this`). This uses
      capstone when available; if capstone is missing the host/overlap checks still run and the lint is
      reported as skipped.
  (e) a `bl` hook (any flavour, DIAG or production) must not clobber a live x30. A `bl` overwrites LR with
      `hook+4`; if the hooked function has already run its `ldp x29, x30` epilogue before the hook, or the
      path from the hook reaches a `ret`/tail call before x30 is reloaded from the stack, the callee (or a
      later `ret`) returns into the middle of the function (handoff/dsh-patch-5: probe 9570 at 0x161A944 in
      `ThrowingStarSpecialSkillAction.OnEndCutScene` sits right after `0x161A940 ldp x29, x30` and before
      `b set_State`; it crashed the first local Kite special skill). il2cpp state-machine jump tables
      (`ldrsw/ldr Xd, [Xb, Xi, lsl #2/3]; ...; add Xd, Xd, Xb; ...; br Xd`) are intra-function computed
      gotos and are followed past the `br`, not treated as tail calls.

Usage (Windows Python is the only interpreter with capstone/keystone; the host/overlap checks only need stdlib):
    python scripts/re/check_cave_hosts.py
Exit code 0 = every flavour clean; 1 = at least one violation (printed). If capstone is missing, lint (d)/(e)
are skipped with a warning and the other checks still run.
"""
from __future__ import annotations

import bisect
import importlib.util
import os
import pickle
import struct
import sys
from pathlib import Path

try:
    from capstone import (Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN, CS_AC_WRITE)
    from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_MEM, ARM64_OP_REG
except Exception:  # pragma: no cover - the RE interpreter ships capstone
    Cs = None

REPO = Path(__file__).resolve().parents[2]
PATCHER = REPO / "scripts" / "patch-il2cpp-endpoints.py"
SYMBOLS = REPO / ".local" / "re-cache" / "symbols.pkl"
PRISTINE_SO = REPO / ".local" / "re" / "lib" / "arm64-v8a" / "libil2cpp.so"
RET = bytes.fromhex("c0035fd6")
LOG = 0x13BC348
STORE_MNEMONICS = ("str", "stp", "stur", "strb", "strh", "st1")
LR_REGS = ("x30", "lr")

FLAVOURS = [(photon, diag, ready_scene)
            for photon in (0, 1) for diag in (0, 1) for ready_scene in (0, 1)]


def branch_target(pc: int, word: int):
    """Decode b/bl/b.cond/cbz/cbnz/tbz/tbnz; None for anything else (no capstone dependency)."""
    op = word >> 26
    if op in (0b000101, 0b100101):                                        # b / bl
        imm = word & 0x3FFFFFF
        imm -= (1 << 26) if imm & (1 << 25) else 0
        return pc + imm * 4
    if (word & 0xFF000010) == 0x54000000 or (word & 0x7E000000) == 0x34000000:   # b.cond / cbz,cbnz
        imm = (word >> 5) & 0x7FFFF
        imm -= (1 << 19) if imm & (1 << 18) else 0
        return pc + imm * 4
    if (word & 0x7E000000) == 0x36000000:                                 # tbz/tbnz
        imm = (word >> 5) & 0x3FFF
        imm -= (1 << 14) if imm & (1 << 13) else 0
        return pc + imm * 4
    return None


def is_branch_patch(rep: bytes) -> bool:
    return len(rep) == 4 and branch_target(0, struct.unpack_from("<I", rep)[0]) is not None


def is_return_stub(rep: bytes) -> bool:
    """The entry replacement makes the body unreachable by returning: ends in `ret`, no branch inside."""
    if len(rep) > 24 or len(rep) % 4 or rep[-4:] != RET:
        return False
    return all(branch_target(0, struct.unpack_from("<I", rep, i)[0]) is None
               for i in range(0, len(rep) - 4, 4))


def is_dead_entry(rep: bytes) -> bool:
    """Return-stub, or starts with an unconditional `b` (not `bl`) so the body is never reached."""
    if is_return_stub(rep):
        return True
    return len(rep) >= 4 and (struct.unpack_from("<I", rep, 0)[0] >> 26) == 0b000101


def is_cave_text(desc: str) -> bool:
    low = desc.lower()
    return "cave" in low or "dead body" in low


def entry_hook_clobbers_x0(code: bytes, base: int, hook_next: int):
    """Entry-hook lint (handoff/dsh-patch-4).

    The region-E LOG helper takes its value in w0 and returns with x0 still holding that value, so an
    entry-hook cave that overwrites w0 for `bl LOG` without first saving the caller's x0 hands the hooked
    function a fake first argument. Return a one-line reason when that pattern is present, else None.

    Only `bl LOG` calls that lie on a path from the cave entry to the hooked function's continuation
    (`b hook+4`) are considered: a guard path that ends in `ret` never runs the body, so it may reuse x0
    freely (the PlayerAnimator.SetParamVelocity DIAG guard does exactly that). The displaced prologue
    instruction is replayed on the continuation path itself, so it cannot count as the saved store.
    """
    if Cs is None:
        return None
    md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    md.detail = True
    insns = list(md.disasm(code, base))
    if not insns:
        return None
    index = {i.address: k for k, i in enumerate(insns)}

    def successors(k):
        insn = insns[k]
        nxt = k + 1 if k + 1 < len(insns) else None
        mnem = insn.mnemonic
        if mnem == "b":
            target = insn.operands[0].imm if insn.operands else None
            return [index[target]] if target in index else []
        if mnem.startswith("b.") or mnem in ("cbz", "cbnz", "tbz", "tbnz"):
            target = insn.operands[-1].imm
            out = [index[target]] if target in index else []
            if nxt is not None:
                out.append(nxt)
            return out
        if mnem == "ret":
            return []
        return [nxt] if nxt is not None else []

    cont = [k for k, i in enumerate(insns)
            if i.mnemonic == "b" and i.operands and i.operands[0].type == ARM64_OP_IMM
            and i.operands[0].imm == hook_next]
    if not cont:
        return None

    pred = {k: set() for k in range(len(insns))}
    for k in range(len(insns)):
        for s in successors(k):
            pred[s].add(k)

    fwd, stack = set(), [0]
    while stack:
        k = stack.pop()
        if k in fwd:
            continue
        fwd.add(k)
        stack.extend(successors(k))
    bwd, stack = set(), list(cont)
    while stack:
        k = stack.pop()
        if k in bwd:
            continue
        bwd.add(k)
        stack.extend(pred[k])
    onpath = fwd & bwd

    first_log = None
    for k in sorted(onpath):
        insn = insns[k]
        if insn.mnemonic == "bl" and insn.operands \
                and insn.operands[0].type == ARM64_OP_IMM and insn.operands[0].imm == LOG:
            first_log = k
            break
    if first_log is None:
        return None

    x0_saved = False
    for k in range(first_log):
        if k not in onpath:
            continue
        insn = insns[k]
        if insn.mnemonic in STORE_MNEMONICS and insn.operands:
            op0 = insn.operands[0]
            if op0.type == ARM64_OP_REG and insn.reg_name(op0.reg) in ("x0", "w0") \
                    and any(o.type == ARM64_OP_MEM and insn.reg_name(o.mem.base) == "sp"
                            for o in insn.operands[1:]):
                x0_saved = True
        for op in insn.operands:
            if op.type == ARM64_OP_REG and (op.access & CS_AC_WRITE) \
                    and insn.reg_name(op.reg) in ("x0", "w0"):
                if not x0_saved:
                    return (f"`{insn.mnemonic} {insn.op_str}` overwrites x0/w0 before the first bl LOG "
                            f"without storing x0 to the stack")
                break
    return None


def is_bl_patch(rep: bytes) -> bool:
    """True for a 4-byte `bl` (the mid-function hook form)."""
    return len(rep) == 4 and (struct.unpack_from("<I", rep)[0] >> 26) == 0b100101


def _x30_reloaded_from_mem(insn) -> bool:
    """`ldp x29, x30, [sp...]`, `ldr x30, [sp/x29...]` (capstone names x30 `lr`)."""
    for op in insn.operands:
        if op.type == ARM64_OP_REG and (op.access & CS_AC_WRITE) and insn.reg_name(op.reg) in LR_REGS:
            for o in insn.operands:
                if o.type == ARM64_OP_MEM and insn.reg_name(o.mem.base) in ("sp", "x29", "fp"):
                    return True
    return False


def _is_jump_table(insns, k) -> bool:
    """`ldrsw/ldr Xd, [Xb, Xi, lsl #2/3]; ...; add Xd, Xd, Xb; ...; br Xd` = il2cpp switch dispatch.

    il2cpp interleaves unrelated loads between the table load and the `add`/`br` (e.g.
    `0x1579D48 ldr x20,[x19,#0x20]` in `GameManager.<BeginAsync>d__71.MoveNext`), so look back a few
    instructions. Such a `br` is an intra-function computed goto, not a tail call.
    """
    br = insns[k]
    if not br.operands or br.operands[0].type != ARM64_OP_REG:
        return False
    br_reg = br.operands[0].reg
    add_idx = None
    for j in range(k - 1, max(k - 7, -1), -1):
        ins = insns[j]
        if ins.mnemonic == "add" and ins.operands and ins.operands[0].type == ARM64_OP_REG \
                and ins.operands[0].reg == br_reg:
            if br_reg in {o.reg for o in ins.operands[1:] if o.type == ARM64_OP_REG}:
                add_idx = j
                break
    if add_idx is None:
        return False
    base_regs = {o.reg for o in insns[add_idx].operands[1:]
                 if o.type == ARM64_OP_REG and o.reg != br_reg}
    for j in range(add_idx - 1, max(add_idx - 7, -1), -1):
        ins = insns[j]
        if ins.mnemonic not in ("ldrsw", "ldr") or not ins.operands:
            continue
        if ins.operands[0].type != ARM64_OP_REG or ins.operands[0].reg != br_reg:
            continue
        for o in ins.operands:
            if o.type == ARM64_OP_MEM and o.mem.index != 0 and o.mem.base in base_regs:
                return True
    return False


def bl_hook_clobbers_lr(data: bytes, syms: dict, addrs: list, hook: int) -> str | None:
    """Lint (e): reason when the `bl` hook overwrites an x30 the function will use, else None.

    Walk the pristine function's control flow from the hook. x30 starts out "live" if it is not reloaded
    from the stack before a `ret` or an out-of-function `b` (tail call); the `bl` then makes the callee or
    the following `ret` return to `hook+4` instead of the caller. Conditional branches are both explored.
    """
    if Cs is None:
        return None
    i = bisect.bisect_right(addrs, hook) - 1
    if i < 0:
        return None
    entry = addrs[i]
    end = addrs[i + 1] if i + 1 < len(addrs) else hook + 0x2000
    if not (entry <= hook < end) or entry == hook:
        return None  # entry hook: the function's own prologue saves the clobbered LR; different lint
    md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    md.detail = True
    insns = list(md.disasm(data[entry:end], entry))
    index = {ins.address: k for k, ins in enumerate(insns)}
    hook_idx = next((k for k, ins in enumerate(insns) if ins.address == hook), None)
    if hook_idx is None:
        return None

    def local(target):
        return target in index

    seen = set()
    stack = [(hook_idx, False)]
    while stack:
        k, reloaded = stack.pop()
        if (k, reloaded) in seen:
            continue
        seen.add((k, reloaded))
        ins = insns[k]
        if _x30_reloaded_from_mem(ins):
            reloaded = True
        m = ins.mnemonic
        if m == "ret":
            if not reloaded:
                return f"`ret` @0x{ins.address:x} with x30 = hook+4 (no x30 reload after the hook)"
            continue
        if m == "b":
            target = ins.operands[0].imm if ins.operands else None
            if target is not None and local(target):
                stack.append((index[target], reloaded))
            elif not reloaded:
                return f"tail call `b` @0x{ins.address:x} -> 0x{target:x} without an x30 reload"
            continue
        if m == "br":
            if _is_jump_table(insns, k):
                nk = k + 1
                if nk < len(insns):
                    stack.append((nk, reloaded))
            elif not reloaded:
                return f"tail call `br` @0x{ins.address:x} without an x30 reload"
            continue
        if m == "blr":
            continue
        if m.startswith("b.") or m in ("cbz", "cbnz", "tbz", "tbnz"):
            target = ins.operands[-1].imm
            if target is not None and local(target):
                stack.append((index[target], reloaded))
            elif not reloaded:
                return f"tail call `{m}` @0x{ins.address:x} -> 0x{target:x} without an x30 reload"
            nk = k + 1
            if nk < len(insns):
                stack.append((nk, reloaded))
            continue
        nk = k + 1
        if nk < len(insns):
            stack.append((nk, reloaded))
    return None


def load_patcher(photon: int, diag: int, ready_scene: int):
    for key in ("KF_PHOTON", "KF_DIAG", "KF_NO_READY_SCENE", "KF_RESULT_DIAG"):
        os.environ.pop(key, None)
    if photon:
        os.environ["KF_PHOTON"] = "1"
    if diag:
        os.environ["KF_DIAG"] = "1"
    if not ready_scene:
        os.environ["KF_NO_READY_SCENE"] = "1"
    name = f"cavehost_{photon}{diag}{ready_scene}"
    spec = importlib.util.spec_from_file_location(name, PATCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_symbols():
    if not SYMBOLS.exists():
        raise SystemExit(
            f"missing {SYMBOLS}; build the RE cache first, e.g.\n"
            f"  python scripts/re/a64dis.py 0x156E8E0 40")
    return pickle.load(open(SYMBOLS, "rb"))[0]


def main() -> int:
    syms = load_symbols()
    addrs = sorted(syms)
    pristine = PRISTINE_SO.read_bytes() if (Cs is not None and PRISTINE_SO.exists()) else None
    bl_cache: dict[int, str | None] = {}

    def containing(addr: int):
        i = bisect.bisect_right(addrs, addr) - 1
        return addrs[i] if i >= 0 else None

    # Load every flavour once and keep the patch tables.
    tables: dict[tuple[int, int, int], list[tuple[int, bytes, str]]] = {}
    cave_offsets: set[int] = set()
    for flav in FLAVOURS:
        mod = load_patcher(*flav)
        rows = [(int(p["offset"]), bytes(p["replacement"]), p.get("description", ""))
                for p in mod.NATIVE_PATCHES["arm64-v8a"]]
        tables[flav] = rows
        for off, rep, desc in rows:
            if is_cave_text(desc) and not is_branch_patch(rep):
                cave_offsets.add(off)

    failures: list[str] = []
    table_rows: list[tuple] = []

    for flav in FLAVOURS:
        rows = tables[flav]
        at: dict[int, tuple[bytes, str]] = {}
        for off, rep, desc in rows:
            at.setdefault(off, (rep, desc))

        # (b) no overlapping writes. Two patches at the SAME offset are an intentional chain (a KF_DIAG
        # override of a production cave/hook, checked by the patcher's expected-vs-actual guard); only a
        # partial overlap (different start, overlapping range) is a real conflict.
        intervals = sorted((off, off + len(rep), desc) for off, rep, desc in rows)
        overlaps = [(a, b) for (a, b) in zip(intervals, intervals[1:]) if b[0] < a[1] and b[0] != a[0]]

        # (a) every cave blob sits in a dead body.
        caves = [(off, rep, desc) for off, rep, desc in rows
                 if is_cave_text(desc) and not is_branch_patch(rep)]
        bad_hosts = []
        for off, rep, desc in caves:
            entry = containing(off)
            if entry is None or entry == off:
                continue  # dwarf/no-symbol or the whole function rewritten in place
            ent = at.get(entry)
            if ent is None:
                bad_hosts.append((off, entry, "host entry not patched in this flavour", desc))
            elif not is_dead_entry(ent[0]):
                bad_hosts.append((off, entry, f"host entry not a dead stub: {ent[0].hex()}", desc))

        # (c) branch hooks whose target lives in another function must hit a cave written here.
        dangling = []
        for off, rep, desc in rows:
            if not is_branch_patch(rep):
                continue
            target = branch_target(off, struct.unpack_from("<I", rep)[0])
            if target is None or containing(target) == containing(off):
                continue
            if target in cave_offsets and target not in at:
                dangling.append((off, target, desc))

        # (d) lint: an entry-hook DIAG cave that reuses w0 for LOG must first save the caller's x0.
        clobbers = []
        if Cs is not None:
            for off, rep, desc in rows:
                if not ("diag" in desc.lower() and is_cave_text(desc) and not is_branch_patch(rep)):
                    continue
                hook = None
                for ho, hr, hd in rows:
                    if is_branch_patch(hr) and (struct.unpack_from("<I", hr)[0] >> 26) == 0b000101 \
                            and branch_target(ho, struct.unpack_from("<I", hr)[0]) == off:
                        hook = ho
                        break
                if hook is None or containing(hook) != hook:
                    continue  # mid-function hook (or no symbol): x0 liveness is cave-specific, not linted
                reason = entry_hook_clobbers_x0(rep, off, hook + 4)
                if reason:
                    clobbers.append((hook, off, reason, desc))

        # (e) lint: a `bl` hook must not clobber a live x30 (after the epilogue restore or before a tail call).
        bl_lr = []
        if Cs is not None and pristine is not None:
            for off, rep, desc in rows:
                if not is_bl_patch(rep):
                    continue
                if off not in bl_cache:
                    bl_cache[off] = bl_hook_clobbers_lr(pristine, syms, addrs, off)
                reason = bl_cache[off]
                if reason:
                    bl_lr.append((off, reason, desc))

        for off, entry, why, desc in bad_hosts:
            failures.append(f"photon={flav[0]} diag={flav[1]} ready={flav[2]} CAVE @{off:#x} "
                            f"host {syms.get(entry, hex(entry))}: {why}\n    {desc[:110]}")
        for a, b in overlaps:
            failures.append(f"photon={flav[0]} diag={flav[1]} ready={flav[2]} OVERLAP "
                            f"{a[0]:#x}..{a[1]:#x} ({a[2][:50]}) vs {b[0]:#x}..{b[1]:#x} ({b[2][:50]})")
        for off, target, desc in dangling:
            failures.append(f"photon={flav[0]} diag={flav[1]} ready={flav[2]} DANGLING HOOK "
                            f"@{off:#x} -> {target:#x} (not written here): {desc[:80]}")
        for hook, off, why, desc in clobbers:
            failures.append(f"photon={flav[0]} diag={flav[1]} ready={flav[2]} X0-CLOBBER entry hook "
                            f"@{hook:#x} -> cave @{off:#x}: {why}\n    {desc[:110]}")
        for off, why, desc in bl_lr:
            failures.append(f"photon={flav[0]} diag={flav[1]} ready={flav[2]} LR-CLOBBER bl hook "
                            f"@{off:#x}: {why}\n    {desc[:110]}")

        n = len(cave_offsets & {off for off, _, _ in caves})
        table_rows.append((flav, len(rows), len(caves), n, len(overlaps), len(bad_hosts),
                           len(dangling), len(clobbers), len(bl_lr)))

    if Cs is None:
        print("WARNING: capstone unavailable; x0-clobber lint (d) and bl/x30 lint (e) skipped.\n")
    elif pristine is None:
        print(f"WARNING: {PRISTINE_SO} missing; bl/x30 lint (e) skipped.\n")
    print("caves x flavours (n = distinct cave blocks asserted; all host entries dead + no overlap + no dangling hook)")
    print(f"{'photon':>6} {'diag':>4} {'ready':>5} {'patches':>7} {'caves':>5} {'n':>4} "
          f"{'overlap':>7} {'bad_host':>8} {'dangling':>8} {'x0_clobber':>10} {'bl_lr':>6}")
    for (photon, diag, ready), patches, caves, n, ov, bh, dh, xc, blr in table_rows:
        print(f"{photon:>6} {diag:>4} {ready:>5} {patches:>7} {caves:>5} {n:>4} "
              f"{ov:>7} {bh:>8} {dh:>8} {xc:>10} {blr:>6}")

    if failures:
        print("\nFAILURES:")
        for line in failures:
            print("  " + line)
        return 1
    print(f"\nOK: {len(FLAVOURS)} flavours, {len(cave_offsets)} distinct cave blocks, all hosts dead, no overlaps.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
