# Gym mode — a match with 3 mannequin kickers and a harmless guardian (2026-09-20)

Goal: a consistent test arena (skills, combos, traps) without AI noise. Retail has no free-practice mode: the
in-game tutorial (`InGameTutorialManager`, `BattleRuleType.Trial`) is a scripted state machine, and "Training" is
just mission counters in real matches. What retail *does* have is `AIOption.Mannequin` (63 = NoMove | NoAttack |
NoHeal | NoDash | NoSkill | NoAvoid), the option the tutorial gives its dummies via
`InGameTutorialManager.SetAllEnemyAiOption`; `PlayerCharacter.AIEnableMove / AIEnableAttack / AIEnableHeal /
PerformMove / TryAvoid / JudgeUseAISkill` all read `PlayerCharacter.AIOption` (+0xE4). Nothing sets it in a
normal match, so the gym is: server picks the roster, client patch flips the option for the gym bots.

## How to use

```
http://192.168.68.55:18080/gym/on     # or kickflightsg.ddns.net:18080/gym/on from the phone browser
http://192.168.68.55:18080/gym/off
http://192.168.68.55:18080/gym        # status
```
Toggle before pressing Combate; it applies to the next match the server assembles. Gym match = you (Blue) vs three
bots on Red (`Owlbert / Buzzy Big / Yuyan` unless you are one of them) standing at their spawn, plus a guardian that
fires but deals 0 damage. Normal 4v4 comes back with `/gym/off`. No restart needed.

## Implementation

Server (`src/KickFlight.BootstrapApi`):
* `BattleMatchmakingService.GymEnabled` (static, `/gym/on|off|` routes in `Program.cs`), `GymBotCount = 3`,
  `GymAiParameterBase = 100`. `BuildRoster`: in gym mode the fill loop adds exactly 3 bots, all `teamType 1`, with
  `kickerAiParameterId = 100 + kickerId` and the name suffixed ` (gym)`.
* `DemoSessionApi.AppendGymAiRows`: `KickerAiParameter` is served with a second copy of every row at id 100 + id
  (`PlayerCharacter.GetKickerAIParameterMaster` is `get_Item(_kickerAiParameterId)` by row id) with the three
  motivations 0, `canLockon false`, every dash/skill interval 9999 — so an *unpatched* client's gym bots are at
  least passive.
* `/battle/start` returns `guardianParameter.id = 3` in gym mode; `config/masters_guardian_parameter.json` row 3 =
  `{hp 8000, attack 0}`.

Client (`scripts/patch-il2cpp-endpoints.py`, cave source `scripts/re/bot_special_skill_cave.py`):
* First thing in the `PlayerCharacter.UpdateAi` cave, after the `_enableAi` check:
  `ldr w8,[x0,#0xc4]` (`_kickerAiParameterId`) `; cmp w8,#100; b.lt not_gym; mov w8,#63; str w8,[x0,#0xe4]; b resume`
  — every frame, so nothing can clear it; the bot never casts its special either (the cave's SS logic is skipped).
  Cave grew 436 → 460 bytes (still inside the dead `HomeSummonModelController.SetModel` body, DIAG caves at
  0x159D420 untouched). Both APKs rebuilt.

## Acceptance

- [ ] Trial button (Discs page): needs `Field` master row 801 (added 2026-09-20 in `DemoSessionApi.cs`; without it
      `FieldManager.FieldInfo` stays null and the load hangs).
- [ ] `/gym/on` then Combate: roster has you + 3 `(gym)` bots on the other team, no allies; match loads.
- [ ] Bots stay where they spawn (no take-off, no attack, no disc/KS/SS) for the whole match; they still take damage
      and respawn.
- [ ] Guardian laser deals 0 damage.
- [ ] `/gym/off` restores the 4v4.
- [ ] With the old APK (no cave change) gym bots are still passive (zero motivation rows); with the new one they are
      fully inert.
