"""DIAG probes for Jay's passive bomb (BatBombTrapAction, 2026-09-20): does the timer fire, does the explosion RPC
apply, and what do the collision / effect lookups return.

  9001        AcceptAction: the 2 s timer fired (OnManagedUpdate -> AcceptAction -> Trap.AcceptAction RPC)
  9002        OnApplyAction entered (the RPC came back)
  9003        OnApplyAction: TrapActionInfo.GetTrapAction == 0 (explosion action), about to check owner/ability
  9004        ApplyExplosion is being called (owner and _abilityParam non-null, or trap synchronized)
  9010/9011   CreateExplosionCollision: _abilityParam.GetCollisionInitInfo(CollisionMasterId) null / non-null
  9012/9013   CreateExplosionCollision: _abilityParam.GetDamageInitInfo() null / non-null
  9014/9015   CreateExplosionCollision: CollisionManager.AddCollision returned null / non-null (-> _damageCollision)
  9022        CreateExplosionEffect: owner IsMine, building the SyncEffect (CollisionEffectPath)
  9030/9031   OnManagedUpdate while _isAction: _damageCollision null (-> Destroy) / present
  9040/9041   SyncEffect.CreateEffect: EffectManager.InstantiateEffect(path) null / non-null (every sync effect)

Same minimal-cave scheme as attack_diag_caves.py; caves live in PlayerCharacter.UpdateIdleTypeRate past the
production bat-bomb cave (0x13CE540-0x13CE7C8).

    python scripts/re/bomb_diag_caves.py   # prints the DIAG_PATCHES_ARM64 entries
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from attack_diag_caves import asm_block, LIB, PRO, EPI  # noqa: E402
from mkcave import asm  # noqa: E402

REGIONS = [(0x13CE540, 0x13CE7C8)]

FLAG = """
cmp x0, #0
cset w0, ne
mov w1, #{base}
add w0, w0, w1
bl LOG
"""

PROBES = [
    (0x143BCB0, "orr w8, wzr, #1", "mov w0, #9001\nbl LOG\n", "BatBombTrapAction.AcceptAction -> 9001"),
    (0x143BF44, "mov x0, x19", "mov w0, #9002\nbl LOG\n", "BatBombTrapAction.OnApplyAction entered -> 9002"),
    (0x143BF80, "mov x0, x19", "mov w0, #9003\nbl LOG\n", "BatBombTrapAction.OnApplyAction: explosion action -> 9003"),
    (0x143BFF8, "mov x0, x19", "mov w0, #9004\nbl LOG\n", "BatBombTrapAction.OnApplyAction -> ApplyExplosion -> 9004"),
    (0x143C244, "ldr x21, [x19, #0x60]", FLAG.format(base=9010), "CreateExplosionCollision: GetCollisionInitInfo -> 9010 + non-null"),
    (0x143C274, "mov x22, x0", FLAG.format(base=9012), "CreateExplosionCollision: GetDamageInitInfo -> 9012 + non-null"),
    (0x143C394, "str x0, [x19, #0x70]", FLAG.format(base=9014), "CreateExplosionCollision: AddCollision -> 9014 + non-null"),
    (0x143C440, "mov x0, x20", "mov w0, #9022\nbl LOG\n", "CreateExplosionEffect: IsMine, SyncEffect being built -> 9022"),
    (0x143B750, "ldr x8, [x19, #0x70]", """
ldr x8, [x19, #0x70]
cmp x8, #0
cset w0, ne
mov w1, #9030
add w0, w0, w1
bl LOG
""", "OnManagedUpdate (_isAction): _damageCollision -> 9030 + non-null"),
    (0x160C268, "mov x20, x0", FLAG.format(base=9040), "SyncEffect.CreateEffect: InstantiateEffect -> 9040 + non-null"),
]


def main():
    lib = open(LIB, "rb").read()
    entries = []
    region, addr = 0, REGIONS[0][0]
    for hook_addr, displaced, body, desc in PROBES:
        orig = lib[hook_addr:hook_addr + 4]
        assert asm(displaced.splitlines()[-1], hook_addr) == orig, (desc, orig.hex())
        text = PRO + body + "skip:\n" + EPI + displaced + "\nret\n"
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
    print(f"# next free: {addr:#x}", file=sys.stderr)


if __name__ == "__main__":
    main()
