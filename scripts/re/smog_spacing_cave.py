"""Cave generator for the Owlbert (kicker 5) smog patch-spacing data value (handoff/dsh-patch-2).

Goal
----
`Colorful.SmogConditionAction` (dump.cs 573855) lays one smog trap every time the carrier has flown
`_intervalDistance` world units. `CreateSmog` (0x18492F0) closes the loop with

    0x1849618  ldp  s1, s0, [x19, #0x4c]   ; s1 = _intervalDistance, s0 = _smogRadius
    0x184961C  fadd s0, s0, s0             ; step = 2 * _smogRadius
    0x1849620  fadd s0, s1, s0             ; _intervalDistance += step
    0x1849624  str  s0, [x19, #0x4c]

and `Initialize` (0x1849648) seeds

    0x1849834  fmov s1, #1.0
    0x1849838  fadd s1, s0, s1             ; _intervalDistance = Radius + 1
    0x184983C  stp  s1, s0, [x19, #0x4c]   ; _smogRadius      = Radius

Design: `step = S if S > 0 else 2 * _smogRadius`, where S is the served `SpecialSkillTrap` row 5
`interval` column (`TrapInfo.Interval`, +0x48). The first patch also uses S when S > 0. Everything else
(the spawn-position offset `-forward*(_smogRadius+1)`, `TrapInfo.Radius` gameplay area, trap lifetime)
is untouched.

How S is fetched (no `bl`, so no LR/callee-saved FP bookkeeping)
---------------------------------------------------------------
`Initialize` already reads the exact same TrapInfo through
`_setter.Param.GetSpecialSkillTrapInitInfo()` -> `_setter.GetTrapInfo(init)`, and the object layout
(Il2CppDumper `dump.cs`) is

    PlayerCharacter.Param                 +0x180   (get_Param is the leaf `ldr x0,[x0,#0x180]; ret`)
    PlayerParameter.SpecialSkillParameter +0x68
    PlayerSpecialSkilParameter.TrapInfo   +0x38
    TrapInfo.Interval                     +0x48

so the cave walks `[x19,#0x40] -> +0x180 -> +0x68 -> +0x38` with null checks at every hop and reads
`[x0,#0x48]`. No call is made, so x30 and d8-d15 are untouched; s1 (`_intervalDistance`) is never
written. s0 is produced for the continuation at 0x1849620 / s1 for 0x1849840.

Dead bodies (entry-stub to `ret` in production, no incoming branch from outside the stubbed function,
free in EVERY build flavour: KF_PHOTON unset/=1, each with/without KF_DIAG=1, READY_SCENE on/off; see the
companion report + `scripts/re/check_cave_hosts.py`):
  * `HomeSummonModelController.<LoadModelAsync>d__25.MoveNext` 0x159E254 is entry-stubbed (patch at
    0x159E254 `mov w0, wzr; ret`) in all flavours; its whole body 0x159E25C-0x159E354 (248 B) is
    branch-clean and unused by any other production/DIAG cave. The two production caves (112 B) and the
    DIAG override cave (96 B) live there.
  (The earlier dsh-patch-2 revision used `GameManager.BeginReconnectRoomFailed` 0x1578064 and
  `GameManager.BeginReconnectFailed` 0x1577FF8; those entries are `ret`-stubbed only when not
  PHOTON_FLOW, so in KF_PHOTON=1 builds the caves overwrote live code. Fixed in handoff/dsh-patch-3.)

KFDIAG probe (DIAG build only, value 9190 + round(step * 10))
------------------------------------------------------------
The DIAG override cave implements the exact production logic and then logs `9190 + int(step*10)`:
`9220` for S = 3.0, `9270` for the 2R fallback with radius 4.0. Same dead-body rules, `b` hook.

    python scripts/re/smog_spacing_cave.py   # prints the production + DIAG entries
"""
import os
import sys

from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN

_ks = Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN)

LOG = 0x13BC348  # region-E KFDIAG logger: `w0` = value, preserves x0-x18 and q0-q7/q16-q31

# --- SmogConditionAction / TrapInfo layout ----------------------------------------------------------------------
OFF_SETTER = 0x40        # SmogConditionAction._setter (PlayerCharacter)
OFF_SMOG_RADIUS = 0x50   # SmogConditionAction._smogRadius
OFF_PARAM = 0x180        # PlayerCharacter.Param (PlayerParameter), PlayerCharacter.get_Param leaf
OFF_SPECIAL = 0x68       # PlayerParameter.SpecialSkillParameter (PlayerSpecialSkilParameter)
OFF_TRAPINFO = 0x38      # PlayerSpecialSkilParameter.TrapInfo
OFF_S = 0x48             # TrapInfo.Interval (chosen column; see report)

# --- hook sites -------------------------------------------------------------------------------------------------
HOOK_SMOG = 0x184961C    # SmogConditionAction.CreateSmog `fadd s0,s0,s0`
RESUME_SMOG = 0x1849620  # `fadd s0,s1,s0`
HOOK_INIT = 0x184983C    # SmogConditionAction.Initialize `stp s1,s0,[x19,#0x4c]`
RESUME_INIT = 0x1849840

# --- dead bodies -------------------------------------------------------------------------------------------------
# `HomeSummonModelController.<LoadModelAsync>d__25.MoveNext` 0x159E254 is entry-stubbed (`mov w0, wzr; ret`,
# patch at 0x159E254) in EVERY flavour; the whole body 0x159E25C-0x159E354 (248 B) is branch-clean and free in
# every production/DIAG image. Production caves A/B first, the DIAG override cave after them.
PROD_BODY = 0x159E25C    # HomeSummonModelController.<LoadModelAsync>d__25.MoveNext body (entry stub -> ret)
PROD_END = 0x159E354
DIAG_END = PROD_END

LIB = os.environ.get("KF_CLEAN_LIBIL2CPP") or os.path.join(
    os.path.dirname(__file__), "..", "..", ".local", "re", "lib", "arm64-v8a", "libil2cpp.so")


def asm_block(text: str, base: int) -> bytes:
    lines = [ln.split(";")[0].strip() for ln in text.splitlines()]
    src = "\n".join(ln for ln in lines if ln).replace("LOG", hex(LOG))
    enc, _ = _ks.asm(src, base)
    if enc is None:
        raise SystemExit("asm failed at " + hex(base) + ":\n" + src)
    return bytes(enc)


def single(text: str, base: int) -> bytes:
    enc, _ = _ks.asm(text, base)
    if enc is None:
        raise SystemExit("asm failed: " + text)
    return bytes(enc)


def position_independent(word: int) -> bool:
    if (word >> 26) in (0b000101, 0b100101):
        return False
    top = word >> 24
    if top == 0x54 or top in (0x34, 0x35) or top in (0x36, 0x37):
        return False
    if (word & 0x1F000000) == 0x10000000:
        return False
    if (word & 0x3B000000) == 0x18000000:
        return False
    return True


def fetch_s(dst: str) -> str:
    """Walk [x19,#0x40] -> Param -> SpecialSkillParameter -> TrapInfo and load Interval into `dst`.

    x16 is IP0 (intra-procedure-call scratch): clobbering it never disturbs a long-lived value, and the
    walker leaves the original x0 untouched. Every hop is null-checked; a null hop branches to the
    cave-local `fallback` label.
    """
    return f"""
ldr x16, [x19, #{OFF_SETTER:#x}]       ; _setter
cbz x16, fallback
ldr x16, [x16, #{OFF_PARAM:#x}]        ; PlayerCharacter.Param (get_Param leaf)
cbz x16, fallback
ldr x16, [x16, #{OFF_SPECIAL:#x}]      ; PlayerParameter.SpecialSkillParameter
cbz x16, fallback
ldr x16, [x16, #{OFF_TRAPINFO:#x}]     ; PlayerSpecialSkilParameter.TrapInfo
cbz x16, fallback
ldr {dst}, [x16, #{OFF_S:#x}]          ; S = TrapInfo.Interval
fcmp {dst}, #0.0
"""


# Production CreateSmog cave: s0 = S if S > 0 else 2 * _smogRadius, then resume at 0x1849620.
CAVE_SMOG_SRC = fetch_s("s0") + f"""
b.gt done
fallback:
ldr s0, [x19, #{OFF_SMOG_RADIUS:#x}]   ; _smogRadius
fadd s0, s0, s0                        ; 2 * _smogRadius
done:
b #{RESUME_SMOG:#x}
"""

# Production Initialize cave: _intervalDistance = S if S > 0 else Radius + 1, replay the stp.
# S goes into s2 so the displaced `stp s1,s0` still stores Radius (s0) into _smogRadius.
CAVE_INIT_SRC = fetch_s("s2") + f"""
b.le fallback
fmov s1, s2                            ; _intervalDistance = S
fallback:
stp s1, s0, [x19, #0x4c]               ; displaced: _smogRadius = Radius
b #{RESUME_INIT:#x}
"""

# DIAG override CreateSmog cave: the same step, then KFDIAG 9190 + int(step * 10).
CAVE_DIAG_SRC = fetch_s("s0") + f"""
b.gt log
fallback:
ldr s0, [x19, #{OFF_SMOG_RADIUS:#x}]   ; _smogRadius
fadd s0, s0, s0                        ; 2 * _smogRadius
log:
stp x29, x30, [sp, #-0x30]!
stp s0, s1, [sp, #0x10]                ; preserve step (s0) and _intervalDistance (s1) across the log call
fcvtzs w0, s0
mov w1, #10
mul w0, w0, w1                         ; int(step * 10)
mov w1, #0x23e6                        ; 9190
add w0, w0, w1
bl LOG
ldp s0, s1, [sp, #0x10]
ldp x29, x30, [sp], #0x30
b #{RESUME_SMOG:#x}
"""


def entry(desc, offset, code, lib, expected=None):
    exp = bytes(lib[offset:offset + len(code)]) if expected is None else expected
    return (f'    {{"description": "{desc}", "offset": {offset:#x}, '
            f'"expected": bytes.fromhex("{exp.hex()}"), '
            f'"replacement": bytes.fromhex("{code.hex()}")}},')


def hook(desc, offset, orig, replacement, expected=None):
    exp = orig if expected is None else expected
    return (f'    {{"description": "{desc}", "offset": {offset:#x}, '
            f'"expected": bytes.fromhex("{exp.hex()}"), '
            f'"replacement": bytes.fromhex("{replacement.hex()}")}},')


def main() -> None:
    lb = open(LIB, "rb").read()

    # 1. hook-site guards, exactly as in the pristine .so, and not PC-relative.
    for off, what in ((HOOK_SMOG, "CreateSmog fadd s0,s0,s0"),
                      (HOOK_INIT, "Initialize stp s1,s0,[x19,#0x4c]")):
        got = lb[off:off + 4]
        assert position_independent(int.from_bytes(got, "little")), \
            f"{what} @{off:#x}: PC-relative displaced instruction ({got.hex()})"
        print(f"# hook guard {what} @{off:#x} pristine={got.hex()}", file=sys.stderr)

    # 2. assemble the production caves (both in HomeSummonModelController.<LoadModelAsync>d__25.MoveNext).
    cave_smog = asm_block(CAVE_SMOG_SRC, PROD_BODY)
    cave_init = asm_block(CAVE_INIT_SRC, PROD_BODY + len(cave_smog))
    assert PROD_BODY + len(cave_smog) <= PROD_END, f"smog cave {len(cave_smog)} B overflows prod body"
    assert PROD_BODY + len(cave_smog) + len(cave_init) <= PROD_END, \
        f"init cave {len(cave_init)} B overflows prod body"

    # 3. assemble the DIAG override cave, right after the two production caves in the same dead body.
    diag_body = PROD_BODY + len(cave_smog) + len(cave_init)
    cave_diag = asm_block(CAVE_DIAG_SRC, diag_body)
    assert diag_body + len(cave_diag) <= DIAG_END, f"diag cave {len(cave_diag)} B overflows diag body"

    # 4. hooks.
    hook_smog = single(f"b #{PROD_BODY:#x}", HOOK_SMOG)
    hook_init = single(f"b #{PROD_BODY + len(cave_smog):#x}", HOOK_INIT)
    diag_hook = single(f"b #{diag_body:#x}", HOOK_SMOG)  # overrides the production hook byte

    out = []
    out.append("    # ---- Owlbert (5) SS smog: patch spacing = served SpecialSkillTrap.interval when > 0 (handoff/dsh-patch-2) ----")
    out.append("    # SmogConditionAction.CreateSmog (0x184961C) and Initialize (0x184983C). S = _setter.Param")
    out.append("    # .SpecialSkillParameter.TrapInfo.Interval (PlayerCharacter.Param +0x180, PlayerParameter")
    out.append("    # .SpecialSkillParameter +0x68, PlayerSpecialSkilParameter.TrapInfo +0x38, Interval +0x48).")
    out.append("    # Dead body: entry-stubbed HomeSummonModelController.<LoadModelAsync>d__25.MoveNext 0x159E25C-0x159E354 (all flavours).")
    out.append(entry("cave: SmogConditionAction.CreateSmog step = S>0 ? S : 2*_smogRadius (dead body of HomeSummonModelController.<LoadModelAsync>d__25.MoveNext)",
                     PROD_BODY, cave_smog, lb))
    out.append(hook("SmogConditionAction.CreateSmog `fadd s0,s0,s0` -> b smog spacing cave",
                    HOOK_SMOG, lb[HOOK_SMOG:HOOK_SMOG + 4], hook_smog))
    out.append(entry("cave: SmogConditionAction.Initialize first-patch _intervalDistance = S>0 ? S : Radius+1 (dead body of HomeSummonModelController.<LoadModelAsync>d__25.MoveNext)",
                     PROD_BODY + len(cave_smog), cave_init, lb))
    out.append(hook("SmogConditionAction.Initialize `stp s1,s0,[x19,#0x4c]` -> b smog first-patch cave",
                    HOOK_INIT, lb[HOOK_INIT:HOOK_INIT + 4], hook_init))
    out.append("")
    out.append("    # ---- DIAG (KFDIAG 9190+): smog spacing override, logs 9190 + int(step*10) ----")
    out.append("    # Generated by scripts/re/smog_spacing_cave.py. Hooks EXPECT the production hook bytes above")
    out.append("    # (production patches are applied first) and redirect them to the logging cave.")
    out.append(entry("DIAG cave: CreateSmog step -> 9190 + int(step*10) (9220 with S=3, 9270 with radius 4 fallback) (same always-dead MoveNext body)",
                     diag_body, cave_diag, lb))
    out.append(hook("DIAG hook: SmogConditionAction.CreateSmog `fadd s0,s0,s0` -> b logging override cave",
                    HOOK_SMOG, lb[HOOK_SMOG:HOOK_SMOG + 4], diag_hook, expected=hook_smog))
    print("\n".join(out))
    print(f"# sizes: prod_smog={len(cave_smog)} prod_init={len(cave_init)} diag={len(cave_diag)}", file=sys.stderr)


if __name__ == "__main__":
    main()
