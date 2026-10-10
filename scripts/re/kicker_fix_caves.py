"""Caves for the two 2.11.0 client fixes (2026-10-09, handoff/dsh-patch-1):
  * Owlbert (kicker 5) special skill "smog": create the NPCSSDrone when EITHER the caster (`_setter`) or the
    carrier (`_target`) is local, instead of only the caster. For a remote human ally the caster's client owns
    the caster but not the target and the ally's client owns the target but not the caster, so with the retail
    `_setter.IsMine()` gate the drone (and every smog patch) was created by neither client. The retail
    one-instruction swap `ldr x20,[x19,#0x40] -> [x19,#0x38]` was rejected: it drops the drone on the caster's
    client for a remote ally.
  * Anna (kicker 8) "Binding Ray": when the Restrainted condition (14) lands on the victim,
    `RestraintedConditionAction.StartAction` must also give the CASTER her trigger-3 ("Execute") kicker-skill
    conditions. The client already expects Restraint (15) on the caster (`GunSkillAction.OnUpdateAction` /
    `UpdateFinish` gate their `StopVelocity` on `IsExists(15)`), but no data path in 2.11.0 ever applies it:
    `GunSkillAction` never calls `GetKickerSkillConditionInitInfo(3)`. The cave reproduces the
    `LaserSkillAction.OnBeginAction` pattern (0x16DB808: `GetKickerSkillConditionInitInfo(3)` ->
    `GameManager.GetConditionID` -> `PlayerCharacter.AcceptCondition`).

RFERENCES: handoff/dsh-owlbert-1/report.md (Q4/Q5), handoff/dsh-owlbert-2/report.md, handoff/dsh-anna-1/report.md §4.

Hook sites (pristine `libil2cpp.so`, RVA == file offset)
--------------------------------------------------------
A. `SmogConditionAction.StartAction` @0x18498D4
     0x18498E4  ldr x20, [x19, #0x40]      ; `_setter` (the caster)
     0x18498FC  bl  CharacterBase.IsMine
     0x1849900  tbz w0, #0, #0x1849914     ; not mine -> return
     0x1849904  <epilogue> b CreateDrone
     0x1849914  <epilogue> ret
   Hook 0x18498E4 with `b CAVE_A`; the cave replays the load, evaluates
   `_setter.IsMine() || _target.IsMine()` null-safely (`_target` @0x38, `_setter` @0x40) and branches to the
   original CreateDrone epilogue (0x1849904) or the return epilogue (0x1849914).

B. `RestraintedConditionAction.StartAction` @0x1881AA8
     0x1881BCC  mov x0, x19                ; x0 = this
     0x1881BD0  mov x1, xzr
     0x1881BD4  str x8, [x19, #0x40]       ; `_setterPlayer` (computed from info.SetterId)
     0x1881BD8  bl  ConditionActionBase.get_Target   ; uses x0 = this
   Hook 0x1881BD4 with `b CAVE_B`; the cave replays the store, then
   `PlayerCharacter.get_Param` (0x13BE270) -> `PlayerParameter.GetKickerSkillConditionInitInfo(3)` (0x1757E90)
   -> (non-null) `PlayerCharacter.AcceptCondition` and finally restores x0=this/x1=0 and continues at 0x1881BD8.
   `AcceptCondition` is called through the SAME vtable slot Laser uses (klass+0x3e8 / MethodInfo +0x3f0).

Dead bodies (verified this session: entry stub to `ret` in production, full b/bl/b.cond/cbz/tbz sweep over the
pristine .so with zero incoming branches from outside the stubbed function, and free in BOTH the production and
the KF_DIAG patch images)
----------------------------------------------------------------------------------------------------------------
   * production cave A @0x13BA15C, 56 bytes free — tail of the entry-stubbed `PlayerBoneController.LateUpdate`
     (entry 0x13BA08C -> `ret`).
   * production cave B @0x13BA8BC, 56 bytes free — tail of the entry-stubbed
     `PlayerBoneController.InterpolationUpdate` (entry 0x13BA65C -> `ret`).
   * DIAG override cave A @0x1A2AC54, 220 bytes free — body of the always-entry-stubbed
     `PhotonPropertyManagerBase<object>.StartDisconnectTime` (entry 0x1A2AC50 -> `ret` in EVERY flavour;
     this one was already fine and is not moved). Since dsh-patch-4 its free tail 0x1A2ACD0-0x1A2AD30 holds the
     SendAddTrap 9104 probe (the entry hook needs a full x0-x7 + q0-q7 save).
   * DIAG override cave B @0x1A2AB64, 236 bytes free — body of the always-entry-stubbed
     `PhotonPropertyManagerBase<object>.CheckInitializeError` (entry 0x1A2AB5C -> `mov w0,#0; ret` in EVERY
     flavour). The Anna override (DIAG_B), the CreateSmog owner probe (DIAG_SMOG) and the RestraintConditionAction
     9110 probe (DIAG_R15) live there.
     (dsh-patch-1 had DIAG_B in `GameManager.BeginReconnectFailed` 0x1577F98 and DIAG_SMALL in
     `GameManager.InitializeReconnect` 0x15704B0; those entries are `ret`-stubbed only when not PHOTON_FLOW,
     so in KF_PHOTON=1 builds the caves overwrote live code. Fixed in handoff/dsh-patch-3.)
   * The existing kicker DIAG block / reconnect probes that lived in `InitializeReconnect` are gated to the
     offline flow in `patch-il2cpp-endpoints.py` (no always-dead space to relocate them); see dsh-patch-3.

KFDIAG probes (DIAG build only, values 9100-9199)
-------------------------------------------------
Owlbert (patch A):
  9100  setter.IsMine()          (1 = the caster is local)
  9101  target.IsMine()          (1 = the carrier is local)
  9102  result = 9100 | 9101     (the value the production cave branches on)
  9103  CreateSmog owner match reached (`w20 == local actor` -> trap is sent)
  9104  `ObjectManager.SendAddTrap` entered (one call per smog patch actually sent)
Anna (patch B):
  9110  RestraintConditionAction.StartAction (condition 15) entered on the caster
  9111  RestraintedConditionAction.StartAction cave entered with `_setterPlayer != null`
  9112  `GetKickerSkillConditionInitInfo(3)` returned non-null
  9113  `AcceptCondition` returned (the trigger-3 row was applied to the caster)
The DIAG override caves implement the EXACT production logic and only add the log calls; the production hook at
0x18498E4 / 0x1881BD4 is redirected to them with `expected` = the production hook bytes.

    python scripts/re/kicker_fix_caves.py   # prints the production + DIAG entries for patch-il2cpp-endpoints.py
"""
import os

from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN

_ks = Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN)

LOG = 0x13BC348  # region-E KFDIAG logger: `w0` = value, preserves x0-x18 and q0-q7/q16-q31

# --- external method addresses (re-verified in this session) ---------------------------------------------------
ISMINE = 0x16B69BC          # Colorful.CharacterBase.IsMine()
GET_PARAM = 0x13BE270       # Colorful.PlayerCharacter.get_Param -> PlayerParameter
GET_KSCII = 0x1757E90       # Colorful.PlayerParameter.GetKickerSkillConditionInitInfo(trigger)
ACCEPT_COND = 0x13DD938     # Colorful.PlayerCharacter.AcceptCondition(ConditionInitializeInfo)

# --- hook sites ------------------------------------------------------------------------------------------------
HOOK_A = 0x18498E4          # SmogConditionAction.StartAction: ldr x20,[x19,#0x40]
HOOK_A_DRONE = 0x1849904    # original epilogue -> b CreateDrone
HOOK_A_RETURN = 0x1849914   # original epilogue -> ret
HOOK_B = 0x1881BD4          # RestraintedConditionAction.StartAction: str x8,[x19,#0x40]
HOOK_B_NEXT = 0x1881BD8     # bl ConditionActionBase.get_Target (needs x0 = this)
HOOK_SMOG = 0x1849378       # SmogConditionAction.CreateSmog: cmp w20,w0 (owner gate)
HOOK_SMOG_MATCH = 0x1849380
HOOK_SMOG_NOMATCH = 0x1849628
HOOK_R15 = 0x1880D84        # RestraintConditionAction.StartAction entry (condition 15)
HOOK_TRAP = 0x1401868       # ObjectManager.SendAddTrap entry (one call per smog patch)

# --- dead bodies -----------------------------------------------------------------------------------------------
CAVE_A = 0x13BA15C
CAVE_A_END = 0x13BA194
CAVE_B = 0x13BA8BC
CAVE_B_END = 0x13BA8F4
DIAG_A = 0x1A2AC54
DIAG_A_END = 0x1A2AD30
# Always-dead body of PhotonPropertyManagerBase<object>.CheckInitializeError (entry 0x1A2AB5C -> `mov w0,#0; ret`).
DIAG_B = 0x1A2AB64
DIAG_BODY2_END = 0x1A2AC50
DIAG_SMALL_END = DIAG_BODY2_END

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


# --------------------------------------------------------------------------------------------------------------
# Production cave A: cond = _setter.IsMine() || _target.IsMine(), then the original epilogues.
CAVE_A_SRC = f"""
ldr x20, [x19, #0x40]           ; displaced: _setter
cbz x20, check_target
mov x0, x20
bl #{ISMINE:#x}                  ; _setter.IsMine()
cbnz w0, take_drone
check_target:
ldr x0, [x19, #0x38]            ; _target
cbz x0, no_drone
bl #{ISMINE:#x}                  ; _target.IsMine()
cbnz w0, take_drone
no_drone:
b #{HOOK_A_RETURN:#x}
take_drone:
b #{HOOK_A_DRONE:#x}
"""

# Production cave B: give the setter her trigger-3 kicker-skill conditions.
CAVE_B_SRC = f"""
str x8, [x19, #0x40]            ; displaced: _setterPlayer
cbz x8, done
mov x20, x8
mov x0, x20
bl #{GET_PARAM:#x}               ; PlayerCharacter.get_Param -> PlayerParameter
orr w1, wzr, #3                 ; ConditionTriggerType.Execute
bl #{GET_KSCII:#x}               ; PlayerParameter.GetKickerSkillConditionInitInfo(3)
cbz x0, done
mov x1, x0
mov x0, x20
bl #{ACCEPT_COND:#x}             ; PlayerCharacter.AcceptCondition(initInfo)
done:
mov x0, x19
mov x1, xzr
b #{HOOK_B_NEXT:#x}
"""

# DIAG override cave A: the same decision, logging setter/target IsMine and the OR result.
DIAG_A_SRC = f"""
ldr x20, [x19, #0x40]           ; displaced: _setter
sub sp, sp, #0x30
str wzr, [sp, #0x10]            ; setter.IsMine
str wzr, [sp, #0x18]            ; target.IsMine
cbz x20, no_setter
mov x0, x20
bl #{ISMINE:#x}
str w0, [sp, #0x10]
mov w1, #9100
add w0, w0, w1
bl LOG
no_setter:
ldr x8, [x19, #0x38]            ; _target
cbz x8, no_target
mov x0, x8
bl #{ISMINE:#x}
str w0, [sp, #0x18]
mov w1, #9101
add w0, w0, w1
bl LOG
no_target:
ldr w0, [sp, #0x10]
ldr w1, [sp, #0x18]
orr w0, w0, w1
str w0, [sp, #0x20]
mov w1, #9102
add w0, w0, w1
bl LOG
ldr w0, [sp, #0x20]
add sp, sp, #0x30
cbnz w0, take_drone
b #{HOOK_A_RETURN:#x}
take_drone:
b #{HOOK_A_DRONE:#x}
"""

# DIAG override cave B: the same logic, logging cave entry / non-null initInfo / AcceptCondition.
DIAG_B_SRC = f"""
str x8, [x19, #0x40]            ; displaced: _setterPlayer
cbz x8, done
mov x20, x8
mov w0, #9111
bl LOG                          ; cave entered, _setterPlayer != null
mov x0, x20
bl #{GET_PARAM:#x}
orr w1, wzr, #3
bl #{GET_KSCII:#x}
cbz x0, done
mov x21, x0
mov w0, #9112
bl LOG                          ; initInfo non-null
mov x0, x20
ldr x8, [x0]                    ; klass
ldr x9, [x8, #0x3e8]            ; PlayerCharacter.AcceptCondition (same slot Laser uses)
ldr x2, [x8, #0x3f0]            ; MethodInfo
mov x1, x21
blr x9
mov w0, #9113
bl LOG                          ; AcceptCondition returned
done:
mov x0, x19
mov x1, xzr
b #{HOOK_B_NEXT:#x}
"""

# DIAG CreateSmog owner-match probe (mid hook at the `cmp w20,w0`).
DIAG_SMOG_SRC = f"""
cmp w20, w0
cset w8, eq
mov w0, #9103
add w0, w0, w8
bl LOG
cbnz w8, match
b #{HOOK_SMOG_NOMATCH:#x}
match:
b #{HOOK_SMOG_MATCH:#x}
"""

# DIAG RestraintConditionAction.StartAction (condition 15) entry probe.
# ENTRY hook: x0-x7 are the function's live arguments at the continuation, so save/restore every one of them
# around the LOG call. The region-E LOG helper returns x0 = the value it was given (its argument), so an
# unsaved x0 would make the function run with a fake `this`=9110 and crash on the first field read
# (handoff/dsh-patch-4 root cause of the "libunity+0x34426c" fault addr 0x23ac/0x23a4).
DIAG_R15_SRC = f"""
stp x29, x30, [sp, #-0x50]!
stp x0, x1, [sp, #0x10]
stp x2, x3, [sp, #0x20]
stp x4, x5, [sp, #0x30]
stp x6, x7, [sp, #0x40]
mov w0, #9110
bl LOG
ldp x6, x7, [sp, #0x40]
ldp x4, x5, [sp, #0x30]
ldp x2, x3, [sp, #0x20]
ldp x0, x1, [sp, #0x10]
ldp x29, x30, [sp], #0x50
stp x20, x19, [sp, #-0x20]!     ; displaced prologue instruction
b #{HOOK_R15 + 4:#x}
"""

# DIAG ObjectManager.SendAddTrap entry probe: one log per trap actually sent (the smog patches).
# ENTRY hook: save x0-x7 and the FP/vector arguments (q0-q7 = s0-s7) around the LOG call. LOG itself preserves
# q0-q7, but the explicit save keeps this cave correct independent of that helper's contract.
DIAG_TRAP_SRC = f"""
stp x29, x30, [sp, #-0xd0]!
stp x0, x1, [sp, #0x10]
stp x2, x3, [sp, #0x20]
stp x4, x5, [sp, #0x30]
stp x6, x7, [sp, #0x40]
stp q0, q1, [sp, #0x50]
stp q2, q3, [sp, #0x70]
stp q4, q5, [sp, #0x90]
stp q6, q7, [sp, #0xb0]
mov w0, #9104
bl LOG
ldp q6, q7, [sp, #0xb0]
ldp q4, q5, [sp, #0x90]
ldp q2, q3, [sp, #0x70]
ldp q0, q1, [sp, #0x50]
ldp x6, x7, [sp, #0x40]
ldp x4, x5, [sp, #0x30]
ldp x2, x3, [sp, #0x20]
ldp x0, x1, [sp, #0x10]
ldp x29, x30, [sp], #0xd0
str d14, [sp, #-0x70]!          ; displaced prologue instruction
b #{HOOK_TRAP + 4:#x}
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
    lib = open(LIB, "rb").read()

    # 1. hook-site guards, exactly as in the pristine .so
    guards = [
        (HOOK_A, "742240f9", "SmogConditionAction.StartAction ldr x20,[x19,#0x40]"),
        (HOOK_B, "682200f9", "RestraintedConditionAction.StartAction str x8,[x19,#0x40]"),
        (HOOK_SMOG, "9f02006b", "SmogConditionAction.CreateSmog cmp w20,w0"),
        (HOOK_R15, "f44fbea9", "RestraintConditionAction.StartAction stp x20,x19,[sp,#-0x20]!"),
        (HOOK_TRAP, "ee0f19fc", "ObjectManager.SendAddTrap str d14,[sp,#-0x70]!"),
    ]
    for off, want, what in guards:
        got = lib[off:off + 4]
        assert got.hex() == want, f"{what} @{off:#x}: expected {want}, found {got.hex()}"
        assert position_independent(int.from_bytes(got, "little")), f"{what}: PC-relative displaced instruction"

    # 2. assemble the production caves
    cave_a = asm_block(CAVE_A_SRC, CAVE_A)
    cave_b = asm_block(CAVE_B_SRC, CAVE_B)
    assert CAVE_A + len(cave_a) <= CAVE_A_END, f"cave A {len(cave_a)} B > {CAVE_A_END - CAVE_A}"
    assert CAVE_B + len(cave_b) <= CAVE_B_END, f"cave B {len(cave_b)} B > {CAVE_B_END - CAVE_B}"

    # 3. assemble the DIAG caves
    diag_a = asm_block(DIAG_A_SRC, DIAG_A)
    diag_b = asm_block(DIAG_B_SRC, DIAG_B)
    diag_small = DIAG_B + len(diag_b)          # right after the Anna override in the same dead body
    diag_smog = asm_block(DIAG_SMOG_SRC, diag_small)
    diag_r15 = asm_block(DIAG_R15_SRC, diag_small + len(diag_smog))
    # The full-argument SendAddTrap probe (88 B) no longer fits next to the R15 probe in CheckInitializeError,
    # so it moves to the free tail of the always-dead StartDisconnectTime body, right after DIAG_A.
    diag_trap = asm_block(DIAG_TRAP_SRC, DIAG_A + len(diag_a))
    assert DIAG_A + len(diag_a) + len(diag_trap) <= DIAG_A_END, \
        f"diag trap {len(diag_trap)} B does not fit in the StartDisconnectTime tail"
    assert DIAG_B + len(diag_b) <= DIAG_BODY2_END, f"diag B {len(diag_b)} B > {DIAG_BODY2_END - DIAG_B}"
    assert diag_small + len(diag_smog) + len(diag_r15) <= DIAG_SMALL_END, \
        "diag small block does not fit"

    # 4. hook replacements
    hook_a = single(f"b #{CAVE_A:#x}", HOOK_A)
    hook_b = single(f"b #{CAVE_B:#x}", HOOK_B)
    # DIAG redirects the production hook to the logging override (production applied first)
    diag_hook_a = single(f"b #{DIAG_A:#x}", HOOK_A)
    diag_hook_b = single(f"b #{DIAG_B:#x}", HOOK_B)
    hook_smog = single(f"bl #{diag_small:#x}", HOOK_SMOG)
    hook_r15 = single(f"b #{diag_small + len(diag_smog):#x}", HOOK_R15)
    diag_trap_at = DIAG_A + len(diag_a)
    hook_trap = single(f"b #{diag_trap_at:#x}", HOOK_TRAP)

    out = []
    out.append("    # ---- Owlbert (5) SS smog: create the drone when the caster OR the carrier is local (patch A) ----")
    out.append("    # handoff/dsh-owlbert-1/report.md Q4/Q5, handoff/dsh-owlbert-2/report.md. Hook site 0x18498E4")
    out.append("    # (SmogConditionAction.StartAction `ldr x20,[x19,#0x40]`); cave replays it and branches to the")
    out.append("    # original CreateDrone (0x1849904) / return (0x1849914) epilogues. Dead body: LateUpdate tail.")
    out.append(entry("cave: SmogConditionAction.StartAction -> drone if _setter.IsMine() || _target.IsMine() (dead body of PlayerBoneController.LateUpdate)",
                     CAVE_A, cave_a, lib))
    out.append(hook("SmogConditionAction.StartAction `ldr x20,[x19,#0x40]` -> b smog drone-gate cave",
                    HOOK_A, lib[HOOK_A:HOOK_A + 4], hook_a))
    out.append("    # ---- Anna (8) Binding Ray: give the caster her trigger-3 conditions when the bind (14) lands (patch B) ----")
    out.append("    # handoff/dsh-anna-1/report.md section 4. Hook site 0x1881BD4 (RestraintedConditionAction.StartAction")
    out.append("    # `str x8,[x19,#0x40]`); cave reproduces LaserSkillAction.OnBeginAction's AcceptCondition call.")
    out.append("    # Dead body: PlayerBoneController.InterpolationUpdate tail.")
    out.append(entry("cave: RestraintedConditionAction.StartAction -> setter.AcceptCondition(GetKickerSkillConditionInitInfo(3)) (dead body of PlayerBoneController.InterpolationUpdate)",
                     CAVE_B, cave_b, lib))
    out.append(hook("RestraintedConditionAction.StartAction `str x8,[x19,#0x40]` -> b Anna bind-root cave",
                    HOOK_B, lib[HOOK_B:HOOK_B + 4], hook_b))
    out.append("")
    out.append("    # ---- DIAG (KFDIAG 9100-9199): override caves + owner-match probe; DIAG_PATCHES_ARM64 only ----")
    out.append("    # Generated by scripts/re/kicker_fix_caves.py. The override hooks expect the PRODUCTION hook bytes")
    out.append("    # above (production patches are applied first) and redirect them to the logging caves.")
    out.append(entry("DIAG cave: smog drone-gate decision, logs 9100 setter.IsMine / 9101 target.IsMine / 9102 result (dead body of StartDisconnectTime)",
                     DIAG_A, diag_a, lib))
    out.append(hook("DIAG hook: SmogConditionAction.StartAction `ldr x20,[x19,#0x40]` -> b logging override cave",
                    HOOK_A, lib[HOOK_A:HOOK_A + 4], diag_hook_a, expected=hook_a))
    out.append(entry("DIAG cave: Anna bind-root cave, logs 9111 cave entered / 9112 initInfo!=null / 9113 AcceptCondition (dead body of CheckInitializeError)",
                     DIAG_B, diag_b, lib))
    out.append(hook("DIAG hook: RestraintedConditionAction.StartAction `str x8,[x19,#0x40]` -> b logging override cave",
                    HOOK_B, lib[HOOK_B:HOOK_B + 4], diag_hook_b, expected=hook_b))
    out.append(entry("DIAG cave: CreateSmog owner gate -> 9103 when w20==local actor (dead body of CheckInitializeError)",
                     diag_small, diag_smog, lib))
    out.append(hook("DIAG hook: SmogConditionAction.CreateSmog `cmp w20,w0` -> bl owner-match probe",
                    HOOK_SMOG, lib[HOOK_SMOG:HOOK_SMOG + 4], hook_smog))
    out.append(entry("DIAG cave: RestraintConditionAction.StartAction entry -> 9110 (condition 15 started) (dead body of CheckInitializeError)",
                     diag_small + len(diag_smog), diag_r15, lib))
    out.append(hook("DIAG hook: RestraintConditionAction.StartAction entry -> b 9110 probe",
                    HOOK_R15, lib[HOOK_R15:HOOK_R15 + 4], hook_r15))
    out.append(entry("DIAG cave: ObjectManager.SendAddTrap entry -> 9104 (one per smog patch) (dead body of StartDisconnectTime)",
                     diag_trap_at, diag_trap, lib))
    out.append(hook("DIAG hook: ObjectManager.SendAddTrap entry -> b 9104 probe",
                    HOOK_TRAP, lib[HOOK_TRAP:HOOK_TRAP + 4], hook_trap))
    print("\n".join(out))
    print(f"# sizes: caveA={len(cave_a)} caveB={len(cave_b)} diagA={len(diag_a)} diagB={len(diag_b)} "
          f"smog={len(diag_smog)} r15={len(diag_r15)} trap={len(diag_trap)}", file=__import__("sys").stderr)


if __name__ == "__main__":
    main()
