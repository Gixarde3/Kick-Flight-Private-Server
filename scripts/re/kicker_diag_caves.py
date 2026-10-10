"""DIAG probes for the Kite special-skill freeze (goal 2) and the bot condition/EnableMove break (goal 4).

Kite (kicker 4) SS "Art of Illusion" freeze
-------------------------------------------
`ThrowingStarSpecialSkillAction` is a 3-state action: `OnBeginAction` sets State=1 (0x161A2A4 `mov w1,#1` ->
0x161A2B0 `bl SpecialSkillActionBase.set_State`, field `State` at +0x28); `UpdateAction` does nothing unless State==2
(0x161A36C `bl get_State`, 0x161A370 `cmp w0,#2`, 0x161A374 `b.ne` -> returns null); the ONLY writer of State=2 is
`ThrowingStarSpecialSkillAction.OnEndCutScene` (0x161A944 `mov w1,#2` -> tail `b set_State`), and that method returns
early at 0x161A92C-0x161A93C when `BattleUtil.GetMyTeamType() == 2`. `PlayerStateSpecialSkill.UpdateAction` (0x14C6AF0)
just tail-calls the action's UpdateAction, and `PlayerStateSpecialSkill.LateUpdate` (0x14C7258) is `ret`, so the
character stays in state 13 (SpecialSkill) forever when State never reaches 2.
The action's cut-end callback is only reached when the cut-scene plays: `PlayerStateSpecialSkill.ExecuteAction`
(0x14C6B24) branches on `IsShowSpecialSkillCut` (0x14C6B8C; = IsMainPlayer && !GameManager.JustWatching) to the no-cut
path at 0x14C6E88, and the cut branch itself is skipped when `_specialSkillCut` (`this+0x18`) is null (0x14C6BC4
`op_Inequality`, 0x14C6BC8 `tbz -> 0x14C6E88`). For the local main player the cut is created (IsMyPlayer / UserId match
in `InitializeDestroyedObject`); bots/non-local characters get `SetCut(null)` and always take the no-cut path. The cut
timeline then drives `SpecialSkillCut.Play` (0x1505E70) -> `OnCalledSpecialSkillEvent` (0x15060E4, event type in w1:
0 = EndCutScene -> `End` -> the `_endAction` delegate) -> `PlayerStateSpecialSkill.OnEndCutScene` (0x14C7488) -> the
action's vtable slot 11 (0x161A8D0) -> State=2. A cut whose timeline never delivers event 0 strands the local player
even though the cut branch was taken.

Values (goal 2):
  9500/9501  ExecuteAction @0x14C6B88: IsShowSpecialSkillCut (0 = cut skipped, 1 = cut shown)
  9510/9511  same site: `_specialSkillCut` == null (1 = null -> cut branch skipped)
  9520       SpecialSkillCut.Play entry: the cut actually started
  9530+n     SpecialSkillCut.OnCalledSpecialSkillEvent entry, w1 = event type (0 = EndCutScene -> End/callback)
  9540+n     PlayerStateSpecialSkill.OnEndCutScene entry (n = isDestroy): the cut-end delegate fired
  9550       ThrowingStarSpecialSkillAction.OnEndCutScene entry: the action's own cut-end ran
  9560+n     action OnEndCutScene @0x161A92C: BattleUtil.GetMyTeamType() = n (2 -> early return, no State=2)
  9570       action OnEndCutScene reached the State=2 store. Emitted by the SAME @0x161A92C probe when n != 2:
             a separate `bl` hook at 0x161A944 would sit after the 0x161A940 `ldp x29, x30` epilogue, clobber
             the caller's restored LR and make the `b set_State` tail call return into the epilogue a second time.
  9580+n     action UpdateAction @0x161A370: State = n, logged only when n != 2 (strand repeats every frame)

Bot condition/EnableMove break (goal 4)
---------------------------------------
`PlayerCharacter.ManagedUpdate` (0x13CB428) calls `UpdateConditionActionAll` (0x13CB4C4, unconditional; it clears
EnableMove and re-runs `CheckEnableMove`) and only calls `ConditionActionController.UpdateConditionAction` (0x17BF7AC,
which removes expired conditions and calls UpdateEnableFly/MovePosition) on the non-synchronized branch: 0x13CB528
`bl get_IsSynchronized`, 0x13CB52C `tbz w0,#0,->0x13CB59C`, 0x13CB5BC `bl UpdateConditionAction`. So conditions that
land on a player this client does not own never expire locally and `EnableMove` (0x17BCD18, `this+0x21`, cleared for
Stun/Paralysis/Restrainted/Prison by `CheckEnableMove` 0x17BEDE4) stays false; `PlayerStateNormal.UpdateAction`
(0x17E13FC `bl get_EnableMove`, 0x17E1400 `tbnz`) then only decelerates, and `InputActionFly` (0x17E1FE4) falls into
the human input path. Gravity (condition 21) only clears EnableFly (0x17C08B8) while it is active and self-expires, so
it is at most a secondary contributor.

Values (goal 4):
  9600/9601  UpdateEnableFly @0x17C08B4: computed EnableFly (0 = false, 1 = true)
  9610+n     same site: number of live conditions seen by the loop
  9620       UpdateEnableFly @0x17C0884: a type-21 Gravity condition is in the list
  9630       GravityConditionAction.CalcMoveVector entry: gravity is actively moving a character
  9640/9641  PlayerStateNormal.UpdateAction @0x17E13F8: EnableMove (0 = movement/AI input blocked)
  9650       ConditionActionController.UpdateConditionAction entry: conditions are being pruned (absent for a
             non-owned broken bot -> the ownership asymmetry above)

All caves live in the verified dead body of `GameManager.InitializeReconnect` (0x1570164-0x1570560): production
stubs its entry to `ret` (patch at 0x1570164) and a branch sweep over the whole .so finds only the call to the entry
itself (0x156FBAC -> 0x1570164), nothing into 0x1570168+. The body was empty in both the production and DIAG patch
tables before this block.

    python scripts/re/kicker_diag_caves.py   # prints the DIAG_PATCHES_ARM64 entries
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from mkcave import LOG  # noqa: E402
from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN  # noqa: E402

_ks = Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN)


def asm_block(text: str, base: int) -> bytes:
    """Whole-block assembly (labels allowed), unlike mkcave.asm which goes line by line."""
    lines = [ln.split(";")[0].strip() for ln in text.splitlines()]
    src = "\n".join(ln for ln in lines if ln).replace("LOG", hex(LOG))
    enc, count = _ks.asm(src, base)
    if enc is None:
        raise SystemExit("asm failed: " + src)
    return bytes(enc)


def single(text: str, base: int) -> bytes:
    enc, _ = _ks.asm(text, base)
    if enc is None:
        raise SystemExit("asm failed: " + text)
    return bytes(enc)


def position_independent(word: int) -> bool:
    """True when replaying this instruction's raw bytes at the cave address has the same effect as at the hook
    address. Hooks must never sit on a PC-relative instruction (AGENTS.md): a replayed branch would retarget into
    the cave/host instead of the original code. The generator refuses to place a probe on one."""
    top = word >> 24
    if (word >> 26) in (0b000101, 0b100101):                        # b / bl
        return False
    if top == 0x54 or top in (0x34, 0x35) or top in (0x36, 0x37):   # b.cond / cbz,cbnz / tbz,tbnz
        return False
    if (word & 0x1F000000) == 0x10000000:                           # adr / adrp
        return False
    if (word & 0x3B000000) == 0x18000000:                           # ldr/ldrsw/prfm (literal)
        return False
    return True


LIB = os.path.join(os.path.dirname(__file__), "..", "..", ".local", "re", "lib", "arm64-v8a", "libil2cpp.so")
# The whole InitializeReconnect body is free (entry stubbed to ret, no incoming branch past the entry).
REGIONS = [(0x1570168, 0x1570560)]

# (hook addr, kind, body, description). kind "mid" hooks with `bl` + `ret`; kind "entry" hooks with `b` and jumps
# back to hook+4 after replaying the displaced prologue instruction (appended as the raw original bytes). The
# PRO/EPI below saves x0/x1/x8/x9/x10, so the hooks preserve every argument/register the original code still needs
# after the cave.
PROBES = [
    # ---- Kite special skill (goal 2) ----
    (0x14C6B88, "mid", """
mov x0, x20
bl #0x14c703c               ; PlayerStateSpecialSkill.IsShowSpecialSkillCut
mov w1, #9500
add w0, w0, w1
bl LOG
ldr x8, [x20, #0x18]        ; _specialSkillCut
cmp x8, #0
cset w0, eq
mov w1, #9510
add w0, w0, w1
bl LOG
""", "PSSS.ExecuteAction: IsShowSpecialSkillCut (9500/9501) + _specialSkillCut==null (9510/9511)"),
    (0x1505E70, "entry", """
mov w0, #9520
bl LOG
""", "SpecialSkillCut.Play entry -> 9520 (the cut timeline actually started)"),
    (0x15060E4, "entry", """
mov w0, w1
mov w1, #9530
add w0, w0, w1
bl LOG
""", "SpecialSkillCut.OnCalledSpecialSkillEvent entry -> 9530 + event type (0 = EndCutScene)"),
    (0x14C7488, "entry", """
mov w0, w1
mov w1, #9540
add w0, w0, w1
bl LOG
""", "PSSS.OnEndCutScene entry -> 9540 + isDestroy (cut-end delegate fired)"),
    (0x161A8D0, "entry", """
mov w0, #9550
bl LOG
""", "ThrowingStarSpecialSkillAction.OnEndCutScene entry -> 9550"),
    (0x161A92C, "mid", """
mov w1, #9560
add w0, w0, w1
bl LOG
mov w1, #9560
sub w0, w0, w1
cmp w0, #2
b.eq skip9570
mov w0, #9570
bl LOG
skip9570:
""", "action OnEndCutScene: BattleUtil.GetMyTeamType -> 9560+n; n!=2 also logs 9570 (State=2 store reached)"),
    (0x161A370, "mid", """
cmp w0, #2
b.eq skip
mov w1, #9580
add w0, w0, w1
bl LOG
skip:
""", "action UpdateAction: State != 2 -> 9580+State (strand), silent while healthy"),
    # ---- bot condition/EnableMove (goal 4) ----
    (0x17C08B4, "mid", """
mov w0, w24
mov w1, #9600
add w0, w0, w1
bl LOG
mov w0, w20
mov w1, #9610
add w0, w0, w1
bl LOG
""", "ConditionActionController.UpdateEnableFly: EnableFly (9600/9601) + condition count (9610+n)"),
    (0x17C0884, "mid", """
cmp w0, #0x15
b.ne skip
mov w0, #9620
bl LOG
skip:
""", "UpdateEnableFly loop: a Gravity (type 21) condition is present -> 9620"),
    (0x1689288, "entry", """
mov w0, #9630
bl LOG
""", "GravityConditionAction.CalcMoveVector entry -> 9630 (gravity is moving a character)"),
    (0x17E13F8, "mid", """
mov x0, x20
bl #0x17bcd18               ; ConditionActionController.get_EnableMove
mov w1, #9640
add w0, w0, w1
bl LOG
""", "PlayerStateNormal.UpdateAction: EnableMove -> 9640/9641 (0 = movement/AI input blocked)"),
    (0x17BF7AC, "entry", """
mov w0, #9650
bl LOG
""", "ConditionActionController.UpdateConditionAction entry -> 9650 (conditions are being pruned)"),
]

# Minimal save: the region-E LOG helper at 0x13BC348 preserves x0-x18 and q0-q7/q16-q31; only NZCV is lost and the
# original compare is the replayed displaced instruction at the end, so every probe is safe on an fcmp/cmp.
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
    for hook_addr, kind, body, desc in PROBES:
        orig = lib[hook_addr:hook_addr + 4]
        assert len(orig) == 4, desc
        assert position_independent(int.from_bytes(orig, "little")), \
            f"{desc}: hook sits on a PC-relative instruction"
        tail = f"b #{hook_addr + 4:#x}" if kind == "entry" else "ret"
        head = asm_block(PRO + body + EPI, addr)
        code = head + orig + single(tail, addr + len(head) + 4)
        if addr + len(code) > REGIONS[region][1]:
            region += 1
            addr = REGIONS[region][0]
            head = asm_block(PRO + body + EPI, addr)
            code = head + orig + single(tail, addr + len(head) + 4)
            assert addr + len(code) <= REGIONS[region][1], desc
        hook = single(f"b #{addr:#x}" if kind == "entry" else f"bl #{addr:#x}", hook_addr)
        entries.append(f'    {{"description": "DIAG cave: {desc}", "offset": {addr:#x}, '
                       f'"expected": bytes.fromhex("{lib[addr:addr + len(code)].hex()}"), '
                       f'"replacement": bytes.fromhex("{code.hex()}")}},')
        entries.append(f'    {{"description": "DIAG hook: {desc}", "offset": {hook_addr:#x}, '
                       f'"expected": bytes.fromhex("{orig.hex()}"), "replacement": bytes.fromhex("{hook.hex()}")}},')
        addr += len(code)
    print("\n".join(entries))


if __name__ == "__main__":
    main()
