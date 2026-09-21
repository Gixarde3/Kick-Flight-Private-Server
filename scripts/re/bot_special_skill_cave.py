"""Source of the "AI casts the special skill" cave in scripts/patch-il2cpp-endpoints.py (arm64).

Hook: `b CAVE` at PlayerCharacter.UpdateAi (0x13BEAEC), which PlayerCharacter.ManagedUpdate tail-calls every
frame for every player; the cave only acts when `_enableAi` (this+0xE0) is set. Two branches:

  state == SpecialSkill (13): the special is running. Many specials stop in SpecialSkillState.AttackStaging (2)
      and wait for the human's execute button, so the bot "presses" it: GetStateRoutine(13) 0x13C0928, and when
      its _skillAction (routine+0x20) exists and get_State() 0x14C5D9C == 2, OnPressExecuteButton 0x14C78FC then
      OnReleaseExecuteButton 0x14C7938 (CreateAttackArea/RemoveAttackArea + the action's press/release slots).
      Without this every bot froze in its first special (2026-09-19, match at 12–19 with 0 kills).
  gym mannequin (_kickerAiParameterId >= 100, server gym mode): AIOption := Mannequin (63) and fall through.
  state == Normal (0): mirror SpecialSkillPresenter.OnClick / SpecialSkillModel.UpdateState:
      Param.SP >= Param.GetMaxSP()          get_Param 0x13BE270, get_SP 0x1754930, GetMaxSP 0x1754ACC
      ConditionActionCtr.EnableSpecialSkill get_ConditionActionCtr 0x16B697C, get_EnableSpecialSkill 0x17BCD54
      then SetState(13, null) 0x13C4A5C + ApplyForcedAction(info) 0x13C4DF0.
Both fall through to the displaced prologue instruction `stp x20, x19, [sp, #-0x20]!` and resume at entry+4.
Cave lives at 0x159D200 in the dead body of the entry-stubbed HomeSummonModelController.SetModel
(0x159D1BC-0x159DAB0, nothing else branches into it).

    python scripts/re/bot_special_skill_cave.py   # prints the replacement/expected hex for the patch table
"""
import os

from keystone import KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN, Ks

CAVE = 0x159D200
HOOK = 0x13BEAEC
RESUME = HOOK + 4
LIB = os.path.join(os.path.dirname(__file__), "..", "..", ".local", "re", "lib", "arm64-v8a", "libil2cpp.so")

SRC = f"""
ldrb w8, [x0, #0xe0]        // _enableAi
cbz w8, resume
ldr w8, [x0, #0xc4]         // _kickerAiParameterId: the server sends 100 + kickerId for gym mannequins
cmn w8, #1                  // (BattleMatchmakingService.GymAiParameterBase); normal server bots are 1..14. -1 is the
b.eq gym                    // PlayerBattleInfo default = the AI kickers of the offline Trial battle (disc "test" button,
cmp w8, #100                // BattleUtil.CreateTrialAiPlayerBattleInfo never sets it) -> mannequins too
b.lt not_gym
gym:
mov w8, #63                 // AIOption.Mannequin = NoMove|NoAttack|NoHeal|NoDash|NoSkill|NoAvoid, read by
str w8, [x0, #0xe4]         // AIEnableMove/AIEnableAttack/PerformMove/TryAvoid/JudgeUseAISkill every frame
b resume                    // no special-skill casting either: plain UpdateAi with the engine muzzled
not_gym:
stp x29, x30, [sp, #-0x30]!
stp x19, x20, [sp, #0x10]
str x21, [sp, #0x20]
mov x19, x0                 // this (PlayerCharacter)
mov x1, xzr
bl #0x13CAB6C               // GetCurrentState()
cmp w0, #13
b.eq in_skill
mov w1, #13
mov x2, xzr
mov x0, x19
bl #0x13C0928               // GetStateRoutine(SpecialSkill)
cbz x0, chk_normal
strh wzr, [x0, #0x3c]       // progress flags + cut frame counter (padding after HitCount) := not started
chk_normal:
mov x0, x19
mov x1, xzr
bl #0x13CAB6C               // GetCurrentState() again (x0 was clobbered)
cbnz w0, done               // only cast from Normal
mov x0, x19
mov x1, xzr
bl #0x13BE270               // get_Param
cbz x0, done
mov x21, x0
mov x1, xzr
bl #0x1754930               // get_SP -> s0
str s0, [sp, #0x28]
mov x0, x21
mov x1, xzr
bl #0x1754ACC               // GetMaxSP -> w0
scvtf s1, w0
ldr s0, [sp, #0x28]
fcmp s0, s1
b.lt done                   // gauge not full
mov x0, x19
mov x1, xzr
bl #0x16B697C               // get_ConditionActionCtr
cbz x0, done
mov x1, xzr
bl #0x17BCD54               // get_EnableSpecialSkill
tbz w0, #0, done
mov x0, x19
mov w1, #13                 // PlayerStateType.SpecialSkill
mov x2, xzr
mov x3, xzr
bl #0x13C4A5C               // SetState(type, arg)
cbz x0, done
mov x1, x0
mov x0, x19
mov x2, xzr
bl #0x13C4DF0               // ApplyForcedAction(info)
b done
in_skill:
mov x0, x19
mov w1, #13
mov x2, xzr
bl #0x13C0928               // GetStateRoutine(SpecialSkill)
cbz x0, done
mov x21, x0                 // PlayerStateSpecialSkill
ldr x20, [x21, #0x20]       // _skillAction (SpecialSkillActionBase)
cbz x20, done
mov x0, x20
mov x1, xzr
bl #0x15030BC               // action.get_State()
str w0, [sp, #0x28]         // keep the state across the calls below
ldrb w8, [x21, #0x3c]       // progress flags: bit0 cut ended (effect fired first), bit2 execute pressed
cmp w0, #1                  // SpecialSkillState.CutStaging
b.ne chk_attack
tbnz w8, #0, skip_engine    // cut already ended by us
ldrb w9, [x21, #0x3d]       // frames spent in the cut pose (padding byte after the flags)
add w9, w9, #1
strb w9, [x21, #0x3d]
cmp w9, #120         // hold the pose like the retail cut-in, then fire
b.lo skip_engine
orr w8, w8, #1
strb w8, [x21, #0x3c]
ldr x8, [x20]               // vtable
add x8, x8, #0x248          // slot 18 = 0x128 + 18*16 (0x250 is that slot's MethodInfo, which SetEvents loads for its delegate)
mov x0, x20
ldp x3, x1, [x8]            // SpecialSkillActionBase.ExecuteSkillEffect - retail fires it from the cut-in scene's
blr x3                      // timeline (SetEvents -> AddSpecialSkillEvent) right before the cut ends; bots never play a cut
ldr x8, [x20]
mov x0, x20
mov w1, wzr                 // isDestroy = false
ldp x3, x2, [x8, #0x1d8]    // slot 11: OnEndCutScene - must run in the same frame, right after the effect: several
blr x3                      // actions leave the SpecialSkill state in this same frame from here
b skip_engine
chk_attack:
ldr w0, [sp, #0x28]
cmp w0, #2                  // SpecialSkillState.AttackStaging
b.ne skip_engine
tbnz w8, #2, skip_engine    // already pressed
orr w8, w8, #4
strb w8, [x21, #0x3c]
mov x0, x21
mov x1, xzr
bl #0x14C78FC               // OnPressExecuteButton()
mov x0, x21
mov x1, xzr
bl #0x14C7938               // OnReleaseExecuteButton()
skip_engine:
// while the special runs, do not run AIPlayerEngine.ManagedUpdate at all: the engine kept flying/boosting the bot
// through its special (banner showed the boost pose, no pause, animation-event effects never fired)
ldr x21, [sp, #0x20]
ldp x19, x20, [sp, #0x10]
ldp x29, x30, [sp], #0x30
ret                         // UpdateAi is tail-called from ManagedUpdate, so this returns to its caller
done:
mov x0, x19
ldr x21, [sp, #0x20]
ldp x19, x20, [sp, #0x10]
ldp x29, x30, [sp], #0x30
resume:
stp x20, x19, [sp, #-0x20]! // displaced prologue instruction
b #{RESUME}
"""


def main():
    ks = Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN)
    cave = bytes(ks.asm(SRC, CAVE)[0])
    hook = bytes(ks.asm(f"b #{CAVE}", HOOK)[0])
    print(f"cave @ {CAVE:#x} ({len(cave)} bytes): {cave.hex()}")
    print(f"hook @ {HOOK:#x}: {hook.hex()}")
    if os.path.exists(LIB):
        lib = open(LIB, "rb").read()
        print("expected cave:", lib[CAVE:CAVE + len(cave)].hex())
        print("expected hook:", lib[HOOK:HOOK + 4].hex())


if __name__ == "__main__":
    main()
