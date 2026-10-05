"""Source of the production GameManager.GetMenuType cave in scripts/patch-il2cpp-endpoints.py (arm64).

GameManager.GetMenuType (0x1570EA8) entry is `b 0x13CE4B0; nop`. Pristine GetMenuType returns, in order:
Tutorial 2, ReplayMode 1, HomeInfo.IsTrainingMode 3, BattleRuleInfo.IsTrial 4, HomeInfo.BattleModeType == 1
(custom battle) -> spectator ? 6 : 5, else 0. Its body cannot be re-entered: production caves live in it
(PlayerAnimator.SetParamVelocity guard at 0x1570FF0) and so do DIAG caves, so the cave re-implements the part we want:
  BattleUtil.GetMyTeamType (0x15B8F24) == 2 (Photon spectator)  -> 6 (MenuType spectator, unchanged)
  ColorfulManager.Archive.BattleRuleInfo.IsTrial                -> 4 (MenuType.Trial: TrialSettingWindow with the
                                                                     End button and the infinite-cooldown toggle)
  otherwise                                                     -> 0 (normal battles, custom battles included, as before)
get_Archive (0x31DC818) does its own method/class init; ArchiveData.get_BattleRuleInfo is `ldr x0, [x0, #0x230]` and
BattleRuleInfo.get_IsTrial is `[x0, #0x18] == 100`, both inlined. Cave space 0x13CE4B0-0x13CE500 (dead
UpdateIdleTypeRate body; the bat-bomb TrapInfo cave starts at 0x13CE500).

    python scripts/re/menu_type_cave.py
"""
import os

from keystone import KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN, Ks

CAVE = 0x13CE4B0
CAVE_END = 0x13CE500
LIB = os.environ.get("KF_CLEAN_LIBIL2CPP") or os.path.join(
    os.path.dirname(__file__), "..", "..", ".local", "re", "lib", "arm64-v8a", "libil2cpp.so")

SRC = """
stp x29, x30, [sp, #-0x10]!
mov x29, sp
bl #0x15b8f24
cmp w0, #2
b.eq spectator
mov x0, xzr
bl #0x31dc818
cbz x0, normal
ldr x0, [x0, #0x230]
cbz x0, normal
ldr w8, [x0, #0x18]
cmp w8, #100
b.ne normal
mov w0, #4
b out
spectator:
mov w0, #6
b out
normal:
mov w0, wzr
out:
ldp x29, x30, [sp], #0x10
ret
"""


def main() -> None:
    code = bytes(Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN).asm(SRC, CAVE)[0])
    assert CAVE + len(code) <= CAVE_END, hex(CAVE + len(code))
    so = open(LIB, "rb").read()
    print("cave @", hex(CAVE), "expected", so[CAVE:CAVE + len(code)].hex(), "replacement", code.hex())


if __name__ == "__main__":
    main()
