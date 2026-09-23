"""DIAG probes for the Hitagi (JapaneseSword) kicker-skill warp and PlayerCharacter.SetVisible (2026-09-20).

Why: with no target the KS leaves Hitagi where she is. WarpSkillAction.UpdateFinish only calls UpdateTransform
(the actual move to _targetPos) while player.IsWarp && !player.IsVisible, and the user's logcat had a
NullReferenceException in PlayerCharacter.SetVisible inside WarpOutAsync - so the hide never completes and the
warp never moves. These caves print which pointer SetVisible trips on and how far the no-target end position is.

KFDIAG values:
  7800+visible   SetVisible entered (0 = hide, 1 = show); then 7810+(modelCtr!=null), 7820+(EffectCtr!=null),
                 7830+(Weapons!=null)
  7700+ok        JapaneseSwordSkillAction.OnBeginFinish: PushBackCollider null (7700) / ok (7701)
  7710, x, 7711, z   _noTargetEndPosition after MoveSphereCollision (world x / z as ints)
  7720           WarpSkillAction.UpdateFinish: IsWarp true, checking IsVisible
  7721           ... IsVisible false -> UpdateTransform runs (the move happens)
  7712, x, z     player position at OnBeginFinish (compare with 7710/7711)
  7730, x, z     position passed to SetPosition each UpdateTransform frame

    python scripts/re/warp_diag_caves.py   # prints the DIAG_PATCHES_ARM64 entries
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from mkcave import asm, cave, hook  # noqa: E402

LIB = os.path.join(os.path.dirname(__file__), "..", "..", ".local", "re", "lib", "arm64-v8a", "libil2cpp.so")

PROBES = [
    # (cave addr, hook addr, displaced instruction, body, description)
    (0x159D420, 0x13C5C44, "mov x20, x0", """
mov x20, x0
and w0, w1, #1
mov w1, #7800
add w0, w0, w1
bl LOG
ldr x8, [x20, #0x168]
cmp x8, #0
cset w0, ne
mov w1, #7810
add w0, w0, w1
bl LOG
ldr x8, [x20, #0x170]
cmp x8, #0
cset w0, ne
mov w1, #7820
add w0, w0, w1
bl LOG
ldr x8, [x20, #0x150]
cmp x8, #0
cset w0, ne
mov w1, #7830
add w0, w0, w1
bl LOG
""", "PlayerCharacter.SetVisible entry -> 7800+visible, 7810/7820/7830 + non-null(_modelCtr/EffectCtr/Weapons)"),
    (0x159D560, 0x15201EC, "mov x20, x0", """
cmp x0, #0
cset w0, ne
mov w1, #7700
add w0, w0, w1
bl LOG
""", "JapaneseSwordSkillAction.OnBeginFinish -> 7700 + (PushBackCollider != null)"),
    (0x159D640, 0x15202A4, "str s0, [x19, #0x18c]", """
mov w0, #7710
bl LOG
fcvtzs w0, s0
bl LOG
mov w0, #7711
bl LOG
fcvtzs w0, s2
bl LOG
mov x0, x19                 ; this (x21 is reused for the SkillParameter by 0x1520244 - using it crashed the first build)
mov x1, xzr
bl #0x141fdf8               ; SkillActionBase.get_Player
mov x1, xzr
bl #0x1a7ca3c               ; MonoBehaviourBase.get_t
mov x1, xzr
bl #0x2789584               ; Transform.get_position
mov v8.16b, v0.16b
mov v9.16b, v2.16b
mov w0, #7712
bl LOG
fcvtzs w0, s8
bl LOG
fcvtzs w0, s9
bl LOG
""", "JapaneseSwordSkillAction.OnBeginFinish -> 7710, end.x, 7711, end.z (_noTargetEndPosition), 7712, pos.x, pos.z"),
    (0x159D7A0, 0x1817174, "mov x0, x20", """
mov w0, #7720
bl LOG
""", "WarpSkillAction.UpdateFinish -> 7720 (IsWarp, checking IsVisible)"),
    (0x159D880, 0x1817184, "mov x0, x19", """
mov w0, #7721
bl LOG
""", "WarpSkillAction.UpdateFinish -> 7721 (invisible: UpdateTransform runs)"),
    (0x159D960, 0x1817534, "mov x2, xzr", """
mov v8.16b, v0.16b
mov v9.16b, v2.16b
mov w0, #7730
bl LOG
fcvtzs w0, s8
bl LOG
fcvtzs w0, s9
bl LOG
""", "WarpSkillAction.UpdateTransform -> 7730, lerp.x, lerp.z (position handed to PlayerCharacter.SetPosition)"),
]


def main():
    lib = open(LIB, "rb").read()
    entries = []
    prev_end = 0
    for cave_addr, hook_addr, displaced, body, desc in PROBES:
        c = cave(cave_addr, body, displaced)
        assert cave_addr >= prev_end, hex(cave_addr)
        prev_end = cave_addr + len(c)
        assert prev_end <= 0x159DAB0, hex(prev_end)
        h = hook(hook_addr, cave_addr)
        assert lib[hook_addr:hook_addr + 4] == asm(displaced, hook_addr), desc
        entries.append(f'    {{"description": "DIAG cave: {desc}", "offset": {cave_addr:#x}, '
                       f'"expected": bytes.fromhex("{lib[cave_addr:cave_addr + len(c)].hex()}"), '
                       f'"replacement": bytes.fromhex("{c.hex()}")}},')
        entries.append(f'    {{"description": "DIAG hook: {desc}", "offset": {hook_addr:#x}, '
                       f'"expected": bytes.fromhex("{lib[hook_addr:hook_addr + 4].hex()}"), '
                       f'"replacement": bytes.fromhex("{h.hex()}")}},')
    print("\n".join(entries))


if __name__ == "__main__":
    main()
