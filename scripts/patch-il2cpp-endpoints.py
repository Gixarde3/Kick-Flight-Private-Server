"""Patch Kick-Flight IL2CPP endpoint literals for a direct private server.

This script is intentionally specific to the preserved 2.11.0 APK. It validates
the metadata layout and native instruction bytes before changing anything.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from urllib.parse import urlsplit


SANITY = 0xFAB11BAF
METADATA_VERSION = 24
ORIGINAL_LITERALS = {
    "https://colorful-api-octo-sb.grenge.jp": "base_url",
    "https://kickflight-resource-api.grenge.jp": "base_url",
    "kickflight-api.grenge.jp/": "authority",
    "ns.exitgames.com": "photon_host",
}
LITERAL_INDEXES = {
    "https://colorful-api-octo-sb.grenge.jp": 2294,
    "https://kickflight-resource-api.grenge.jp": 2304,
    "kickflight-api.grenge.jp/": 9244,
    "ns.exitgames.com": 2039,
}
NATIVE_PATCHES: dict[str, list[dict[str, object]]] = {
    "arm64-v8a": [
        {
            "description": "force HTTP for direct server access",
            "offset": 0x31B5024,
            "expected": bytes.fromhex("e8030aaa"),  # ponytail: base.apk already ships mov x8,x10; alreadyPatched path skips
            "replacement": bytes.fromhex("e8030aaa"),  # mov x8, x10 (always HTTP)
        },
        {
            "description": "bypass dead Firebase chat setup in HomeChatNotificationView.OnCompleteChatSetup",
            "offset": 0x17331C0,
            "expected": bytes.fromhex("f50f1df8"),  # str x21, [sp, #-0x30]!
            "replacement": bytes.fromhex("c0035fd6"),  # ret
        },
        {
            "description": "bypass null format string crash in BattleRuleDefaultView.SetView",
            "offset": 0x1890c50,
            "expected": bytes.fromhex("a0050036"),  # tbz w0, #0, #0x1890d04
            "replacement": bytes.fromhex("2d000014"),  # b #0x1890d04
        },
        {
            "description": "bypass null exception in HomeSummonModelController.UnloadModel on window close",
            "offset": 0x159DF5C,
            "expected": bytes.fromhex("f50f1df8"),  # str x21, [sp, #-0x30]!
            "replacement": bytes.fromhex("c0035fd6"),  # ret
        },
        {
            "description": "bypass null exception in HomeSummonModelController.<LoadModelAsync>d__25.MoveNext",
            "offset": 0x159E254,
            "expected": bytes.fromhex("f50f1df8f44f01a9"),  # str x21, [sp, #-0x30]!; stp x20, x19, [sp, #0x10]
            "replacement": bytes.fromhex("e0031f2ac0035fd6"),  # mov w0, wzr; ret
        },
        {
            "description": "bypass null _flagBone exception in JapaneseSwordAction.IsCloded",
            "offset": 0x151DAE8,
            "expected": bytes.fromhex("f30f1ef8fd7b01a9fd430091130c40f9730000b5e0031faabbd9f397"),
            "replacement": bytes.fromhex("080c40f9680000b5e0031f2ac0035fd6f30f1ef8fd7b01a9f30308aa"),
        },
        {
            "description": "bypass null _flagBone exception in JapaneseSwordAction.IsInHandScabbard",
            "offset": 0x151DB2C,
            "expected": bytes.fromhex("f30f1ef8fd7b01a9fd430091130c40f9730000b5e0031faaaad9f397"),
            "replacement": bytes.fromhex("080c40f9680000b5e0031f2ac0035fd6f30f1ef8fd7b01a9f30308aa"),
        },
        {
            "description": "bypass null _sword exception in JapaneseSwordAction.InitializeSword",
            "offset": 0x151D820,
            "expected": bytes.fromhex("e0031faa72daf397"),  # mov x0, xzr; bl #0x12141ec
            "replacement": bytes.fromhex("070000141f2003d5"),  # b #0x151d83c; nop
        },
        {
            "description": "force CriAtomSource.Play to always configure loop before starting playback",
            "offset": 0x2724398,
            "expected": bytes.fromhex("60010035"),  # cbnz w0, #0x27243c4
            "replacement": bytes.fromhex("1f2003d5"),  # nop
        },
        {
            "description": "bypass null exception in HomeSummonModelController.SetModel",
            "offset": 0x159D1BC,
            "expected": bytes.fromhex("ea0f18fc"),  # str d10, [sp, #-0x80]!
            "replacement": bytes.fromhex("c0035fd6"),  # ret
        },
        {
            "description": "safely bypass weapon attachment when instantiated model is null in Weapon.Initialize",
            "offset": 0x1818FD8,
            "expected": bytes.fromhex("560000b584ece797"),  # cbnz x22, #0x1818fe0; bl #0x12141ec
            "replacement": bytes.fromhex("560900b41f2003d5"),  # cbz x22, #0x1819100; nop
        },
        {
            "description": "bypass region info ping alert check in HomeUIManager.CheckRegionInfo",
            "offset": 0x15A2BE8,
            "expected": bytes.fromhex("f85fbca9f65701a9"),  # stp x24, x23, [sp, #-0x40]!; stp x22, x21, [sp, #0x10]
            "replacement": bytes.fromhex("e00301aa22c31814"),  # mov x0, x1; b #0x1bd3874 (ActionExtensions.Call(onFinished))
        },

        {
            "description": "bypass ObjectDisposedException in GetAssignmentsDestroy on scene exit",
            "offset": 0x13EAFB4,
            "expected": bytes.fromhex("b4010036"),  # tbz w20, #0, #0x13eafe8
            "replacement": bytes.fromhex("0d000014"),  # b #0x13eafe8
        },
        {
            "description": "safely bypass SpecialSkillMaster null check in PlayerSpecialSkilParameter..ctor",
            "offset": 0x18BF7C8,
            "expected": bytes.fromhex("570000b58852e597"),  # cbnz x23, #0x18bf7d0; bl #0x12141ec
            "replacement": bytes.fromhex("771300b41f2003d5"),  # cbz x23, #0x18bfa34; nop
        },
        {
            "description": "safely bypass null FieldInfo in PlayerStateBackStep..ctor",
            "offset": 0x18C3DC0,
            "expected": bytes.fromhex("540000b50a41e597e00314aae1031faaf2cafb97f40300aa540000b50441e597e00314aae1031faad1cbfb97f40300aa540000b5fe40e597"),
            "replacement": bytes.fromhex("540200b41f2003d5e00314aae1031faaf2cafb97f40300aa940100b41f2003d5e00314aae1031faad1cbfb97f40300aad40000b41f2003d5"),
        },
        {
            "description": "transition to GameScene via ChangeGameSceneSync at end of ApplyBattleProperties",
            "offset": 0x17A2430,
            "expected": bytes.fromhex("c0035fd6"),  # ret
            "replacement": bytes.fromhex("0f03f517"),  # b #0x14e306c (ChangeGameSceneSync)
        },
        {
            "description": "bypass _isChangeScene check in SceneManager.ChangeScene",
            "offset": 0x1CAC918,
            "expected": bytes.fromhex("c8000034"),  # cbz w8, #0x1cac930
            "replacement": bytes.fromhex("06000014"),  # b #0x1cac930
        },
        {
            "description": "safely return null when model asset is null in ModelManager.InstantiateModel",
            "offset": 0x19F5338,
            "expected": bytes.fromhex("770000b5e0031faaab7be097"),
            "replacement": bytes.fromhex("770000b5f6031faa24000014"),
        },
        {
            "description": "safely return null when model instantiation fails in ModelManager.InstantiateModel",
            "offset": 0x19F53A8,
            "expected": bytes.fromhex("e0031faa907be097"),
            "replacement": bytes.fromhex("f6031faa09000014"),
        },
        {
            "description": "instantiate DiscSkillValidator in SkillRangeValidator.CreateValidator instead of returning null",
            "offset": 0x18436D0,
            "expected": bytes.fromhex("002140f9"),
            "replacement": bytes.fromhex("0b000014"),  # b #0x18436fc
        },
        {
            "description": "instantiate KickerSkillValidator in SkillRangeValidator.CreateValidator instead of returning null",
            "offset": 0x1843740,
            "expected": bytes.fromhex("002140f9"),
            "replacement": bytes.fromhex("0b000014"),  # b #0x184376c
        },
        {
            "description": "apply condition locally in SpecialSkillActionBase.AcceptCondition without waiting for RPC",
            "offset": 0x1503B8C,
            "expected": bytes.fromhex("a0000036"),  # tbz w0, #0, #0x1503ba0
            "replacement": bytes.fromhex("05000014"),  # b #0x1503ba0
        },
        {
            "description": "remove condition locally in SpecialSkillActionBase.AcceptRemoveCondition without waiting for RPC",
            "offset": 0x1503C04,
            "expected": bytes.fromhex("a0000036"),  # tbz w0, #0, #0x1503c18
            "replacement": bytes.fromhex("05000014"),  # b #0x1503c18
        },
        {
            "description": "prevent dropping RPCs in ReplayManager.SendRPC when Photon is not connected or in offline mode",
            "offset": 0x177581C,
            "expected": bytes.fromhex("e00a0036"),  # tbz w0, #0, #0x1775978
            "replacement": bytes.fromhex("1f2003d5"),  # nop
        },
        {
            "description": "safely bypass null Player in KickerSkillParameter.GetRange for bots",
            "offset": 0x153B678,
            "expected": bytes.fromhex("730000b5e0031faadb62f397"),
            "replacement": bytes.fromhex("130100b41f2003d51f2003d5"),
        },
        {
            "description": "safely bypass null Player in DiscSkillParameter.GetRange for bots",
            "offset": 0x148ECE0,
            "expected": bytes.fromhex("730000b5e0031faa4115f697"),
            "replacement": bytes.fromhex("130100b41f2003d51f2003d5"),
        },
        {
            "description": "safely return 0.0 when SkillMaster is null in SkillParameterBase.GetRange for bots",
            "offset": 0x184321C,
            "expected": bytes.fromhex("730000b5e0031faaf243e797"),
            "replacement": bytes.fromhex("730000b5e003271e02000014"),
        },
        {
            "description": "safely return when lock-on controller is null for remote player in PlayerCharacter.ApplySetLockOnTarget",
            "offset": 0x13df9e0,
            "expected": bytes.fromhex("b80000b4"),
            "replacement": bytes.fromhex("182400b4"),
        },
        {
            "description": "safely return when SkillActionDataManager is null in DiscSkillMasterData..ctor",
            "offset": 0x148b904,
            "expected": bytes.fromhex("550000b53922f697"),
            "replacement": bytes.fromhex("150600b41f2003d5"),
        },
        {
            "description": "safely return when ActionMasterData is null in DiscSkillMasterData..ctor",
            "offset": 0x148b958,
            "expected": bytes.fromhex("140100b4"),
            "replacement": bytes.fromhex("740300b4"),
        },
        {
            "description": "safely return null when action master list is null in SkillActionDataManager.GetActionMasterData",
            "offset": 0x1833440,
            "expected": bytes.fromhex("760000b5e0031faa6983e797"),
            "replacement": bytes.fromhex("160400b41f2003d51f2003d5"),
        },
        {
            "description": "bypass _isUnloading check in LoadManager.LoadCacheAsync so scene transition models are always queued",
            "offset": 0x16E2AD8,
            "expected": bytes.fromhex("88724039a8000034"),
            "replacement": bytes.fromhex("060000141f2003d5"),
        },
        {
            "description": "safely fallback to default kicker when MyPlayerBattleInfo is null in LoadInGameKickerEffect",
            "offset": 0x16E7D90,
            "expected": bytes.fromhex("e0031faa16b1ec97e0031faa"),
            "replacement": bytes.fromhex("37008052230080520a000014"),
        },
        {
            "description": "bypass null BattleRuleInfo check in CallbackBattleStartSuccess and jump to BattleStart",
            "offset": 0x13EA054,
            "expected": bytes.fromhex("a88301d0"),
            "replacement": bytes.fromhex("53000014"),
        },
        {
            "description": "bypass null button crash in TitleView.SetAllButtonActive",
            "offset": 0x31C496C,
            "expected": bytes.fromhex("f50f1df8f44f01a9"),  # str x21, [sp, #-0x30]!; stp x20, x19, [sp, #0x10]
            "replacement": bytes.fromhex("e0031f2ac0035fd6"),  # mov w0, wzr; ret (return false)
        },
        {
            "description": "bypass null _button crash in TitleView.Initialize",
            "offset": 0x31C7950,
            "expected": bytes.fromhex("770000b5e0031faa25328197"),  # cbnz x23, #0x31c795c; bl #0x12141ec
            "replacement": bytes.fromhex("f70000b4020000141f2003d5"),  # cbz x23, #0x31c795c; nop
        },
        {
            "description": "bypass null _canvasGroup crash in TitleView.Initialize",
            "offset": 0x31C7970,
            "expected": bytes.fromhex("740000b5e0031faa1d328197"),  # cbnz x20, #0x31c797c; bl #0x12141ec
            "replacement": bytes.fromhex("f40000b4020000141f2003d5"),  # cbz x20, #0x31c797c; nop
        },
        {
            "description": "bypass null field crash at 0x31c79b4 in TitleView.Initialize",
            "offset": 0x31C79B4,
            "expected": bytes.fromhex("750000b5e0031faa0c328197b44200f9"),
            "replacement": bytes.fromhex("950000b4b44200f91f2003d51f2003d5"),
        },
        {
            "description": "clean stack epilogue and return in TitleView.Initialize before null field crash (0x31c79c4)",
            "offset": 0x31C79C4,
            "expected": bytes.fromhex("733640f9e0031faa666fdf97e89100b008fd44f9"),
            "replacement": bytes.fromhex("fd7b43a9f44f42a9f65741a9f70744f8c0035fd6"),
        },

        {
            "description": "safely skip null controller in TitleView coroutine MoveNext (0x31c77b4)",
            "offset": 0x31C77B4,
            "expected": bytes.fromhex("740000b5e0031faa8c328197"),
            "replacement": bytes.fromhex("d40000b41f2003d51f2003d5"),
        },
        {
            "description": "safely skip null animation in TitleView coroutine MoveNext (0x31c77d8)",
            "offset": 0x31C77D8,
            "expected": bytes.fromhex("540000b584328197"),
            "replacement": bytes.fromhex("b40000b41f2003d5"),
        },
        {
            "description": "safely skip weapon attachment when WeaponModelController is null in PlayerCharacter.SetModel",
            "offset": 0x13C941C,
            "expected": bytes.fromhex("770000b5e0031faa722bf997"),
            "replacement": bytes.fromhex("970600b41f2003d51f2003d5"),
        },
        {
            "description": "safely clamp Team 0 spawn point index to valid array bounds (0x17407f4)",
            "offset": 0x17407F4,
            "expected": bytes.fromhex("f451eb97e1031faae2031faa574eeb97"),
            "replacement": bytes.fromhex("1c0500719cc39f1a020000141f2003d5"),
        },
        {
            "description": "safely clamp Team 1 spawn point index to valid array bounds (0x1740bc0)",
            "offset": 0x1740BC0,
            "expected": bytes.fromhex("0151eb97e1031faae2031faa644deb97"),
            "replacement": bytes.fromhex("1805007118c39f1a020000141f2003d5"),
        },
        {
            "description": "safely clamp Team 1 spawn point index in secondary array (0x1740bf8)",
            "offset": 0x1740BF8,
            "expected": bytes.fromhex("f350eb97e1031faae2031faa564deb97"),
            "replacement": bytes.fromhex("1305007173c29f1a737e409301000014"),
        },
        {
            "description": "safely clamp spawn point slot index in 0x1740d2c (0x1740d5c)",
            "offset": 0x1740D5C,
            "expected": bytes.fromhex("9a50eb97e1031faae2031faafd4ceb97"),
            "replacement": bytes.fromhex("1305007173c29f1a737e409301000014"),
        },
        {
            "description": "safely skip Prop_R muzzle effect when weapon is null in TwoGunsAttackAction..ctor (Coco)",
            "offset": 0x147CAE0,
            "expected": bytes.fromhex("560000b5c25df697"),
            "replacement": bytes.fromhex("360900b41f2003d5"),
        },
        {
            "description": "safely skip Prop_L muzzle effect when weapon is null in TwoGunsAttackAction..ctor (Coco)",
            "offset": 0x147CC60,
            "expected": bytes.fromhex("540000b5625df697"),
            "replacement": bytes.fromhex("b40700b41f2003d5"),
        },
        {
            "description": "safely skip Prop_R muzzle effect when weapon is null in LaserAttackAction..ctor (Eleonora)",
            "offset": 0x16D7788,
            "expected": bytes.fromhex("560000b598f2ec97"),
            "replacement": bytes.fromhex("360900b41f2003d5"),
        },
        {
            "description": "safely skip Prop_L muzzle effect when weapon is null in LaserAttackAction..ctor (Eleonora)",
            "offset": 0x16D7908,
            "expected": bytes.fromhex("540000b538f2ec97"),
            "replacement": bytes.fromhex("b40700b41f2003d5"),
        },
        {
            "description": "safely skip missing effect attachment in BowgunAttackAction..ctor (Owlbert)",
            "offset": 0x14D75F0,
            "expected": bytes.fromhex("540000b5fef2f497"),
            "replacement": bytes.fromhex("940300b41f2003d5"),
        },
        {
            "description": "safely skip missing effect attachment in AttackAction_14a5fa4..ctor",
            "offset": 0x14A6078,
            "expected": bytes.fromhex("540000b55cb8f597"),
            "replacement": bytes.fromhex("940300b41f2003d5"),
        },
        {
            "description": "safely skip missing effect attachment in AttackAction_13f9fd8..ctor",
            "offset": 0x13FA0B4,
            "expected": bytes.fromhex("540000b54d68f897"),
            "replacement": bytes.fromhex("940300b41f2003d5"),
        },
        {
            "description": "safely skip missing effect attachment in AttackAction_151e3cc..ctor",
            "offset": 0x151E4A0,
            "expected": bytes.fromhex("540000b552d7f397"),
            "replacement": bytes.fromhex("940300b41f2003d5"),
        },
        {
            "description": "safely skip missing effect attachment in AttackAction_160846c..ctor",
            "offset": 0x1608540,
            "expected": bytes.fromhex("540000b52a2ff097"),
            "replacement": bytes.fromhex("940300b41f2003d5"),
        },
        {
            "description": "safely skip missing effect attachment in AttackAction_16989b0..ctor",
            "offset": 0x1698A84,
            "expected": bytes.fromhex("540000b5d9eded97"),
            "replacement": bytes.fromhex("940300b41f2003d5"),
        },
        {
            "description": "safely skip missing effect attachment in AttackAction_149d72c..ctor",
            "offset": 0x149D8F4,
            "expected": bytes.fromhex("540000b53ddaf597"),
            "replacement": bytes.fromhex("540200b41f2003d5"),
        },
        {
            "description": "safely skip missing effect attachment in AttackAction_1439e0c..ctor",
            "offset": 0x1439EE0,
            "expected": bytes.fromhex("550000b5c268f797"),
            "replacement": bytes.fromhex("950300b41f2003d5"),
        },
        {
            "description": "safely skip missing effect attachment in AttackAction_168efe4..ctor",
            "offset": 0x168F0F8,
            "expected": bytes.fromhex("540000b53c14ee97"),
            "replacement": bytes.fromhex("b40600b41f2003d5"),
        },
        {
            "description": "safely skip missing effect attachment in AttackAction_15ca5e0..ctor",
            "offset": 0x15CA6EC,
            "expected": bytes.fromhex("540000b5bf26f197"),
            "replacement": bytes.fromhex("b40600b41f2003d5"),
        },
        {
            "description": "safely return from PlayerCharacter.UpdateLookTarget when look target is uninitialized",
            "offset": 0x013CD984,
            "expected": bytes.fromhex("ee0f16fc"),
            "replacement": bytes.fromhex("c0035fd6"),  # ret
        },
        {
            "description": "safely return from PlayerCharacter.UpdateIdleTypeRate when idle rate is uninitialized",
            "offset": 0x013CE3DC,
            "expected": bytes.fromhex("ee0f19fc"),
            "replacement": bytes.fromhex("c0035fd6"),  # ret
        },
        {
            "description": "safely return from PlayerBoneController.LateUpdate when bone transforms are uninitialized",
            "offset": 0x013BA08C,
            "expected": bytes.fromhex("f50f1df8"),
            "replacement": bytes.fromhex("c0035fd6"),  # ret
        },
        {
            "description": "safely return from PlayerBoneController.SetPose when bone transforms are uninitialized",
            "offset": 0x013BA8F4,
            "expected": bytes.fromhex("ed33ba6d"),
            "replacement": bytes.fromhex("c0035fd6"),  # ret
        },
        {
            "description": "safely return from PlayerBoneController.InterpolationUpdate when bone transforms are uninitialized",
            "offset": 0x013BA65C,
            "expected": bytes.fromhex("ffc305d1"),
            "replacement": bytes.fromhex("c0035fd6"),  # ret
        },
        {
            "description": "force GameManager.get_IsAllPlayerLoaded to true for offline battle start sequence",
            "offset": 0x0156D7D8,
            "expected": bytes.fromhex("f44fbea9fd7b01a9"),
            "replacement": bytes.fromhex("20008052c0035fd6"),  # mov w0, #1; ret
        },
        {
            "description": "force GameManager.<BeginAsync>b__1 to return false (0) to bypass room property wait",
            "offset": 0x01579940,
            "expected": bytes.fromhex("f44fbea9fd7b01a9"),
            "replacement": bytes.fromhex("00008052c0035fd6"),  # mov w0, #0; ret
        },
        {
            "description": "force GameManager.<BeginAsync>b__2 to return false (0) to bypass room property wait",
            "offset": 0x0157999C,
            "expected": bytes.fromhex("f44fbea9fd7b01a9"),
            "replacement": bytes.fromhex("00008052c0035fd6"),  # mov w0, #0; ret
        },
        {
            "description": "force GameManager.<BeginAsync>b__3 to return false (0) to bypass room property wait",
            "offset": 0x01579A38,
            "expected": bytes.fromhex("f44fbea9fd7b01a9"),
            "replacement": bytes.fromhex("00008052c0035fd6"),  # mov w0, #0; ret
        },
        {
            "description": "force GameManager.<BeginAsync>b__4 to return false (0) to bypass room property wait",
            "offset": 0x01579AC8,
            "expected": bytes.fromhex("f44fbea9fd7b01a9"),
            "replacement": bytes.fromhex("00008052c0035fd6"),  # mov w0, #0; ret
        },
        {
            "description": "force GameManager.<BeginAsync>b__5 to return false (0) to bypass room property wait",
            "offset": 0x01579B80,
            "expected": bytes.fromhex("f44fbea9fd7b01a9"),
            "replacement": bytes.fromhex("00008052c0035fd6"),  # mov w0, #0; ret
        },
        {
            "description": "force GameManager.<BeginAsync>b__6 to return false (0) to bypass room property wait",
            "offset": 0x01579C1C,
            "expected": bytes.fromhex("f44fbea9fd7b01a9"),
            "replacement": bytes.fromhex("00008052c0035fd6"),  # mov w0, #0; ret
        },
        {
            "description": "bypass GameResultFade and ReplayManager in GameManager.<BeginAsync>d__71.MoveNext by jumping State 10 directly to 0x157a44c",
            "offset": 0x0157A30C,
            "expected": bytes.fromhex("08008012681200b9"),
            "replacement": bytes.fromhex("500000141f2003d5"),  # b #0x157a44c; nop
        },
        {
            "description": "safely skip PlayEnvironmentEffect and jump to GameReadyAsync when StageManager.Instance is null in GameManager.<BeginAsync>d__71.MoveNext",
            "offset": 0x0157A488,
            "expected": bytes.fromhex("550000b55867f297"),
            "replacement": bytes.fromhex("150a00b41f2003d5"),  # cbz x21, #0x157a5c8; nop
        },
        {
            "description": "force branch to 0x157a5c8 (GameReadyAsync) in GameManager.<BeginAsync>d__71.MoveNext bypassing static fields and AR reconnect",
            "offset": 0x0157A4A0,
            "expected": bytes.fromhex("c80240f9085d40f908654039e8080034"),
            "replacement": bytes.fromhex("4a0000141f2003d51f2003d51f2003d5"),  # b #0x157a5c8; 3x nop
        },
        {
            "description": "safely stub LoadDeckSummonModel to return immediately to avoid missing summon model crash in offline mode",
            "offset": 0x016E6CA8,
            "expected": bytes.fromhex("fc6fbaa9"),
            "replacement": bytes.fromhex("c0035fd6"),  # ret
        },
        {
            "description": "safely stub PlayerBoneController.GetDisplayAngles to return Vector3.zero avoiding null transform crash on combat start",
            "offset": 0x013BC3A8,
            "expected": bytes.fromhex("ed33bb6deb2b016de923026df44f03a9"),
            "replacement": bytes.fromhex("e003271ee103271ee203271ec0035fd6"),  # fmov s0..s2, wzr; ret
        },
        {
            "description": "bypass ReplayManager.BeginSession in GameScene.<PreBeginAsync>d__0.MoveNext when ReplayManager is null in offline mode",
            "offset": 0x0176280C,
            "expected": bytes.fromhex("540000b577c6ea97"),
            "replacement": bytes.fromhex("050000141f2003d5"),  # b #0x1762820; nop
        },
        {
            "description": "bypass ReplayManager.EndSession in GameScene.<PostEndAsync>d__3.MoveNext when ReplayManager is null in offline mode",
            "offset": 0x01762640,
            "expected": bytes.fromhex("550000b5eac6ea97"),
            "replacement": bytes.fromhex("050000141f2003d5"),  # b #0x1762654; nop
        },
        {
            "description": "safely stub CharacterAnimatorBase.IsCurrentState to return false avoiding null animator controller crash during combat flight",
            "offset": 0x016B5D5C,
            "expected": bytes.fromhex("ff4302d1f53300f9"),
            "replacement": bytes.fromhex("00008052c0035fd6"),  # mov w0, #0; ret
        },
        {
            "description": "safely stub CharacterAnimatorBase.IsInTransition to return false avoiding null animator controller crash during combat flight",
            "offset": 0x016B5D24,
            "expected": bytes.fromhex("f44fbea9fd7b01a9"),
            "replacement": bytes.fromhex("00008052c0035fd6"),  # mov w0, #0; ret
        },
        {
            "description": "ponytail: stub GameReadyScene.GetGameReadyAnimationClip entry to return null, one guard covers all three null-throw sites inside (0x176035c/0x1760378/0x17603cc); sole caller 0x175fa7c skips clip-use region via 0x175fab4 guard",
            "offset": 0x01760304,
            "expected": bytes.fromhex("ffc300d1f44f01a9"),  # sub sp, sp, #0x30; stp x20, x19, [sp, #0x10]
            "replacement": bytes.fromhex("e0031faac0035fd6"),  # mov x0, xzr; ret (return null clip)
        },
        {
            "description": "ponytail: skip clip-use region when clip is null (cbz x26 to 0x175fb88 cbnz, falls to throw-safe path via existing checks), non-null falls through via b to 0x175fac0; lands before x25 null-check so str preserves loop state (x24/x25) and reaches timeline tail 0x175fdc4",
            "offset": 0x0175FAB4,
            "expected": bytes.fromhex("7a0000b5e0031faaccd1ea97"),  # cbnz x26, #0x175fac0; mov x0, xzr; bl throw
            "replacement": bytes.fromhex("ba0600b4020000141f2003d5"),  # cbz x26, #0x175fb88; b #0x175fac0; nop
        },
        {
            "description": "ponytail: force Play past w2 gate (bypass tbz w21 at 0x175aff4, sole caller w2=0) so shared-gate result is ignored and setup runs; downstream cbnz null-throws preserved, epilogue still reachable via normal ret",
            "offset": 0x0175AFF4,
            "expected": bytes.fromhex("55030036"),  # tbz w21, #0, #0x175b05c (epilogue ret)
            "replacement": bytes.fromhex("1f2003d5"),  # nop (always fall through to state-check/setup)
        },
        {
            "description": "safely early-exit PlayerStateNormal.UpdateAction when animator lookup object is null (2nd cbnz site)",
            "offset": 0x017E13EC,
            "expected": bytes.fromhex("540000b57fcbe897"),  # cbnz x20, #0x17e13f4; bl throw
            "replacement": bytes.fromhex("542f00b41f2003d5"),  # cbz x20, #0x17e19d4; nop
        },
        {
            "description": "safely gate PlayerStateNormal.UpdateAction for local User (PlayerType == 1), exit early to epilogue for null or bots/AI",
            "offset": 0x017E13C4,
            "expected": bytes.fromhex("e00313aae1031faa537e0394f40300aa540000b585cbe897"),  # mov x0, x19; mov x1, xzr; bl get_Player; mov x20, x0; cbnz x20, #0x17e13dc; bl throw
            "replacement": bytes.fromhex("680a40f9683000b4098941b93f05007101300054f40308aa"),  # ldr x8, [x19, #0x10]; cbz x8, #0x17e19d4; ldr w9, [x8, #0x188]; cmp w9, #1; b.ne #0x17e19d4; mov x20, x8
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E1420,
            "expected": bytes.fromhex("73cbe897"),
            "replacement": bytes.fromhex("6d010014"),  # b #0x17e19d4
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E1444,
            "expected": bytes.fromhex("6acbe897"),
            "replacement": bytes.fromhex("64010014"),  # b #0x17e19d4
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E14AC,
            "expected": bytes.fromhex("50cbe897"),
            "replacement": bytes.fromhex("4a010014"),  # b #0x17e19d4
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E14C4,
            "expected": bytes.fromhex("4acbe897"),
            "replacement": bytes.fromhex("44010014"),  # b #0x17e19d4
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E153C,
            "expected": bytes.fromhex("2ccbe897"),
            "replacement": bytes.fromhex("26010014"),  # b #0x17e19d4
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E1564,
            "expected": bytes.fromhex("22cbe897"),
            "replacement": bytes.fromhex("1c010014"),  # b #0x17e19d4
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E158C,
            "expected": bytes.fromhex("18cbe897"),
            "replacement": bytes.fromhex("12010014"),  # b #0x17e19d4
        },
        {
            "description": "safely skip WeaponAction attack in PlayerStateNormal.UpdateAction when null",
            "offset": 0x017E15A0,
            "expected": bytes.fromhex("750000b5"),  # cbnz x21, #0x17e15ac
            "replacement": bytes.fromhex("950700b4"),  # cbz x21, #0x17e1690
        },
        {
            "description": "safely skip WeaponAction attack throw in PlayerStateNormal.UpdateAction",
            "offset": 0x017E15A8,
            "expected": bytes.fromhex("11cbe897"),
            "replacement": bytes.fromhex("3a000014"),  # b #0x17e1690
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E16A4,
            "expected": bytes.fromhex("d2cae897"),
            "replacement": bytes.fromhex("cc000014"),  # b #0x17e19d4
        },
        {
            "description": "safely skip Land state routine in PlayerStateNormal.UpdateAction when null",
            "offset": 0x017E16BC,
            "expected": bytes.fromhex("950300b4"),  # cbz x21, #0x17e172c
            "replacement": bytes.fromhex("150400b4"),  # cbz x21, #0x17e173c
        },
        {
            "description": "safely skip Land state throw in PlayerStateNormal.UpdateAction",
            "offset": 0x017E16F8,
            "expected": bytes.fromhex("bdcae897"),
            "replacement": bytes.fromhex("11000014"),  # b #0x17e173c
        },
        {
            "description": "safely skip Land state cast throw in PlayerStateNormal.UpdateAction",
            "offset": 0x017E172C,
            "expected": bytes.fromhex("b0cae897"),
            "replacement": bytes.fromhex("04000014"),  # b #0x17e173c
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E1750,
            "expected": bytes.fromhex("a7cae897"),
            "replacement": bytes.fromhex("a1000014"),  # b #0x17e19d4
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E1768,
            "expected": bytes.fromhex("a1cae897"),
            "replacement": bytes.fromhex("9b000014"),  # b #0x17e19d4
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E1794,
            "expected": bytes.fromhex("96cae897"),
            "replacement": bytes.fromhex("90000014"),  # b #0x17e19d4
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E17AC,
            "expected": bytes.fromhex("90cae897"),
            "replacement": bytes.fromhex("8a000014"),  # b #0x17e19d4
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E17D4,
            "expected": bytes.fromhex("86cae897"),
            "replacement": bytes.fromhex("80000014"),  # b #0x17e19d4
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E17EC,
            "expected": bytes.fromhex("80cae897"),
            "replacement": bytes.fromhex("7a000014"),  # b #0x17e19d4
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E1818,
            "expected": bytes.fromhex("75cae897"),
            "replacement": bytes.fromhex("6f000014"),  # b #0x17e19d4
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E1858,
            "expected": bytes.fromhex("65cae897"),
            "replacement": bytes.fromhex("5f000014"),  # b #0x17e19d4
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E1870,
            "expected": bytes.fromhex("5fcae897"),
            "replacement": bytes.fromhex("59000014"),  # b #0x17e19d4
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E1898,
            "expected": bytes.fromhex("55cae897"),
            "replacement": bytes.fromhex("4f000014"),  # b #0x17e19d4
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E18D8,
            "expected": bytes.fromhex("45cae897"),
            "replacement": bytes.fromhex("3f000014"),  # b #0x17e19d4
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E18F0,
            "expected": bytes.fromhex("3fcae897"),
            "replacement": bytes.fromhex("39000014"),  # b #0x17e19d4
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E190C,
            "expected": bytes.fromhex("38cae897"),
            "replacement": bytes.fromhex("32000014"),  # b #0x17e19d4
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E194C,
            "expected": bytes.fromhex("28cae897"),
            "replacement": bytes.fromhex("22000014"),  # b #0x17e19d4
        },
        {
            "description": "safely branch to epilogue in PlayerStateNormal.UpdateAction throw sites instead of throwing NRE every frame",
            "offset": 0x017E1964,
            "expected": bytes.fromhex("22cae897"),
            "replacement": bytes.fromhex("1c000014"),  # b #0x17e19d4
        },
        {
            "description": "ponytail: force Play gate 0x175b530 to always return false (nop tbz at 0x175b598 falls through to mov w0,wzr, skipping the 0x23ecf30-gated true path with its x19 null-throw at 0x175ba8); Play then uses AFE4 state-check + 0x175aff4 nop to reach setup",
            "offset": 0x0175B598,
            "expected": bytes.fromhex("60000036"),  # tbz w0, #0, #0x175b5a4 (little-endian: 36 00 00 60)
            "replacement": bytes.fromhex("1f2003d5"),  # nop (fall through to return false)
        },
        {
            "description": "force ReplayManager.get_ReplayMode to return 0 (not replay/playback)",
            "offset": 0x1773670,
            "expected": bytes.fromhex("f30f1ef8fd7b01a9"),  # str x19, [sp, #-0x20]!; stp x29, x30, [sp, #0x10]
            "replacement": bytes.fromhex("e0031f2ac0035fd6"),  # mov w0, wzr; ret
        },
        {
            "description": "force GameManager.GetMenuType to return 0 (MenuType.Default)",
            "offset": 0x1570EA8,
            "expected": bytes.fromhex("f44fbea9fd7b01a9"),  # stp x20, x19, [sp, #-0x20]!; stp x29, x30, [sp, #0x10]
            "replacement": bytes.fromhex("e0031f2ac0035fd6"),  # mov w0, wzr; ret
        },
        {
            "description": "ponytail: stub PlayerAnimator.IsBindMotionCondition to return true, one guard covers PlayIdle + 0x13d7a2c and all downstream IsCondition leaf null-throws; true makes PlayIdle early-ret safely instead of derefing null animator",
            "offset": 0x013AEA90,
            "expected": bytes.fromhex("f30f1ef8fd7b01a9"),  # str x19, [sp, #-0x20]!; stp x29, x30, [sp, #0x10]
            "replacement": bytes.fromhex("20008052c0035fd6"),  # mov w0, #1; ret
        },
        {
            "description": "safely stub PlayerBoneController.SetDisplayAngles to return immediately avoiding null model crash",
            "offset": 0x013BC314,
            "expected": bytes.fromhex("ea0f1cfc"),  # str d10, [sp, #-0x40]!
            "replacement": bytes.fromhex("c0035fd6"),  # ret
        },
        {
            "description": "bypass null festival check in GameStartAnimation.PlayReadyAnimation by jumping directly to non-festival setup",
            "offset": 0x01762D80,
            "expected": bytes.fromhex("540000b51ac5ea97"),  # cbnz x20, #0x1762d88; bl #0x12141ec
            "replacement": bytes.fromhex("f40d00b41f2003d5"),  # cbz x20, #0x1762f3c; nop
        },
        {
            "description": "determine IsAi from MatchingPlayerBattleInfo.kickerAiParameterId instead of PhotonPlayer null-check",
            "offset": 0x017A17F4,
            "expected": bytes.fromhex("f35cf097e1031faad1090594f50300aa770000b5e0031faa78cae997bf0200f1e1179f1a"),
            "replacement": bytes.fromhex("084740b91f010071e1079f1a1f2003d51f2003d51f2003d51f2003d51f2003d51f2003d5"),
        },
        {
            "description": "safely clamp DroneAbilityParameter.get_TimeData to element 0 when length <= 1 avoiding IndexOutOfRangeException",
            "offset": 0x0149D3A8,
            "expected": bytes.fromhex("07dff597e1031faae2031faa6adbf597"),
            "replacement": bytes.fromhex("601240f9040000141f2003d51f2003d5"),
        },
        {
            "description": "prevent GameManager.BeginReconnectFailed from disconnecting Photon",
            "offset": 0x1577F94,
            "expected": bytes.fromhex("f44fbea9"),  # stp x20, x19, [sp, #-0x20]!
            "replacement": bytes.fromhex("c0035fd6"),  # ret
        },
        {
            "description": "prevent GameManager.BeginReconnectRoomFailed from disconnecting Photon",
            "offset": 0x1578060,
            "expected": bytes.fromhex("f44fbea9"),  # stp x20, x19, [sp, #-0x20]!
            "replacement": bytes.fromhex("c0035fd6"),  # ret
        },
        {
            "description": "force PhotonPropertyManagerBase.CheckInitializeError to return false",
            "offset": 0x1A2AB5C,
            "expected": bytes.fromhex("f85fbca9"),  # stp x24, x23, [sp, #-0x40]!
            "replacement": bytes.fromhex("00008052c0035fd6"),  # mov w0, #0; ret
        },
        {
            "description": "prevent PhotonPropertyManagerBase.StartDisconnectTime from starting disconnect timer",
            "offset": 0x1A2AC50,
            "expected": bytes.fromhex("f70f1cf8"),  # str x23, [sp, #-0x40]!
            "replacement": bytes.fromhex("c0035fd6"),  # ret
        },
        {
            "description": "safely bypass fieldOfView read when camera is null in SpecialSkillCut.Initialize",
            "offset": 0x1504AD4,
            "expected": bytes.fromhex("580000b5c53df497"),  # cbnz x24, #0x1504adc; bl #0x12141ec
            "replacement": bytes.fromhex("d80000b41f2003d5"),  # cbz x24, #0x1504aec; nop
        },
        {
            "description": "safely bypass CinemachineBrain lookup when camera is null in SpecialSkillCut.Initialize",
            "offset": 0x1504C60,
            "expected": bytes.fromhex("760000b5e0031faa613df497"),  # cbnz x22, #0x1504c6c; mov x0, xzr; bl #0x12141ec
            "replacement": bytes.fromhex("160100b41f2003d51f2003d5"),  # cbz x22, #0x1504c80; nop; nop
        },
        {
            "description": "bypass null _fovFitter exception in SpecialSkillCut.LateUpdate",
            "offset": 0x150539C,
            "expected": bytes.fromhex("740000b5e0031faa923bf497"),  # cbnz x20, #0x15053a8; mov x0, xzr; bl #0x12141ec
            "replacement": bytes.fromhex("740b00b41f2003d51f2003d5"),  # cbz x20, #0x1505508; nop; nop
        },
        {
            "description": "bypass null _rollFitter exception in SpecialSkillCut.LateUpdate",
            "offset": 0x15053B8,
            "expected": bytes.fromhex("740000b5e0031faa8b3bf497"),  # cbnz x20, #0x15053c4; mov x0, xzr; bl #0x12141ec
            "replacement": bytes.fromhex("940a00b41f2003d51f2003d5"),  # cbz x20, #0x1505508; nop; nop
        },
        {
            "description": "bypass null _windRoot exception in SpecialSkillCut.LateUpdate",
            "offset": 0x15053D8,
            "expected": bytes.fromhex("740000b5e0031faa833bf497"),  # cbnz x20, #0x15053e4; mov x0, xzr; bl #0x12141ec
            "replacement": bytes.fromhex("940900b41f2003d51f2003d5"),  # cbz x20, #0x1505508; nop; nop
        },
        {
            "description": "bypass null _wind exception in SpecialSkillCut.LateUpdate",
            "offset": 0x15053F4,
            "expected": bytes.fromhex("750000b5e0031faa7c3bf497"),  # cbnz x21, #0x1505400; mov x0, xzr; bl #0x12141ec
            "replacement": bytes.fromhex("b50800b41f2003d51f2003d5"),  # cbz x21, #0x1505508; nop; nop
        },
        {
            "description": "safely bypass null camera fieldOfView in SpecialSkillCut.Play",
            "offset": 0x1506018,
            "expected": bytes.fromhex("750000b5e0031faa7338f497"),  # cbnz x21, #0x1506024; mov x0, xzr; bl #0x12141ec
            "replacement": bytes.fromhex("f50000b41f2003d51f2003d5"),  # cbz x21, #0x1506034; nop; nop
        },
        {
            "description": "safely bypass null CinemachineBrain in SpecialSkillCut.Play",
            "offset": 0x1506038,
            "expected": bytes.fromhex("750000b5e0031faa6b38f497"),  # cbnz x21, #0x1506044; mov x0, xzr; bl #0x12141ec
            "replacement": bytes.fromhex("150100b41f2003d51f2003d5"),  # cbz x21, #0x1506058; nop; nop
        },
        {
            "description": "set NormalMatchingJoinBattleRoomState.GetDelayTime to 0.0s to eliminate lobby join stagger",
            "offset": 0x13EFE74,
            "expected": bytes.fromhex("ff4302d1e82300fd"),  # sub sp, sp, #0x90; str d8, [sp, #0x40]
            "replacement": bytes.fromhex("e003271ec0035fd6"),  # fmov s0, wzr; ret
        },
        {
            "description": "safely bypass ReconnectInfo null dereference in GameManager.InitializeReconnect",
            "offset": 0x1570164,
            "expected": bytes.fromhex("f70f1cf8"),  # str x23, [sp, #-0x40]!
            "replacement": bytes.fromhex("c0035fd6"),  # ret
        },
        {
            "description": "prevent native SIGSEGV in List<LocalClient.InternalMsg>.Contains on uninitialized memory",
            "offset": 0x2F277B8,
            "expected": bytes.fromhex("f90f1bf8f85f01a9"),  # str x25, [sp, #-0x50]!; stp x24, x23, [sp, #0x10]
            "replacement": bytes.fromhex("e0031f2ac0035fd6"),  # mov w0, wzr; ret
        },
        {
            "description": "safely bypass null _goRoot in GameStartAnimation.PlayGoAnimation",
            "offset": 0x17630FC,
            "expected": bytes.fromhex("740000b5e0031faa3ac4ea97"),  # cbnz x20, #0x1763108; mov x0, xzr; bl #0x12141ec
            "replacement": bytes.fromhex("b40800b41f2003d51f2003d5"),  # cbz x20, #0x1763210; nop; nop
        },
        {
            "description": "dispatch CallbackGetAssignments: Case 0 when connection is empty, Case 1 when connection is populated",
            "offset": 0x13EE484,
            "expected": bytes.fromhex("df120071280b0054c9f100b0e803162a298104912879a8b80801098b00011fd6"),
            "replacement": bytes.fromhex("880e40f9480200b4091140b909020034190000141f2003d51f2003d51f2003d5"),
        },
    ],
    "armeabi-v7a": [
        {
            "description": "force HTTP for direct server access",
            "offset": 0x2AC1798,
            "expected": bytes.fromhex("02309f17"),
            "replacement": bytes.fromhex("0000a0e1"),  # mov r0, r0 (skip HTTPS override)
        },
    ],
}

UNITY_PATCHES: dict[str, list[dict[str, object]]] = {
    "arm64-v8a": [
        {
            "description": "bypass 16GB memory radix table overflow crash in Insert",
            "offset": 0xA045C4,
            "expected": bytes.fromhex("06000014"),  # b #0xa045dc
            "replacement": bytes.fromhex("74000014"),  # b #0xa04794 (epilogue)
        },
        {
            "description": "bypass 16GB memory radix table overflow error handler in Insert",
            "offset": 0xA045DC,
            "expected": bytes.fromhex("882e00b0"),  # adrp x8, #0xfd5000
            "replacement": bytes.fromhex("6e000014"),  # b #0xa04794 (epilogue)
        },
        {
            "description": "bypass 16GB memory radix table overflow crash in Remove",
            "offset": 0xA0481C,
            "expected": bytes.fromhex("06000014"),  # b #0xa04834
            "replacement": bytes.fromhex("66000014"),  # b #0xa049b4 (epilogue)
        },
        {
            "description": "bypass 16GB memory radix table overflow error handler in Remove",
            "offset": 0xA04834,
            "expected": bytes.fromhex("882e00b0"),  # adrp x8, #0xfd5000
            "replacement": bytes.fromhex("60000014"),  # b #0xa049b4 (epilogue)
        },
        {
            "description": "bind libunity internal operator new to Unity MemoryManager",
            "offset": 0xDA630,
            "expected": bytes.fromhex("509100f0"),  # adrp x16, #0x1305000
            "replacement": bytes.fromhex("1ac01014"),  # b #0x50a698
        },
        {
            "description": "bind libunity internal operator delete to Unity MemoryManager",
            "offset": 0xDA690,
            "expected": bytes.fromhex("509100f0"),  # adrp x16, #0x1305000
            "replacement": bytes.fromhex("61b91014"),  # b #0x508c14
        },
        {
            "description": "bind libunity internal nothrow operator delete to Unity MemoryManager",
            "offset": 0xDA8D0,
            "expected": bytes.fromhex("509100f0"),  # adrp x16, #0x1305000
            "replacement": bytes.fromhex("66c01014"),  # b #0x50aa68
        },
        {
            "description": "bind libunity internal operator new[] to Unity MemoryManager",
            "offset": 0xDAA20,
            "expected": bytes.fromhex("509100f0"),  # adrp x16, #0x1305000
            "replacement": bytes.fromhex("b3bf1014"),  # b #0x50a8ec
        },
        {
            "description": "bind libunity internal operator delete[] to Unity MemoryManager",
            "offset": 0xDAC50,
            "expected": bytes.fromhex("509100f0"),  # adrp x16, #0x1305000
            "replacement": bytes.fromhex("67bf1014"),  # b #0x50a9ec
        },
        {
            "description": "bind libunity internal nothrow operator new to Unity MemoryManager",
            "offset": 0xDAE30,
            "expected": bytes.fromhex("509100f0"),  # adrp x16, #0x1305000
            "replacement": bytes.fromhex("f6be1014"),  # b #0x50aa08
        },
        {
            "description": "route MemoryManager::Reallocate allocator check through null-safe handler stub",
            "offset": 0x50AE7C,
            "expected": bytes.fromhex("080040f9"),  # ldr x8, [x0]
            "replacement": bytes.fromhex("1d000014"),  # b #0x50aef0
        },
        {
            "description": "bypass invalid free call on unowned pointer in MemoryManager::Deallocate",
            "offset": 0x50AED4,
            "expected": bytes.fromhex("e00000b4"),  # cbz x0, #0x50aef0
            "replacement": bytes.fromhex("c00100b4"),  # cbz x0, #0x50af0c
        },
        {
            "description": "null-safe allocator stub in MemoryManager for Reallocate and Deallocate",
            "offset": 0x50AEF0,
            "expected": bytes.fromhex("c8068352886a6838a8000034e00313aaf37b41a9f40742f8023def17"),
            "replacement": bytes.fromhex("600000b4080040f9e2ffff171f0300f168fe61d30213889ae3ffff17"),
        },
    ],
}


def normalize_base_url(value: str) -> tuple[str, str]:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() != "http":
        raise ValueError("serverBaseUrl must use http:// for direct, certificate-free LAN access")
    if not parsed.hostname or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("serverBaseUrl must contain only scheme, host, and optional port")
    authority = parsed.netloc
    return f"http://{authority}", authority


def patch_metadata(path: Path, base_url: str, authority: str) -> list[dict[str, object]]:
    data = bytearray(path.read_bytes())
    sanity, version = struct.unpack_from("<II", data, 0)
    if sanity != SANITY or version != METADATA_VERSION:
        raise ValueError(f"unsupported IL2CPP metadata header: sanity=0x{sanity:x}, version={version}")

    literal_offset, literal_count, literal_data_offset, literal_data_count = struct.unpack_from("<IIII", data, 8)
    if literal_count % 8:
        raise ValueError("invalid IL2CPP string literal table size")

    active_literals: dict[int, str] = {}
    for index in range(literal_count // 8):
        length, data_index = struct.unpack_from("<II", data, literal_offset + index * 8)
        raw = bytes(data[literal_data_offset + data_index : literal_data_offset + data_index + length])
        try:
            value = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if index in LITERAL_INDEXES.values():
            active_literals[index] = value

    if set(active_literals) != set(LITERAL_INDEXES.values()):
        raise ValueError("missing expected endpoint literal indexes")

    replacement_blob = bytearray()
    report: list[dict[str, object]] = []
    for original, kind in ORIGINAL_LITERALS.items():
        if kind == "base_url":
            replacement = base_url
        elif kind == "authority":
            replacement = f"{authority}/"
        elif kind == "photon_host":
            parsed_host = urlsplit(base_url).hostname
            replacement = parsed_host if parsed_host else "10.0.2.2"
        else:
            replacement = base_url
        encoded = replacement.encode("utf-8")
        index = LITERAL_INDEXES[original]
        current = active_literals[index]
        if kind == "base_url":
            parsed_current = urlsplit(current)
            accepted = current == original or (
                parsed_current.scheme == "http"
                and bool(parsed_current.netloc)
                and parsed_current.path in ("", "/")
                and not parsed_current.query
                and not parsed_current.fragment
            )
        elif kind == "photon_host":
            accepted = current == original or current == "10.0.2.2" or (
                len(current.split(".")) == 4
            )
        else:
            accepted = current == original or (
                current.endswith("/")
                and ":" in current
                and "/" not in current[:-1]
            )
        if not accepted:
            raise ValueError(
                f"endpoint literal guard failed at index {index}: found {current!r}"
            )
        new_data_index = literal_data_count + len(replacement_blob)
        struct.pack_into("<II", data, literal_offset + index * 8, len(encoded), new_data_index)
        replacement_blob.extend(encoded)
        report.append({"literalIndex": index, "from": current, "to": replacement})

    while len(replacement_blob) % 4:
        replacement_blob.append(0)

    insertion_offset = literal_data_offset + literal_data_count
    delta = len(replacement_blob)
    data[insertion_offset:insertion_offset] = replacement_blob

    # Every remaining metadata table begins at an absolute offset recorded in
    # the header. Shift those tables by the inserted literal bytes.
    for pair_offset in range(8, literal_offset, 8):
        section_offset = struct.unpack_from("<I", data, pair_offset)[0]
        if section_offset >= insertion_offset:
            struct.pack_into("<I", data, pair_offset, section_offset + delta)
    struct.pack_into("<I", data, 20, literal_data_count + delta)

    path.write_bytes(data)
    return report


def patch_native(path: Path, abi: str, dry_run: bool = False) -> list[dict[str, object]]:
    patches = NATIVE_PATCHES[abi]
    data = bytearray(path.read_bytes())
    reports: list[dict[str, object]] = []
    for patch in patches:
        offset = int(patch["offset"])
        expected = bytes(patch["expected"])
        replacement = bytes(patch["replacement"])
        desc = patch.get("description", "")
        actual = bytes(data[offset : offset + len(expected)])
        if actual == replacement:
            reports.append({
                "abi": abi,
                "description": desc,
                "offset": f"0x{offset:x}",
                "from": actual.hex(),
                "to": replacement.hex(),
                "alreadyPatched": True,
            })
            continue
        if actual != expected:
            raise ValueError(
                f"{abi} native patch guard failed at 0x{offset:x} ({desc}): "
                f"expected {expected.hex()}, found {actual.hex()}"
            )
        data[offset : offset + len(replacement)] = replacement
        reports.append({
            "abi": abi,
            "description": desc,
            "offset": f"0x{offset:x}",
            "from": expected.hex(),
            "to": replacement.hex(),
        })
    if not dry_run:
        path.write_bytes(data)
    return reports


def patch_unity_native(path: Path, abi: str) -> list[dict[str, object]]:
    patches = UNITY_PATCHES.get(abi, [])
    if not patches:
        return []
    data = bytearray(path.read_bytes())
    reports: list[dict[str, object]] = []
    for patch in patches:
        offset = int(patch["offset"])
        expected = bytes(patch["expected"])
        replacement = bytes(patch["replacement"])
        desc = patch.get("description", "")
        actual = bytes(data[offset : offset + len(expected)])
        if actual == replacement:
            reports.append({
                "abi": abi,
                "library": "libunity.so",
                "description": desc,
                "offset": f"0x{offset:x}",
                "from": actual.hex(),
                "to": replacement.hex(),
                "alreadyPatched": True,
            })
            continue
        if actual != expected:
            raise ValueError(
                f"{abi} libunity native patch guard failed at 0x{offset:x} ({desc}): "
                f"expected {expected.hex()}, found {actual.hex()}"
            )
        data[offset : offset + len(replacement)] = replacement
        reports.append({
            "abi": abi,
            "library": "libunity.so",
            "description": desc,
            "offset": f"0x{offset:x}",
            "from": expected.hex(),
            "to": replacement.hex(),
        })
    path.write_bytes(data)
    return reports


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Validate patches without writing")
    parser.add_argument("--metadata", required=False, type=Path)
    parser.add_argument("--arm64", required=False, type=Path)
    parser.add_argument("--armv7", required=False, type=Path)
    parser.add_argument("--arm64-unity", required=False, type=Path)
    parser.add_argument("--base-url", required=False)
    parser.add_argument("dry_run_target", nargs="?", type=Path, help="Target .so file for dry-run")
    args = parser.parse_args()

    if args.dry_run:
        target = args.dry_run_target or args.arm64
        if not target:
            print("Error: dry-run requires a target .so file (e.g. --dry-run .local/libil2cpp_clean.so)", file=sys.stderr)
            return 1
        reports = patch_native(target, "arm64-v8a", dry_run=True)
        print(f"Dry-run successful on {target}: verified {len(reports)} patches.")
        return 0

    if not (args.metadata and args.arm64 and args.armv7 and args.base_url):
        parser.error("the following arguments are required: --metadata, --arm64, --armv7, --base-url")

    base_url, authority = normalize_base_url(args.base_url)
    native_reports = [
        *patch_native(args.arm64, "arm64-v8a"),
        *patch_native(args.armv7, "armeabi-v7a"),
    ]
    if args.arm64_unity and args.arm64_unity.is_file():
        native_reports.extend(patch_unity_native(args.arm64_unity, "arm64-v8a"))

    report = {
        "baseUrl": base_url,
        "metadata": patch_metadata(args.metadata, base_url, authority),
        "native": native_reports,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
