"""Patch Kick-Flight IL2CPP endpoint literals for a direct private server.

This script is intentionally specific to the preserved 2.11.0 APK. It validates
the metadata layout and native instruction bytes before changing anything.
"""

from __future__ import annotations

import argparse
import os
import json
import struct
from pathlib import Path
from urllib.parse import urlsplit


SANITY = 0xFAB11BAF
METADATA_VERSION = 24
ORIGINAL_LITERALS = {
    "https://colorful-api-octo-sb.grenge.jp": "base_url",
    "https://kickflight-resource-api.grenge.jp": "base_url",
    "kickflight-api.grenge.jp/": "authority",
}
LITERAL_INDEXES = {
    "https://colorful-api-octo-sb.grenge.jp": 2294,
    "https://kickflight-resource-api.grenge.jp": 2304,
    "kickflight-api.grenge.jp/": 9244,
}

# Battle-start / AI diagnostics. Off by default; enable with KF_DIAG=1 when building. Each hook logs an
# integer through __android_log_print (logcat tag KFDIAG). See docs/CONTINUATION_PROMPT_BATTLE_CRASH_FIX_V2.md §7.
DIAG_PATCHES_ARM64: list[dict[str, object]] = [
    # ---- DIAGNOSTIC (temporary): trace the battle start handshake via logcat tag KFDIAG ----
    # Logging goes straight to __android_log_print (PLT 0x10D6270); UnityEngine.Debug.Log* must NOT be
    # called from patched code here: its stack-trace capture walks through cave frames without unwind
    # info and dies in libunity's log formatter (+0x34426c) under ndk_translation.
    # Values: 1xx = UpdateRoomState(state), 2xx = UpdatePlayerState(state), 3xx = <BeginAsync> coroutine
    # state index on each resume, 4xx = RoomState read by GameManager.UpdateState, 119 = sanity (GameScene).
    {
        "description": "DIAG: caves in dead body of PlayerBoneController.SetDisplayAngles (log helper + hooks 1,2,A)",
        "offset": 0x13bc318,
        "expected": bytes.fromhex("e923016df44f02a9fd7b03a9fdc30091f30300aa740a40f9481ca24e291ca14e0a1ca04e740000b5e0031faaaa5ff997e00314aae1031faabb011b94f40300aa540000b5a45ff997e00314aae1031faa27354f94031ca04e241ca14e451ca24e401daa4e211da94e021da84ee0031faa1d5e20946006102d628a00bd"),
        "replacement": bytes.fromhex("f40300aafd7bbfa98092011109000094fd7bc1a8c0035fd6f90300aafd7bbfa9a022031103000094fd7bc1a8c0035fd6e2aa0c14e303002a60008052a1000010c2000010c567f497fd7bc1a8c0035fd64b46444941470000763d256400000000fd7bbfa9601240b900b00411f1ffff97681240b9fd7bc1a8c0035fd6"),
    },
    {
        "description": "DIAG: caves in dead body of GameManager.GetMenuType (hooks B, C)",
        "offset": 0x1570eb0,
        "expected": bytes.fromhex("fd430091d38a01d068525639e8000037687701b0080d40f9000140b9d1e3f197e803003268521639687901f0089545f9000140f9089c44398800083608d840b9480000359b18f297"),
        "replacement": bytes.fromhex("fd7bbea9e01300b900400611232df997e01340b9fd7bc2a81f1c0071c0035fd6fd7bbda9e00701a9e20f02a9e00e80521a2df997e20f42a9e00741a9fd7bc3a8f30f1ef811c50714"),
    },
    {
        "description": "DIAG hook1: PhotonPropertyManagerBase.UpdateRoomState -> log 100+state",
        "offset": 0x01A2A744,
        "expected": bytes.fromhex("f40300aa"),  # mov x20, x0
        "replacement": bytes.fromhex("f546e697"),
    },
    {
        "description": "DIAG hook2: PhotonPropertyManagerBase.UpdatePlayerState -> log 200+state",
        "offset": 0x01A2A87C,
        "expected": bytes.fromhex("f90300aa"),  # mov x25, x0
        "replacement": bytes.fromhex("ad46e697"),
    },
    {
        "description": "DIAG hookA: GameManager.<BeginAsync>.MoveNext dispatcher -> log 300+state index",
        "offset": 0x01579D30,
        "expected": bytes.fromhex("681240b9"),  # ldr w8, [x19, #0x10]
        "replacement": bytes.fromhex("9209f997"),
    },
    {
        "description": "DIAG hookB: GameManager.UpdateState -> log 400+RoomState each tick (cave re-does cmp w0,#7)",
        "offset": 0x0156E954,
        "expected": bytes.fromhex("1f1c0071"),  # cmp w0, #7
        "replacement": bytes.fromhex("57090094"),
    },
    {
        "description": "DIAG hookC: GameScene.RegisterPhotonCallback entry -> log 119 (b, not bl: entry hook must not clobber lr; cave jumps back)",
        "offset": 0x01762334,
        "expected": bytes.fromhex("f30f1ef8"),  # str x19, [sp, #-0x20]!
        "replacement": bytes.fromhex("e73af817"),
    },
    {
        "description": "DIAG: caves F/G (6xx = PlayerCharacter._enableAi store in DelayEnableAI, 700 = AIPlayerEngine.Start)",
        "offset": 0x1570f1c,
        "expected": bytes.fromhex("8800083608d840b9480000358e18f297e0031faad00908941f040071000b00549477019094e244f9800240f9089c44398800083608d840b9480000358218f297e0031faa"),
        "replacement": bytes.fromhex("fd7bbfa960620911092df997fd7bc1a893820339e0031f2ac0035fd6fd7bbda9e00701a9e20f02a980578052002df997e20f42a9e00741a9fd7bc3a8d48a01f0c0035fd6"),
    },
    {
        "description": "DIAG hookF: PlayerCharacter.<DelayEnableAI>.MoveNext -> log 600+enable at the _enableAi store",
        "offset": 0x0173F37C,
        "expected": bytes.fromhex("93820339"),  # strb w19, [x20, #0xe0]
        "replacement": bytes.fromhex("e8c6f897"),
    },
    {
        "description": "DIAG hookG: AIPlayerEngine.Start (after prologue) -> log 700",
        "offset": 0x01804F10,
        "expected": bytes.fromhex("347601f0"),  # adrp x20, #0x46cb000
        "replacement": bytes.fromhex("0ab0f597"),
    },
    {
        "description": "DIAG: cave H — log the return address (decimal RVA) of every NullReferenceException raise",
        "offset": 0x1570f60,
        "expected": bytes.fromhex("2eae7194f30300aa530000b5a08cf297e00313aae1031faa"),
        "replacement": bytes.fromhex("fd7bbfa9e0031e2af82cf997fd7bc1a8ff8300d19f8cf217"),
    },
    {
        "description": "DIAG hookH: il2cpp NRE throw helper entry (0x12141EC) -> b cave H (logs LR, re-runs displaced sub sp, jumps back)",
        "offset": 0x012141EC,
        "expected": bytes.fromhex("ff8300d1"),  # sub sp, sp, #0x20
        "replacement": bytes.fromhex("5d730d14"),
    },
    {
        "description": "DIAG: cave I — log LR + 3 frame-pointer return addresses of every il2cpp generic exception raise (0x121415C)",
        "offset": 0x1570f78,
        "expected": bytes.fromhex("940f7294f30300aa530000b59a8cf297e00313aae1031faa4a2d079460000036e00700323f000014800240f9089c44398800083608d840b9480000356b18f297"),
        "replacement": bytes.fromhex("fd7bbca9e00701a9e20f02a9f45703a9e0031e2aef2cf997e02340f9ed2cf997e02740f9eb2cf997f45743a9e20f42a9e00741a9fd7bc4a8f30f1ef86b8cf217"),
    },
    {
        "description": "DIAG hookI: il2cpp generic raise entry -> b cave I (logs LR, re-runs displaced str x19, jumps back)",
        "offset": 0x0121415C,
        "expected": bytes.fromhex("f30f1ef8"),  # str x19, [sp, #-0x20]!
        "replacement": bytes.fromhex("87730d14"),
    },
    {
        "description": "DIAG: SetParamVelocity guard with logging (810 = Animator null, 811 + addr = Animator native dead); replaces the plain guard cave",
        "offset": 0x1570ff0,
        "expected": bytes.fromhex("080840f9a80000b4080940f9680000b4e80f1dfce90af917c0035fd6"),
        "replacement": bytes.fromhex("080840f9a80000b4090940f9090100b4e80f1dfce90af917fd7bbfa940658052ce2cf997fd7bc1a8c0035fd6fd7bbea9e80b00f960658052c82cf997e80b40f9e003082ac52cf997fd7bc2a8c0035fd6"),
    },
    {
        "description": "DIAG: cave L — log 820, animator addr, PlayerAnimator addr at CharacterAnimatorBase.Initialize store",
        "offset": 0x1571040,
        "expected": bytes.fromhex("e00313aae1031faa142d07941f04007121020054487301f0086d44f9000140f9089c443988000836"),
        "replacement": bytes.fromhex("fd7bbfa980668052c02cf997e003142abe2cf997e003132abc2cf997fd7bc1a8740a00f9c0035fd6"),
    },
    {
        "description": "DIAG hookL: CharacterAnimatorBase.Initialize `str x20,[x19,#0x10]` -> bl cave L",
        "offset": 0x016B55A0,
        "expected": bytes.fromhex("740a00f9"),
        "replacement": bytes.fromhex("a8eefa97"),
    },
    {
        "description": "DIAG: cave M — log 830, object addr, caller LR at UnityEngine.Object.Destroy entry",
        "offset": 0x1571068,
        "expected": bytes.fromhex("08d840b9480000353c18f297e0031faaab1f0194e1031faabc6702941f000072a80080520005881a02000014e0031f2afd7b41a9f44fc2a8"),
        "replacement": bytes.fromhex("fd7bbda9e00701a9e20f02a9c0678052b42cf997e00b40f9b22cf997e00740f9b02cf997e20f42a9e00741a9fd7bc3a8f44fbea945fa3914"),
    },
    {
        "description": "DIAG hookM: UnityEngine.Object.Destroy(Object) entry -> b cave M",
        "offset": 0x023EF9AC,
        "expected": bytes.fromhex("f44fbea9"),
        "replacement": bytes.fromhex("af05c617"),
    },
    {
        "description": "DIAG: region C caves in dead body of GameReadyScene.GetGameReadyAnimationClip (900 ExecuteUpdate, 901 Execute, 902 UpdateTarget, 903 SetCurrentTarget)",
        "offset": 0x176030c,
        "expected": bytes.fromhex("fd7b02a9fd830091537b01f068e25239f40301aae20f00b9e80000376867019008c545f9000140b9b726ea97e803003268e21239a86601f008b545f9000140f9e30eeb97e1031faaf30300aa4b146794740000b5e0031faaa2cfea97e00314aae1031faa4a136794f40300aa730000b5e0031faa9bcfea97e00313aae10314aae2031faa80146794686801b0084940f9e0330091e2031faa010140f95a581794"),
        "replacement": bytes.fromhex("fd7bbda9e00701a9e20f02a9807080520b70f197e20f42a9e00741a9fd7bc3a8f30300aac0035fd6fd7bbda9e00701a9e20f02a9a07080520170f197e20f42a9e00741a9fd7bc3a8f30300aac0035fd6fd7bbda9e00701a9e20f02a9c0708052f76ff197e20f42a9e00741a9fd7bc3a8882e6b39c0035fd6fd7bbda9e00701a9e20f02a9e0708052ed6ff197e20f42a9e00741a9fd7bc3a8f40301aac0035fd6"),
    },
    {
        "description": "DIAG hook: AIPlayerEngine.ExecuteUpdate -> log 900",
        "offset": 0x018049e8,
        "expected": bytes.fromhex("f30300aa"),
        "replacement": bytes.fromhex("496efd97"),
    },
    {
        "description": "DIAG hook: AIPlayerEngine.Execute -> log 901",
        "offset": 0x01804e10,
        "expected": bytes.fromhex("f30300aa"),
        "replacement": bytes.fromhex("496dfd97"),
    },
    {
        "description": "DIAG hook: AIPlayerEngine.UpdateTarget -> log 902",
        "offset": 0x01807170,
        "expected": bytes.fromhex("882e6b39"),
        "replacement": bytes.fromhex("7b64fd97"),
    },
    {
        "description": "DIAG hook: AIPlayerEngine.SetCurrentTarget -> log 903",
        "offset": 0x01806834,
        "expected": bytes.fromhex("f40301aa"),
        "replacement": bytes.fromhex("d466fd97"),
    },
    {
        "description": "DIAG: region C (cont.) caves — 921 WaitForWarpOut, 922 ApplyCancelWarp, 923 ApplyWarp",
        "offset": 0x17603ac,
        "expected": bytes.fromhex("486801b0080540f9e10300aae2031faa080140f9e00308aae34f1894f40300aa730000b5e0031faa86cfea97e00313aae10314aae2031faa88146794a86601d0084146f9f30300aa080140f9099d4439a900083609d940b969000035e00308aa555bea97e00313aae1031faae2031faac5323294e00313aafd7b42a9f44f41a9ffc30091c0035fd6"),
        "replacement": bytes.fromhex("fd7bbda9e00701a9e20f02a920738052e36ff197e20f42a9e00741a9fd7bc3a8f30300aac0035fd6fd7bbda9e00701a9e20f02a940738052d96ff197e20f42a9e00741a9fd7bc3a8f30300aac0035fd6fd7bb9a9e00701a9e20f02a9e08701ade28f02ad60738052cd6ff197e28f42ade08741ade20f42a9e00741a9fd7bc7a828876039c0035fd6"),
    },
    {
        "description": "DIAG hook: WaitForWarpOut -> log 921",
        "offset": 0x0180589c,
        "expected": bytes.fromhex("f30300aa"),
        "replacement": bytes.fromhex("c46afd97"),
    },
    {
        "description": "DIAG hook: ApplyCancelWarp -> log 922",
        "offset": 0x013e4a20,
        "expected": bytes.fromhex("f30300aa"),
        "replacement": bytes.fromhex("6dee0d94"),
    },
    {
        "description": "DIAG hook: ApplyWarp -> log 923",
        "offset": 0x013e45b8,
        "expected": bytes.fromhex("28876039"),
        "replacement": bytes.fromhex("91ef0d94"),
    },
    {
        "description": "DIAG: cave in ReplayManager.get_ReplayMode body tail — 940+PlayerStateType at PlayerCharacter.SetState",
        "offset": 0x17736a8,
        "expected": bytes.fromhex("600240f9089c4439a800083608d840b968000035a90eea97600240f9085c40f9fd7b41a9000140b9"),
        "replacement": bytes.fromhex("fd7bbda9e00701a9e20f02a920b00e112423f197e20f42a9e00741a9fd7bc3a8c8025e39c0035fd6"),
    },
    {
        "description": "DIAG hook: PlayerCharacter.SetState -> log 940+type",
        "offset": 0x013c4a74,
        "expected": bytes.fromhex("c8025e39"),
        "replacement": bytes.fromhex("0dbb0e94"),
    },
    {
        "description": "DIAG: region D caves in dead body of LoadManager.LoadDeckSummonModel (950+routeCount UpdateRoute, 951 SearchRoute, 952 RouteJunctionTable.InitTable)",
        "offset": 0x16e6cc0,
        "expected": bytes.fromhex("fd430191ffc302d1337f01b068664239a0c310b8e8000037886d01f008ed46f9000140b94b0cec97e80300326866023900e4006fe84300d1bf7f37a9bf7f34a9a0033cada0833aada80311f81f010091c86701d0083d45f9000140f96ff4ec97286b01f0086d44f9f50300aa010140f915675394c86b01d008e144f9000140f9089c44398800083608d840b9480000350441ec97e0031faab0d66b94f40300aa540000b522b5ec97e00314aae1031faa1e386c94f40300aa540000b51cb5ec97e00314aae1031faa42960694fb6701b0b96701f0d36601d07b1b47f9392f45f973c241f9f60300aaf4031faa"),
        "replacement": bytes.fromhex("fd7bb5a9e00701a9e20f02a9e41703a9e61f04a9e08702ade28f03ada10000b4201840b900d80e119855f39703000014c07680529555f397e28f43ade08742ade61f44a9e41743a9e20f42a9e00741a9fd7bcba8f30301aac0035fd6fd7bb5a9e00701a9e20f02a9e41703a9e61f04a9e08702ade28f03ade07680528355f397e28f43ade08742ade61f44a9e41743a9e20f42a9e00741a9fd7bcba8f80304aac0035fd6fd7bb5a9e00701a9e20f02a9e41703a9e61f04a9e08702ade28f03ad007780527155f397e28f43ade08742ade61f44a9e41743a9e20f42a9e00741a9fd7bcba8c81a4639c0035fd6"),
    },
    {
        "description": "DIAG hook: UpdateRoute -> region D",
        "offset": 0x01807650,
        "expected": bytes.fromhex("f30301aa"),
        "replacement": bytes.fromhex("9c7dfb97"),
    },
    {
        "description": "DIAG hook: SearchRoute -> region D",
        "offset": 0x01701C9C,
        "expected": bytes.fromhex("f80304aa"),
        "replacement": bytes.fromhex("2094ff97"),
    },
    {
        "description": "DIAG hook: InitTable -> region D",
        "offset": 0x016FE480,
        "expected": bytes.fromhex("c81a4639"),
        "replacement": bytes.fromhex("39a2ff97"),
    },
    {
        "description": "DIAG: region D (cont.) — 970+flags set_AutoMoveFlags, 971 PerformAttack, 972 PerformGetScore, 973 PerformMove",
        "offset": 0x16e6db0,
        "expected": bytes.fromhex("1a008012b30000149f03086b977f4093a300005480b8ec97e1031faae2031faae3b4ec97c80e178b001140f9001500b4e1031faa9b47f397f70300aa971400b4610340f9e00317aaff1055941f100071e1130054086a01d0084544f9e00317aa010140f9a8a303d1fd135594a083d23ca183d13ca1033cad210340f9a00302d169281694000d0036610240f9a00302d1f2281694a86601d0081940f9a08317f8080140f9e00308aa49e74894f70300aa770000b5e0031faae1b4ec97e00317aae1031faa29cb0294f70300aa286801d0089d43f9010140f9a02302d1fa9f5194f803002a770000b5e0031faad4b4ec97286c019008d941f9020140f9e00317aae103182aee260d94f70300aa77fbffb4a86601d0081940f9000140f92ce74894"),
        "replacement": bytes.fromhex("fd7bb5a9e00701a9e20f02a9e41703a9e61f04a9e08702ade28f03ad20280f115e55f397e28f43ade08742ade61f44a9e41743a9e20f42a9e00741a9fd7bcba8f303012ac0035fd6fd7bb5a9e00701a9e20f02a9e41703a9e61f04a9e08702ade28f03ad607980524c55f397e28f43ade08742ade61f44a9e41743a9e20f42a9e00741a9fd7bcba8f30301aac0035fd6fd7bb5a9e00701a9e20f02a9e41703a9e61f04a9e08702ade28f03ad807980523a55f397e28f43ade08742ade61f44a9e41743a9e20f42a9e00741a9fd7bcba8f40300aac0035fd6fd7bb5a9e00701a9e20f02a9e41703a9e61f04a9e08702ade28f03ada07980522855f397e28f43ade08742ade61f44a9e41743a9e20f42a9e00741a9fd7bcba8c8da5c39c0035fd6"),
    },
    {
        "description": "DIAG hook: PlayerCharacter.set_AutoMoveFlags(970+flags)",
        "offset": 0x013BF2B8,
        "expected": bytes.fromhex("f303012a"),
        "replacement": bytes.fromhex("be9e0c94"),
    },
    {
        "description": "DIAG hook: PlayerCharacter.PerformAttack",
        "offset": 0x013BEF78,
        "expected": bytes.fromhex("f30301aa"),
        "replacement": bytes.fromhex("a09f0c94"),
    },
    {
        "description": "DIAG hook: PlayerCharacter.PerformGetScore",
        "offset": 0x013C0200,
        "expected": bytes.fromhex("f40300aa"),
        "replacement": bytes.fromhex("109b0c94"),
    },
    {
        "description": "DIAG hook: PlayerCharacter.PerformMove",
        "offset": 0x013BF870,
        "expected": bytes.fromhex("c8da5c39"),
        "replacement": bytes.fromhex("869d0c94"),
    },
    {
        "description": "DIAG: region E (keystone-generated, scripts/re/mkcave.py) in dead body of LoadManager.LoadDeckSummonModel: safe LOG helper that preserves x0-x18/q0-q7/q16-q31 (the region A helper at 0x13BC348 branches here; without it caves clobbered x8 between a method's metadata-init flag load and its tbnz and randomly skipped il2cpp method init -> SIGSEGV fault addr 0x127), plus PerformMove destination-selection trace caves",
        "offset": 0x16e6ed0,
        "expected": bytes.fromhex("f80300aa780000b5e0031faac4b4ec97e00318aae1031faa94cb0294f80300aae00317aae1031faa0715fd97f703002a780000b5e0031faab9b4ec97686a01b0087d45f9020140f9e00318aae103172ad3260d94f70300aa17f8ffb4750000b5e0031faaaeb4ec97086d01d008fd43f9020140f9e00315aae10317aae26a5394c0020036750000b5e0031faaa4b4ec97c869019008c940f9020140f9e00315aae10317aa7e695394f803002a750000b5e0031faa9ab4ec97e86801f008d143f902070011030140f9e00315aae10317aab0695394a1ffff17750000b5e0031faa8fb4ec97286a01b0086145f9030140f9e2030032e00315aae10317aabb69539496ffff17a80351f85a070011e91a805209d93ab8110000140b0000140a0000140900001408000014070000140600001405000014040000140300001402000014010000143f040071011800542dc0e797140040f90fbfe797086b01f008f542f9a00302d1010140f9762816945f07003120010054a80351f808d97ab81f5d0371a100005408008012087d9a4a5a03080b07000014d40000b4e00314aae1031faae2031faa3ab4ec97f4031faa9c070011760000b5e0031faa59b4ec97c81a40b99f03086b2be9ff54750000b5e0031faa53b4ec97a86601d0081544f9e00315aa010140f9a8a303d1836b5394a88353f8a083d23ca183d13c536a01d0196b01d0fc6801d01b6a01f0731246f939a340f99c6f47f97b0f41f9a80317f8a1833aad610240f9a0c302d17c4a1194a00a0036210340f9a0c302d10a4b1194880340f9a00734a9e00308aa70f3ec97f50300aae00315aae1031faaeb813794610340f9a00303d181a45194f60300aa760000b5e0031faa2ab4ec97e00316aae1031faa25620594f603002a750000b5e0031faa23b4ec97b61200b9a86601b0081940f9000140f982e64894f60300aa760000b5e0031faa1ab4ec97e00316aae1031faa0acb0294f60300aab71240b9760000b5e0031faa12b4ec97486c01f0080540f9020140f9e00316aae103172a2c260d94f60300aa760000b5e0031faa08b4ec97e00316aae1031faaaeacfd97a01600b9886701b0085d44f9010140f9a00303d154a45194a01a00b9486d01d0b65e4229081940f9000140f934f3ec97f80300aae86601f008a944f9020140f9e00318aae10315aae3031faad8682b94a0c350b8e1031faa29fafc97e303002ae003162ae103172ae20318aa42f0ff97a9ffff17a90351f85a0700116830805228d93ab8140000140e000014"),
        "replacement": bytes.fromhex("ff0309d1fd7b00a9e00701a9e20f02a9e41703a9e61f04a9e82705a9ea2f06a9ec3707a9ee3f08a9f04709a9f25300f9e08705ade28f06ade49707ade69f08adf0c709adf2cf0aadf4d70badf6df0cadf8e70dadfaef0eadfcf70fadfeff10ade303002a6000805281030010a2030010ccbce797feff50adfcf74fadfaef4eadf8e74dadf6df4cadf4d74badf2cf4aadf0c749ade69f48ade49747ade28f46ade08745adf25340f9f04749a9ee3f48a9ec3747a9ea2f46a9e82745a9e61f44a9e41743a9e20f42a9e00741a9fd7b40a9ff030991c0035fd64b46444941470000763d256400000000ff0309d1fd7b00a9e00701a9e20f02a9e41703a9e61f04a9e82705a9ea2f06a9ec3707a9ee3f08a9f04709a9f25300f9e08705ade28f06ade49707ade69f08adf0c709adf2cf0aadf4d70badf6df0cadf8e70dadfaef0eadfcf70fadfeff10ad00a00f11cb54f397feff50adfcf74fadfaef4eadf8e74dadf6df4cadf4d74badf2cf4aadf0c749ade69f48ade49747ade28f46ade08745adf25340f9f04749a9ee3f48a9ec3747a9ea2f46a9e82745a9e61f44a9e41743a9e20f42a9e00741a9fd7b40a9ff030991e803002ac0035fd6ff0309d1fd7b00a9e00701a9e20f02a9e41703a9e61f04a9e82705a9ea2f06a9ec3707a9ee3f08a9f04709a9f25300f9e08705ade28f06ade49707ade69f08adf0c709adf2cf0aadf4d70badf6df0cadf8e70dadfaef0eadfcf70fadfeff10ad60e640b9003011119654f397e01340b9005014119354f39760ea40b99154f397feff50adfcf74fadfaef4eadf8e74dadf6df4cadf4d74badf2cf4aadf0c749ade69f48ade49747ade28f46ade08745adf25340f9f04749a9ee3f48a9ec3747a9ea2f46a9e82745a9e61f44a9e41743a9e20f42a9e00741a9fd7b40a9ff03099168864339c0035fd6ff0309d1fd7b00a9e00701a9e20f02a9e41703a9e61f04a9e82705a9ea2f06a9ec3707a9ee3f08a9f04709a9f25300f9e08705ade28f06ade49707ade69f08adf0c709adf2cf0aadf4d70badf6df0cadf8e70dadfaef0eadfcf70fadfeff10ad0000381e00401f115c54f3970109281e62092b1e2128221e82092c1e2128221e21c0211e2000381e00e02e115354f397feff50adfcf74fadfaef4eadf8e74dadf6df4cadf4d74badf2cf4aadf0c749ade69f48ade49747ade28f46ade08745adf25340f9f04749a9ee3f48a9ec3747a9ea2f46a9e82745a9e61f44a9e41743a9e20f42a9e00741a9fd7b40a9ff030991031ca04ec0035fd6"),
    },
    {
        "description": "DIAG hook: PerformMove after get_TargetActive -> 1000+active",
        "offset": 0x13bf8b4,
        "expected": bytes.fromhex("e803002a"),
        "replacement": bytes.fromhex("c19d0c94"),
    },
    {
        "description": "DIAG hook: PerformMove after route count check -> 1100+AIOption, 1300+count, raw _aiAutoMoveDefaultGoalDistance bits",
        "offset": 0x13bf8f4,
        "expected": bytes.fromhex("68864339"),
        "replacement": bytes.fromhex("e59d0c94"),
    },
    {
        "description": "DIAG hook: PerformMove per segment -> 2000+int(goalDistance), 3000+int(|segment|)",
        "offset": 0x13bfa10,
        "expected": bytes.fromhex("031ca04e"),
        "replacement": bytes.fromhex("d89d0c94"),
    },
    {
        "description": "DIAG: region E (cont.) minimal caves (safe LOG preserves everything) — 38xx SubState, 39xx auto-move flags consumed, 399x UpdateAutoSmoothMove result",
        "offset": 0x16e7268,
        "expected": bytes.fromhex("0d0000140c0000140b0000140a0000140900001408000014070000140600001405000014040000140300001402000014010000143f040071c10300548bbfe797140040f96dbee797486d0190080545f9a0c302d1010140f99f4a11945f07003140020054340100b4"),
        "replacement": bytes.fromhex("fd7bbea9e00b00f900613b113554f397e00b40f9fd7bc2a81f150071c0035fd6fd7bbea9e00b00f9609a41b900f03c112c54f397e00b40f9fd7bc2a8749a41b9c0035fd6fd7bbea9e00b00f91f0000f1e0079f1a00583e112254f397e00b40f9fd7bc2a8b8f00314"),
    },
    {
        "description": "DIAG hook: PlayerStateNormal.UpdateAction -> 3800+SubState each tick",
        "offset": 0x17e14e4,
        "expected": bytes.fromhex("1f150071"),
        "replacement": bytes.fromhex("6117fc97"),
    },
    {
        "description": "DIAG hook: PlayerStateNormal.InputActionFly -> 3900+consumed CurrentAutoMoveFlags",
        "offset": 0x17e20a4,
        "expected": bytes.fromhex("749a41b9"),
        "replacement": bytes.fromhex("7914fc97"),
    },
    {
        "description": "DIAG hook: InputActionFly after UpdateAutoSmoothMove -> 3990+(result!=null)",
        "offset": 0x17e3768,
        "expected": bytes.fromhex("91ffff17"),
        "replacement": bytes.fromhex("d10efc97"),
    },
    {
        "description": "DIAG: region E (cont. 2) minimal caves — 3700 UpdateFly reached CanTakeOff, 3701 CanTakeOff true",
        "offset": 0x16e72d0,
        "expected": bytes.fromhex("a80351f808d97ab81f0d0671a0000054e00314aae1031faae2031faa9cb3ec97bf4301d1fd7b45a9f44f44a9f65743a9f85f42a9fa6741a9fc6fc6a8c0035fd6"),
        "replacement": bytes.fromhex("fd7bbea9e00b00f980ce81521b54f397e00b40f9fd7bc2a8aa2e032dc0035fd6fd7bbea9e00b00f9a0ce81521354f397e00b40f9fd7bc2a8e00313aac0035fd6"),
    },
    {
        "description": "DIAG hook: PlayerStateNormal.UpdateFly before CanTakeOff -> 3700",
        "offset": 0x17e48b4,
        "expected": bytes.fromhex("aa2e032d"),
        "replacement": bytes.fromhex("870afc97"),
    },
    {
        "description": "DIAG hook: UpdateFly CanTakeOff true -> 3701 (then SetSubStateTakeOff)",
        "offset": 0x17e48c0,
        "expected": bytes.fromhex("e00313aa"),
        "replacement": bytes.fromhex("8c0afc97"),
    },
    {
        "description": "DIAG only: stub LoadDeckSummonModel (region D/E caves live in its body; production builds keep it so disc pets load)",
        "offset": 0x016E6CA8,
        "expected": bytes.fromhex("fc6fbaa9"),
        "replacement": bytes.fromhex("c0035fd6"),  # ret
    },
    {
        "description": "DIAG: region F minimal caves in dead body of HomeSummonModelController.UnloadModel (after the production PlayIdle cave) — 6200 PlayerStateSkill.End, 6300/6301 CharacterAnimatorBase.CrossFade(string/hash), 6210 PlayerStateNormal.BeginAction, 6220 PlayerStateSkill.SetStateNormal",
        "offset": 0x159dfd0,
        "expected": bytes.fromhex("080540f9e00315aae103142a020140f9a34a1294f50300aa550000b580d8f197e00315aae1031faad9d40294e103002ae003142ae2031faa59150594d5740190b54246f9742640f9a00240f9089c44398800083608d840b9480000354d64f197e00314aae1031faae2031faa55473994c0020036732640f9730000b5e0031faa67d8f197e00313aae1031faa457a1394a80240f9f30300aa099d4439a9000836"),
        "replacement": bytes.fromhex("fd7bbea9e00b00f900078352db78f897e00b40f9fd7bc2a8f30300aac0035fd6fd7bbea9e00b00f980138352d378f897e00b40f9fd7bc2a8fd030191c0035fd6fd7bbea9e00b00f9a0138352cb78f897e00b40f9fd7bc2a8fd030191c0035fd6fd7bbea9e00b00f940088352c378f897e00b40f9fd7bc2a8fd430191c0035fd6fd7bbea9e00b00f980098352bb78f897e00b40f9fd7bc2a8fdc30191c0035fd6"),
    },
    {"description": "DIAG hook: PlayerStateSkill.End -> 6200", "offset": 0x17f8b80, "expected": bytes.fromhex("f30300aa"), "replacement": bytes.fromhex("1495f697")},
    {"description": "DIAG hook: CharacterAnimatorBase.CrossFade(string) -> 6300", "offset": 0x16b55f0, "expected": bytes.fromhex("fd030191"), "replacement": bytes.fromhex("80a2fb97")},
    {"description": "DIAG hook: CharacterAnimatorBase.CrossFade(hash) -> 6301", "offset": 0x16b5a48, "expected": bytes.fromhex("fd030191"), "replacement": bytes.fromhex("72a1fb97")},
    {"description": "DIAG hook: PlayerStateNormal.BeginAction -> 6210", "offset": 0x17e04f8, "expected": bytes.fromhex("fd430191"), "replacement": bytes.fromhex("cef6f697")},
    {"description": "DIAG hook: PlayerStateSkill.SetStateNormal -> 6220", "offset": 0x17f60e0, "expected": bytes.fromhex("fdc30191"), "replacement": bytes.fromhex("dc9ff697")},
    {"description": "DIAG cave: PlayerAnimator.PlayIdle entry -> 6250", "offset": 0x159e070, "expected": bytes.fromhex("09d940b969000035e00308aa3964f197e00313aafd7b42a9f44f41a9e1031faa"), "replacement": bytes.fromhex("fd7bbea9e00b00f9400d8352b378f897e00b40f9fd7bc2a8a80a5a39c0035fd6")},
    {"description": "DIAG hook: PlayerAnimator.PlayIdle entry -> 6250", "offset": 0x13ae9c4, "expected": bytes.fromhex("a80a5a39"), "replacement": bytes.fromhex("abbd0794")},
    {"description": "DIAG cave: PlayerAnimator.PlayIdle past bind-condition check -> 6251", "offset": 0x17332d4, "expected": bytes.fromhex("e0031faac583eb97e00314aafd7b42a9f44f41a9e10315aae2031faaf50743f8"), "replacement": bytes.fromhex("fd7bbea9e00b00f9600d83521a24f297e00b40f9fd7bc2a8b57e47f9c0035fd6")},
    {"description": "DIAG hook: PlayerAnimator.PlayIdle past bind-condition check -> 6251", "offset": 0x13aea18, "expected": bytes.fromhex("b57e47f9"), "replacement": bytes.fromhex("2f120e94")},
    {"description": "DIAG: region G minimal caves in dead body of stubbed GameManager.<BeginAsync>b__3 — 6420/6421 Weapon.Initialize attach, 6410 NunchakuAction.Initialize, 6411 NunchakuAction.OnManagedLateUpdate", "offset": 0x1579a40, "expected": bytes.fromhex("fd430091948a01b088c25739f30300aae8000037487201b008ad47f9000140b9ecc0f197e803003288c21739740a40f9740000b5e0031faadd69f297e00314aabdd2ff9760000036e8031f2a0b000014730a40f9730000b5e0031faad469f29708720190081144f9e00313aa010140f941ab129408000052fd7b41a900010012"), "replacement": bytes.fromhex("fd7bbea9e00b00f9802283523f0af997e00b40f9fd7bc2a8f90300aac0035fd6fd7bbea9e00b00f9a0228352370af997e00b40f9fd7bc2a87c2a00f9c0035fd6fd7bbea9e00b00f9402183522f0af997e00b40f9fd7bc2a8fd430191c0035fd6fd7bbea9e00b00f960218352270af997e00b40f9fd7bc2a8f30300aac0035fd6")},
    {"description": "DIAG hook: Weapon.Initialize: weapon parented to a bone -> 6420", "offset": 0x1818e64, "expected": bytes.fromhex("f90300aa"), "replacement": bytes.fromhex("f782f597")},
    {"description": "DIAG hook: Weapon.Initialize: after attach (parent or not) -> 6421", "offset": 0x1818e84, "expected": bytes.fromhex("7c2a00f9"), "replacement": bytes.fromhex("f782f597")},
    {"description": "DIAG hook: NunchakuAction.Initialize -> 6410", "offset": 0x13f8dfc, "expected": bytes.fromhex("fd430191"), "replacement": bytes.fromhex("21030694")},
    {"description": "DIAG hook: NunchakuAction.OnManagedLateUpdate -> 6411", "offset": 0x13f9268, "expected": bytes.fromhex("f30300aa"), "replacement": bytes.fromhex("0e020694")},
    # ---- END DIAGNOSTIC ----
] if os.environ.get("KF_DIAG") == "1" else []

NATIVE_PATCHES: dict[str, list[dict[str, object]]] = {
    "arm64-v8a": [
        {
            "description": "force HTTP for direct server access",
            "offset": 0x31B5024,
            "expected": bytes.fromhex("28118a9a"),  # pristine csel x8, x9, x10, ne; a pre-patched base (e8030aaa) takes the alreadyPatched path
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
            "description": "bridge matchmaking completion to offline battle room and launch GameScene",
            "offset": 0x13EF4C0,
            "expected": bytes.fromhex("687e019008a141f9000140f947c554948002003657820190f78243f9e00240f9d4c45494f40300aa540000b5"),
            "replacement": bytes.fromhex("e0031f2a01a68e52e2031faadca01394fd7b43a9f44f42a9f65741a9f70744f8c0035fd61f2003d51f2003d5"),
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
            "description": "force MatchingManager.IsRoomLocalPlayerMaster to true",
            "offset": 0x14E16AC,
            "expected": bytes.fromhex("e0031faa75d50f14"),  # mov x0, xzr; b #0x18d6c84
            "replacement": bytes.fromhex("20008052c0035fd6"),  # mov w0, #1; ret
        },
        {
            "description": "store battleRuleInfo and battleInfo into ArchiveData and launch ChangeGameSceneSync in ApplyBattleProperties",
            "offset": 0x17A2148,
            "expected": bytes.fromhex("ffc301d1fc6f01a9fa6702a9f85f03a9f65704a9f44f05a9fd7b06a9fd830191557901b0a87a5d39f40302aaf30301aa"),
            "replacement": bytes.fromhex("f44fbea9fd7b01a9f30301aaf40302aae00314aa94a90394aee96894131801f9141c01f9fd7b41a9f44fc2a8be03f517"),
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
            "description": "bypass DiscSkill InvalidCastException in SkillRangeValidator.CreateValidator",
            "offset": 0x18436D0,
            "expected": bytes.fromhex("002140f9"),
            "replacement": bytes.fromhex("2b000014"),
        },
        {
            "description": "bypass KickerSkill InvalidCastException in SkillRangeValidator.CreateValidator",
            "offset": 0x1843740,
            "expected": bytes.fromhex("002140f9"),
            "replacement": bytes.fromhex("0f000014"),
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
            "description": "bypass IsMatched check in NormalMatchingController.BattleStart to allow local battle setup",
            "offset": 0x13EB238,
            "expected": bytes.fromhex("00080037"),
            "replacement": bytes.fromhex("1f2003d5"),
        },
        {
            "description": "bypass IsRoomLocalPlayerMaster check in NormalMatchingController.BattleStart to allow local battle setup",
            "offset": 0x13EB25C,
            "expected": bytes.fromhex("e0060036"),
            "replacement": bytes.fromhex("1f2003d5"),
        },
        {
            "description": "bypass premature scene change in CallbackRoomPropertiesUpdate on status 3",
            "offset": 0x13EB720,
            "expected": bytes.fromhex("400a0054"),
            "replacement": bytes.fromhex("1f2003d5"),
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
            "description": "force GameManager.<BeginAsync>b__1 (!IsCreatedSceneObject) to return false; b__2/b__5 (!IsRoomStateComplete 4/5) are deliberately NOT forced: IsRoomStateComplete calls this.UpdateState(), which is what advances RoomState (None->PreLoaded->CreatedObject) before ManagedUpdate starts ticking; without it RoomState never reaches Playing and RoomStartTime/IsGameStarted/AI never start",
            "offset": 0x01579940,
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
            "description": "cave: CharacterAnimatorBase.IsCurrentState -> false only when the Animator is null/destroyed, else run the original (the old unconditional stub broke dash attacks, attack motions and state transitions for every kicker)",
            "offset": 0x1733284,
            "expected": bytes.fromhex("e00314aae103152ae3031faadb1e0294f40300aa741e00f968650190083940f9000140f9"),
            "replacement": bytes.fromhex("080840f9c80000b4080940f9880000b4ff4302d1f53300f9b20afe17e0031f2ac0035fd6"),
        },
        {
            "description": "CharacterAnimatorBase.IsCurrentState entry -> b animator-guard cave",
            "offset": 0x16b5d5c,
            "expected": bytes.fromhex("ff4302d1f53300f9"),
            "replacement": bytes.fromhex("4af501141f2003d5"),
        },
        {
            "description": "cave: CharacterAnimatorBase.IsInTransition -> false only when the Animator is null/destroyed, else run the original (the old unconditional stub broke dash attacks, attack motions and state transitions for every kicker)",
            "offset": 0x1733260,
            "expected": bytes.fromhex("e383eb97e00315aae1031faa73066b94f503002a740000b5e0031faadc83eb97e2031f32"),
            "replacement": bytes.fromhex("080840f9c80000b4080940f9880000b4f44fbea9fd7b01a9ad0afe17e0031f2ac0035fd6"),
        },
        {
            "description": "CharacterAnimatorBase.IsInTransition entry -> b animator-guard cave",
            "offset": 0x16b5d24,
            "expected": bytes.fromhex("f44fbea9fd7b01a9"),
            "replacement": bytes.fromhex("4ff501141f2003d5"),
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
            "description": "PlayerStateNormal.UpdateAction: replace get_Player null-throw with a null-guard on the owning PlayerCharacter; no PlayerType gate (bots/AI need UpdateAction to move; the per-site null guards below cover their missing Photon objects)",
            "offset": 0x017E13C4,
            "expected": bytes.fromhex("e00313aae1031faa537e0394f40300aa540000b585cbe897"),  # mov x0, x19; mov x1, xzr; bl get_Player; mov x20, x0; cbnz x20, #0x17e13dc; bl throw
            "replacement": bytes.fromhex("680a40f9683000b41f2003d51f2003d51f2003d5f40308aa"),  # ldr x8, [x19, #0x10]; cbz x8, #0x17e19d4; nop; nop; nop; mov x20, x8  (PlayerType gate lifted: AI kickers must run UpdateAction too)
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
        # PlayerAnimator.IsBindMotionCondition used to be stubbed to `return true` (for dead bot animators); since
        # PlayIdle/PlayMove bail out when it is true, NO kicker ever played its idle again after a skill (pose stuck
        # until another action played). Guard instead: true only when the Animator is null/destroyed.
        {
            "description": "cave: PlayerAnimator.IsBindMotionCondition -> true only when the Animator is null/destroyed, else run the original (in the dead body of stubbed TitleView.SetAllButtonActive)",
            "offset": 0x31C4980,
            "expected": bytes.fromhex("752a40f9f403012a750000b5e0031faa173e819794020012e00315aae103142ae2031faa"),
            "replacement": bytes.fromhex("080840f9c80000b4080940f9880000b4f30f1ef8fd7b01a940a8871720008052c0035fd6"),
        },
        {
            "description": "PlayerAnimator.IsBindMotionCondition entry -> b animator-guard cave",
            "offset": 0x013AEA90,
            "expected": bytes.fromhex("f30f1ef8fd7b01a9"),
            "replacement": bytes.fromhex("bc5778141f2003d5"),
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
        # Offline battle start: the ponytail patches skip the GameReadyScene timeline, so its end event
        # (OnEndCutScene -> OnCompleted -> _onCompleted -> WaitReadiedAsync -> PlayerState=Readied) never fires
        # and GameManager.UpdateState can never move RoomState CreatedObject(5) -> Playing(6); RoomStartTime is
        # then never written, IsGameStarted stays false, the clock sits at 3:00 and the AI never runs.
        # Re-emit that completion at countdown start (GameStartAnimation.PlayGoAnimation). In this patched flow
        # OnEndReadyGoAnimation publishes Playing(4) ~0.2 s BEFORE the async WaitReadiedAsync lands Readied(3), so
        # the final gate in UpdateState (PlayerState == Playing) is relaxed to >= Readied below. calls GameManager.CompleteGameReady(), which is GetSubScene<GameReadyScene>()
        # -> Complete() -> OnCompleted() (idempotent; its teardown also restores the in-game camera/HUD). Readied then lands before OnEndReadyGoAnimation publishes
        # Playing, which is the original ordering. Cave lives in the dead body of GameManager.GetMenuType.
        {
            "description": "cave: fetch SingletonMonoBehaviour<GameManager>.Instance and call GameManager.CompleteGameReady (-> GameReadyScene.Complete -> OnCompleted: publishes PlayerState Readied AND restores camera state/DOF/canvas), then run displaced `ldr w8,[x19,#0xb0]`",
            "offset": 0x01570EF8,
            "expected": bytes.fromhex("e0031faa5717fc9760000036e0031f3264000014487801d008e142f9000140f9089c4439"),
            "replacement": bytes.fromhex("fd7bbfa9687301b0087941f9000140f94abe4e94fb060094fd7bc1a868b240b9c0035fd6"),
        },
        {
            "description": "GameStartAnimation.PlayGoAnimation: emit GameReadyScene completion (PlayerState Readied) at countdown start",
            "offset": 0x017630EC,
            "expected": bytes.fromhex("68b240b9"),  # ldr w8, [x19, #0xb0]
            "replacement": bytes.fromhex("8337f897"),  # bl #0x1570ef8
        },
        {
            "description": "GameManager.UpdateState case Playing: write RoomStartTime when local PlayerState >= Readied (was == Playing); offline the async Readied can overwrite Playing",
            "offset": 0x0156EB14,
            "expected": bytes.fromhex("1f10007121050054"),  # cmp w0, #4; b.ne #0x156ebbc
            "replacement": bytes.fromhex("1f0c00712b050054"),  # cmp w0, #3; b.lt #0x156ebbc
        },
        # AI kickers in this offline flow have a PlayerAnimator whose Unity Animator is null/dead; every
        # PlayerStateNormal.UpdateAction then dies in Animator.SetFloat (NRE raised by libunity, ~40/s) and the
        # exception aborts ObjectManager.ManagedUpdate for the frame, starving every later manager (GameManager
        # never ticks -> no RoomStartTime). Guard the one direct Animator call on that path.
        {
            "description": "cave: PlayerAnimator.SetParamVelocity entry guard — return if Animator is null or its native m_CachedPtr is 0, else run displaced prologue insn and continue",
            "offset": 0x1570ff0,
            "expected": bytes.fromhex("60000036e0031e3228000014800240f9089c44398800083608d840b9"),
            "replacement": bytes.fromhex("080840f9a80000b4080940f9680000b4e80f1dfce90af917c0035fd6"),
        },
        {
            "description": "PlayerAnimator.SetParamVelocity: b guard cave (entry hook uses b, cave returns to caller or jumps back to +4)",
            "offset": 0x013B3BA4,
            "expected": bytes.fromhex("e80f1dfc"),  # str d8, [sp, #-0x30]!
            "replacement": bytes.fromhex("13f50614"),
        },
        # Offline ownership: CharacterBase.IsMine is photonView.IsMine, false for the AI kickers (their PhotonViews
        # belong to actors that do not exist). Online the master client owns AI players; offline the single client
        # must own everything, otherwise e.g. AcceptCancelWarp (`if (!IsMine) return`) never ends the bots' warp-in
        # and AIPlayerEngine.ManagedUpdate parks in WaitForWarpOut forever. Cave lives in the dead body of the stubbed
        # ReplayManager.get_ReplayMode.
        {
            "description": "cave: CharacterBase.IsMine -> return true when PhotonManager.IsOffline(), else run displaced prologue insn and continue",
            "offset": 0x1773678,
            "expected": bytes.fromhex("fd430091d37a019068325639e8000037286901d008f546f9000140b9dfd9e997e803003268321639336801f073e242f9"),
            "replacement": bytes.fromhex("fd7bbea9e00b00f9e0031faac68e0594e10b40f9fd7bc2a8600000b420008052c0035fd6e00301aaf44fbea9c70cfd17"),
        },
        {
            "description": "CharacterBase.IsMine entry -> b offline-ownership cave",
            "offset": 0x016B69BC,
            "expected": bytes.fromhex("f44fbea9"),  # stp x20, x19, [sp, #-0x20]!
            "replacement": bytes.fromhex("2ff30214"),
        },
        # AI locomotion offline. Two gates in PlayerStateNormal assume a human finger:
        #  1. CanTakeOff(): on the ground a kicker only lifts off when MoveInfo.IsMove && pitch <= -20 deg, i.e. after
        #     a swipe; the AI never produces that, so the bots stayed on the start pad. For EnableAI kickers return true.
        #  2. Acceleration(): while _dashRemainTime > 0 it takes the "dash" branch (acceleration 0 / brake) and relies on
        #     UpdateDash() to drive velocity, but UpdateDash only runs under InputManager.IsCurrentState(3) (touch) and
        #     only while IsMove — the bots ended a dash with velocity 0 and _dashRemainTime stuck > 0, so acceleration
        #     stayed 0 forever. For EnableAI kickers always take the normal branch (accelerate to CalcMaxSpeed).
        # Both caves live in the dead body of the stubbed HomeChatNotificationView.OnCompleteChatSetup (0x17331C4..0x17332F8,
        # nothing branches into it). Generated with scripts/re/mkcave.py; x19 == this in both hooked methods.
        {
            "description": "cave: PlayerStateNormal.CanTakeOff ground branch -> return Player.EnableAI instead of false",
            "offset": 0x17331D0,
            "expected": bytes.fromhex("d47c0190883e4d39f30300aae8000037e86601f008c942f9000140b909dbea97"),
            "replacement": bytes.fromhex("fd7bbfa9e00313aae1031faacf360694e1031faa8b2cf297fd7bc1a8c0035fd6"),
        },
        {
            "description": "PlayerStateNormal.CanTakeOff `mov w0, wzr` (ground, not moving/pitched) -> bl EnableAI cave",
            "offset": 0x17E6FFC,
            "expected": bytes.fromhex("e0031f2a"),
            "replacement": bytes.fromhex("7530fd97"),
        },
        {
            "description": "cave: PlayerStateNormal.Acceleration -> if Player.EnableAI skip the dash branch, else redo `fcmp _dashRemainTime, #0; b.le`",
            "offset": 0x17331F0,
            "expected": bytes.fromhex("e8030032883e0d39686901b008e144f9000140f9089c44398800083608d840b948000035d30feb97e0031faa7fa56a94f40300aa540000b5"),
            "replacement": bytes.fromhex("fd7bbfa9e00313aae1031faac7360694e1031faa832cf297fd7bc1a8e803002ae00313aac83f5a35617a40bd2820201e6d3f5a54dcd10214"),  # x0 must be `this` again on both exits (get_Player derefs x0+0x10)
        },
        {
            "description": "PlayerStateNormal.Acceleration `b.le normal-branch` -> b EnableAI cave",
            "offset": 0x17E7990,
            "expected": bytes.fromhex("ed030054"),
            "replacement": bytes.fromhex("182efd17"),
        },
        # Offline RPC transport. Every gameplay RPC (ReceiveDamage, ReceiveHit, effects...) goes through
        # CharacterRPCControllerBase.SendRPC -> ReplayManager.SendRPC -> PhotonView.RPC. GRE.Singleton<ReplayManager>
        # is null in this offline flow (see the BeginSession/EndSession bypasses above), so SendRPC threw
        # NullReferenceException and no attack ever dealt damage. When the instance is null, call the
        # controller's own photonView.RPC(name, target, parameters) directly (PUN executes it locally offline).
        {
            "description": "cave: CharacterRPCControllerBase.SendRPC with null ReplayManager -> photonView.RPC(methodName, target, parameters)",
            "offset": 0x1733230,
            "expected": bytes.fromhex("e1031faa81066b94604200b9486a0190083940f9000140f94db64794f40300aae0031faa71a56a94f50300aa550000b5"),
            "replacement": bytes.fromhex("e00316aae1031faa4cd13094e10315aae203142ae30313aae4031faafd7b43a9f44f42a9f65741a9f70744f81d3d6814"),
        },
        {
            "description": "CharacterRPCControllerBase.SendRPC: NullReferenceException raise for null ReplayManager -> b direct-RPC cave",
            "offset": 0x31DA530,
            "expected": bytes.fromhex("2fe78097"),
            "replacement": bytes.fromhex("40639517"),
        },
        # Skill state watchdog. PlayerStateSkill.UpdateSubStateTime(time, next) waits forever when time < 0 until the
        # SkillAction reports IsNextState; SwordSkillAction (and friends) only do that once the kicker is within 3 u / 90
        # deg of MainTarget, so a cast at a fleeing or missing target leaves the kicker frozen in the pose with no
        # cooldown. Only for the Execute->Finish (next == 4) and Finish->End (next == 0) transitions, advance after 4 s.
        {
            "description": "cave: PlayerStateSkill.UpdateSubStateTime negative-time wait -> advance after 4 s for Execute/Finish",
            "offset": 0x17332B0,
            "expected": bytes.fromhex("69690190082d42f9296147f9e10313aaf50300aa020140f9230140f948144294740000b5"),
            "replacement": bytes.fromhex("05cc60549f12007160000054540000345e0603140110221e0020211ea5cd60545a060314"),
        },
        {
            "description": "PlayerStateSkill.UpdateSubStateTime `b.mi wait` -> b watchdog cave",
            "offset": 0x17F4C2C,
            "expected": bytes.fromhex("64000054"),
            "replacement": bytes.fromhex("a1f9fc17"),
        },
        # Skill exit pose. After a kicker/disc skill the state machine returns to PlayerStateNormal but the animator
        # keeps the last skill clip until some other action plays (dodge, attack...). On PlayerStateSkill.End() play
        # PlayerAnimator.PlayIdle(isGround=false, 0.1 s) explicitly. Cave in the dead body of the stubbed
        # HomeSummonModelController.UnloadModel (0x159DF60..0x159E0A8, nothing branches into it).
        {
            "description": "cave: PlayerStateSkill.End tail -> ClearSynchronizedProperty(); Player.PlayerAnimator.PlayIdle(false, 0.1, 0)",
            "offset": 0x159DF70,
            "expected": bytes.fromhex("a8325c39f403012af30300aae8000037e87201f0084d44f9000140b9a12ff197e8030032a8321c39e87001f0081940f9000140f9f60a4e94f50300aa550000b58fd8f197e00315aae1031faa7fef0794f50300aa550000b5"),
            "replacement": bytes.fromhex("fd7bbea9f30b00f9f30300aae1031faae24e0994e00313aae1031faa638b0c94600100b4e1031faa58a0f897000100b4e1031f2aa899995288b9a7720001271ee103271ee2031faa7d42f897f30b40f9fd7bc2a8c0035fd6"),
        },
        {
            "description": "PlayerStateSkill.End tail call `b ClearSynchronizedProperty` -> b idle cave",
            "offset": 0x17F8F1C,
            "expected": bytes.fromhex("fbe2ff17"),
            "replacement": bytes.fromhex("1594f617"),
        },
        *DIAG_PATCHES_ARM64,
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
        replacement = base_url if kind == "base_url" else f"{authority}/"
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
