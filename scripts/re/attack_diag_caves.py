"""DIAG probes for the basic (auto) attack loop of every weapon - WeaponAttackActionBase (2026-09-20).

Shows, per frame, why the kicker does or does not swing and which combo step it plays:

  8100+n  AddComboCount: an attack was just started, n = combo index (0/1/2 = hit 1/2/3) - a 0 right after a 0 or
          a 1 means the combo was reset (target lost -> ResetComboCount) instead of chaining
  8210    JapaneseSword UpdateAction: IsReset (target == null) -> combo reset
  8211    JapaneseSword UpdateAction: IsUpdateAction false -> combo reset
  8230    IsUpdateAction false, followed by its inputs (+1 = true): 8710 IsSynchronized, 8720 EnableAttack,
          8730 EnableTransitionMotion, 8740 IsCurrentState(Normal), 8750 IsLand, 8760 IsCrouch, 8770 SS targeting,
          8790+n current PlayerStateType (0 Normal, 1 Avoid, 2 TurnAround, 3 BarrelRoll, 4 BackStep, 5 KickTurn,
          6 BlowOff, 7 PullIn, 8 KnockBack, 9 Dead, 10 Revival, 11 Skill, 12 Deposit, 13 SpecialSkill)
  8220    SS gauge full while SS targeting is active (attack loop suspended)
  8300/8301  IsTargetInAttackSearchDistance: target out of / in range (attackTargetSearchDistance x speed weight)
  8320 dx lim   IsAttack, idle: |yaw delta| vs limit (IDLE_ATTACKABLE_ANGLE_X 60 / weight)
  8321 dy lim   IsAttack, idle: |pitch delta| vs limit (30 / weight)
  8322 dx lim   IsAttack, moving: |yaw delta| vs limit (MOVE 90 / LOCK_ON 145, / weight)
  8323 dy lim   IsAttack, moving: |pitch delta| vs the same limit
  8310    IsAttack returned true -> Attack() this frame
  8400+n  PlayAttackIn(comboCount n)        (idle swing / shot)
  8500+n  PlayMoveAttackIn(comboCount n)    (attack while flying)
  8600+n  PlayGroundMoveAttackIn(comboCount n)
  8800+t  CollisionBase.OnDestroy: t = 0 None / 1 Hit / 2 LifeTime / 3 ForceRemove (LifeTime on an attack collision
          = CallbackAttackCollisionDestroy sets _isAttackMiss + Target null -> combo reset), then 8810+hits

Minimal caves (no full register save): the region-E LOG helper (0x13BC348 -> region E) preserves x0-x18 and
q0-q7/q16-q31, the callee-saved registers survive by ABI, only NZCV is lost - so a probe on an `fcmp` re-executes
the compare after logging. Caves live in the dead body of the entry-stubbed PlayerBoneController.InterpolationUpdate
(0x13BA660-0x13BA8F4), SetPose (0x13BA8F8-0x13BAA7C) and LateUpdate (0x13BA090-0x13BA194).

    python scripts/re/attack_diag_caves.py   # prints the DIAG_PATCHES_ARM64 entries
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from mkcave import asm, LOG  # noqa: E402
from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN  # noqa: E402

_ks = Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN)


def asm_block(text: str, base: int) -> bytes:
    """Whole-block assembly (labels allowed), unlike mkcave.asm which goes line by line."""
    lines = [ln.split(";")[0].strip() for ln in text.splitlines()]
    src = chr(10).join(ln for ln in lines if ln).replace("LOG", hex(LOG))
    enc, count = _ks.asm(src, base)
    if enc is None:
        raise SystemExit("asm failed: " + src)
    return bytes(enc)

LIB = os.path.join(os.path.dirname(__file__), "..", "..", ".local", "re", "lib", "arm64-v8a", "libil2cpp.so")
REGIONS = [(0x13BA660, 0x13BA8F4), (0x13BA8F8, 0x13BAA7C), (0x13BA090, 0x13BA194),
           (0x13CE3E0, 0x13CE500)]   # PlayerCharacter.UpdateIdleTypeRate up to the production bat-bomb cave (0x13CE500)

# Only the human's action is interesting (the gym mannequins run the same code every frame): a probe body may start
# with one of these guards, which jump to the cave's epilogue for AI-driven players (PlayerCharacter._enableAi +0xE0).
HUMAN_ACTION = """
ldr x8, [x19, #0x18]        ; WeaponAttackActionBase._player
ldrb w8, [x8, #0xe0]
cbnz w8, skip
"""
HUMAN_PLAYER = """
ldrb w8, [x19, #0xe0]       ; PlayerCharacter._enableAi
cbnz w8, skip
"""

# (hook addr, displaced instruction(s) re-executed at the end, body, description)
# body runs with x29/x30, x0/x1, x8-x10 and q16 saved on the stack (restored before the displaced instruction)
PROBES = [
    (0x181C8E8, "ldr w8, [x19, #0x60]", """
ldr w8, [x19, #0x60]        ; _totalComboCount before the increment
mov w9, #3
udiv w10, w8, w9
msub w8, w10, w9, w8        ; % MaxComboCount (3 WeaponAttack rows for every kicker)
mov w1, #8100
add w0, w8, w1
bl LOG
""", "WeaponAttackActionBase.AddComboCount -> 8100 + combo index just attacked"),
    (0x151E674, "mov x0, x19", HUMAN_ACTION + """
mov w0, #8210
bl LOG
""", "JapaneseSwordAttackAction.UpdateAction: IsReset (target null) -> ResetComboCount -> 8210"),
    (0x151E6C0, "mov x0, x19", HUMAN_ACTION + """
mov w0, #8211
bl LOG
""", "JapaneseSwordAttackAction.UpdateAction: IsUpdateAction false -> ResetComboCount -> 8211"),
    (0x181AD0C, "mov w0, wzr", """
; x19 is NOT `this` here: IsUpdateAction reuses it for the state routine (0x181AC90) - the first version of this
; probe dereferenced it and crashed the DIAG build on the loading screen 5/5 (2026-09-20). The caller's x19 (every
; weapon UpdateAction keeps its action in x19 and calls this.IsUpdateAction()) is saved at [sp,#0x18] of this frame,
; i.e. [sp,#0x68] after our own 0x50 push. x19-x21 are free to clobber: the epilogue reloads them from the stack.
ldr x19, [sp, #0x68]
cbz x19, skip
ldr x20, [x19, #0x18]       ; _player
cbz x20, skip
ldrb w8, [x20, #0xe0]       ; human only
cbnz w8, skip
mov w0, #8230
bl LOG
mov x0, x20
mov x1, xzr
bl #0x16b6a94               ; CharacterBase.get_IsSynchronized
and w0, w0, #1
mov w1, #8710
add w0, w0, w1
bl LOG
mov x0, x20
mov x1, xzr
bl #0x16b697c               ; CharacterBase.get_ConditionActionCtr
mov x21, x0
cbz x21, no_ctr
mov x0, x21
mov x1, xzr
bl #0x17bcd04               ; ConditionActionController.get_EnableAttack
and w0, w0, #1
mov w1, #8720
add w0, w0, w1
bl LOG
mov x0, x21
mov x1, xzr
bl #0x17bcde0               ; get_EnableTransitionMotion
and w0, w0, #1
mov w1, #8730
add w0, w0, w1
bl LOG
no_ctr:
mov x0, x20
mov w1, wzr
mov x2, xzr
bl #0x13bdff0               ; PlayerCharacter.IsCurrentState(Normal)
and w0, w0, #1
mov w1, #8740
add w0, w0, w1
bl LOG
mov x0, x20
mov x1, xzr
bl #0x13cab6c               ; PlayerCharacter.GetCurrentState -> 8790 + PlayerStateType (Normal 0, Avoid 1, ... Skill 11)
mov w1, #8790
add w0, w0, w1
bl LOG
mov x0, x20
mov w1, wzr
mov x2, xzr
bl #0x13c0928               ; GetStateRoutine(Normal)
mov x21, x0
cbz x21, no_routine
mov x0, x21
mov x1, xzr
bl #0x17e6d48               ; PlayerStateNormal.IsLand
and w0, w0, #1
mov w1, #8750
add w0, w0, w1
bl LOG
mov x0, x21
mov x1, xzr
bl #0x17e6d24               ; PlayerStateNormal.IsCrouch
and w0, w0, #1
mov w1, #8760
add w0, w0, w1
bl LOG
no_routine:
ldrb w0, [x20, #0x2a8]      ; IsUpdateSpecialSkillTargetting
mov w1, #8770
add w0, w0, w1
bl LOG
""", "WeaponAttackActionBase.IsUpdateAction -> 8230 (false) + reasons 8710 sync/8720 enableAttack/8730 transitionMotion/8740 stateNormal/8750 land/8760 crouch/8770 ssTargeting (+1 = true; human only)"),
    (0x181AC68, "mov x1, xzr", """
mov w0, #8220
bl LOG
""", "IsUpdateAction: SS gauge full while SS targeting is up -> 8220 (attacks suspended if EnableSpecialSkill)"),
    (0x13C6C2C, "fcmp s9, s0\ncset w0, ls", HUMAN_PLAYER + """
fcmp s9, s0
cset w0, ls
mov w1, #8300
add w0, w0, w1
bl LOG
""", "PlayerCharacter.IsTargetInAttackSearchDistance -> 8300 out of range / 8301 in range"),
    (0x181C198, "fcmp s1, s0", HUMAN_ACTION + """
mov w0, #8320
bl LOG
fabs s16, s1
fcvtzs w0, s16
bl LOG
fcvtzs w0, s0
bl LOG
""", "IsAttack idle yaw check -> 8320, |dx|, limit"),
    (0x181C1C4, "fcmp s0, s1", HUMAN_ACTION + """
mov w0, #8321
bl LOG
fabs s16, s0
fcvtzs w0, s16
bl LOG
fcvtzs w0, s1
bl LOG
""", "IsAttack idle pitch check -> 8321, |dy|, limit"),
    (0x181C1F8, "fcmp s1, s8", HUMAN_ACTION + """
mov w0, #8322
bl LOG
fabs s16, s1
fcvtzs w0, s16
bl LOG
fcvtzs w0, s8
bl LOG
""", "IsAttack moving yaw check -> 8322, |dx|, limit"),
    (0x181C21C, "fcmp s0, s8", HUMAN_ACTION + """
mov w0, #8323
bl LOG
fabs s16, s0
fcvtzs w0, s16
bl LOG
fcvtzs w0, s8
bl LOG
""", "IsAttack moving pitch check -> 8323, |dy|, limit"),
    (0x181C224, "orr w0, wzr, #1", """
mov w0, #8310
bl LOG
""", "IsAttack -> 8310 (true: attack this frame)"),
    (0x181E518, "mov x22, x0", """
mov w0, #8400
add w0, w0, w1
bl LOG
""", "WeaponAttackActionBase.PlayAttackIn -> 8400 + comboCount"),
    (0x181E5B0, "mov x22, x0", """
mov w0, #8500
add w0, w0, w1
bl LOG
""", "WeaponAttackActionBase.PlayMoveAttackIn -> 8500 + comboCount"),
    (0x181E648, "mov x22, x0", """
mov w0, #8600
add w0, w0, w1
bl LOG
""", "WeaponAttackActionBase.PlayGroundMoveAttackIn -> 8600 + comboCount"),
    # Why the combo resets: CallbackAttackCollisionDestroy(type == LifeTime) sets _isAttackMiss and Target = null, and
    # the next UpdateAction takes the IsReset path. Log every collision's destroy type + how many hit infos it carried.
    (0x31E2928, "ldr x20, [x20, #0x10]", """
mov w1, #8800
add w0, w19, w1             ; CollisionDestroyType (0 None, 1 Hit, 2 LifeTime, 3 ForceRemove)
bl LOG
ldr w8, [x21, #0x18]        ; List<CollisionHitInfo>._size
mov w9, #9
cmp w8, w9
csel w8, w8, w9, lt
mov w1, #8810
add w0, w8, w1
bl LOG
""", "CollisionBase.OnDestroy -> 8800 + destroy type, 8810 + hit count (capped at 9)"),
]

PRO = """
stp x29, x30, [sp, #-0x50]!
stp x0, x1, [sp, #0x10]
stp x8, x9, [sp, #0x20]
str x10, [sp, #0x30]
str q16, [sp, #0x40]
"""
EPI = """
ldr q16, [sp, #0x40]
ldr x10, [sp, #0x30]
ldp x8, x9, [sp, #0x20]
ldp x0, x1, [sp, #0x10]
ldp x29, x30, [sp], #0x50
"""


def main():
    lib = open(LIB, "rb").read()
    entries = []
    region = 0
    addr = REGIONS[0][0]
    for hook_addr, displaced, body, desc in PROBES:
        orig = lib[hook_addr:hook_addr + 4]
        # the displaced text may re-establish flags first; its last instruction must be the original one
        assert asm(displaced.splitlines()[-1], hook_addr) == orig, (desc, orig.hex())
        text = PRO + body + "skip:\n" + EPI + displaced + "\nret\n"
        code = asm_block(text, addr)
        if addr + len(code) > REGIONS[region][1]:
            region += 1
            addr = REGIONS[region][0]
            code = asm_block(text, addr)
            assert addr + len(code) <= REGIONS[region][1], desc
        hook = asm(f"bl #{addr:#x}", hook_addr)
        entries.append(f'    {{"description": "DIAG cave: {desc}", "offset": {addr:#x}, '
                       f'"expected": bytes.fromhex("{lib[addr:addr + len(code)].hex()}"), '
                       f'"replacement": bytes.fromhex("{code.hex()}")}},')
        entries.append(f'    {{"description": "DIAG hook: {desc}", "offset": {hook_addr:#x}, '
                       f'"expected": bytes.fromhex("{orig.hex()}"), "replacement": bytes.fromhex("{hook.hex()}")}},')
        addr += len(code)
    print("\n".join(entries))


if __name__ == "__main__":
    main()
