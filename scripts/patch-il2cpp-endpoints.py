"""Patch Kick-Flight IL2CPP endpoint literals for a direct private server.

This script is intentionally specific to the preserved 2.11.0 APK. It validates
the metadata layout and native instruction bytes before changing anything.

NATIVE_PATCHES["arm64-v8a"] is the union of two patch families (merged 2026-09-21, both validated against the
pristine libil2cpp.so):
  * Photon multiplayer (Gixarde3/main): real 2-player rooms, result scene, reconnect guards, RPC handling,
    SkillRangeValidator instantiation, ns.exitgames.com -> server host.
  * Offline / solo battle (tanuki-discs): offline ownership (IsMine), bot AI + bot special skills, gym mannequins,
    bat-bomb traps, basic-attack combos (GetDisplayAngles cave, IsUpdateAction), GetRange master fallback,
    RANGED_ATTACK_INTERVALS.
Where both families patched the same bytes the newer/complete fix was kept: CreateValidator instantiates the
validators (was: return null), GetRange/GetDisplayAngles use the offline caves (superset of the older stubs).

Build modes (environment variables): KF_DIAG=1 full KFDIAG trace (DIAG_PATCHES_ARM64), KF_RESULT_DIAG=1 isolated
ResultManager/ResultScene trace (RESULT_DIAG_PATCHES_ARM64; exclusive with KF_DIAG), KF_NRE_LR=1 (with KF_DIAG)
log the return address of every NRE, KF_UNLOAD_BYPASS=1, KF_FORCE_GAME_SCENE=1, KF_UNITY_NO_ALLOCATOR_REBIND=1 (drop the libunity allocator rebinding),
KF_PHOTON=1 Photon (LuxonServer) matchmaking flow instead of the offline bridge (see PHOTON_FLOW).
"""

from __future__ import annotations

import argparse
import os
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

# Ready scene. The "ponytail" patches (2026-09-07) skip the whole GameReadyScene intro cinematic (whose end is the
# 3-2-1 countdown) because the high-model game_ready animators were not served back then, and then fake its
# completion at PlayGoAnimation / relax the RoomStartTime gate. KF_READY_SCENE=1 drops those seven patches so the
# retail flow runs (ready cinematic -> countdown -> GO, input locked until then). Experimental, 2026-09-21.
READY_SCENE = os.environ.get("KF_READY_SCENE") == "1"

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
        "replacement": bytes.fromhex("f40300aafd7bbfa98092011109000094fd7bc1a8c0035fd6f90300aafd7bbfa9a022031103000094fd7bc1a8c0035fd616460014e303002a60008052a1000010c2000010c567f497fd7bc1a8c0035fd64b46444941470000763d256400000000fd7bbfa9601240b900b00411f1ffff97681240b9fd7bc1a8c0035fd6"),
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
    # DISABLED 2026-09-20: hooks every il2cpp exception raise on EVERY thread; a raise on UnityPreload during the
    # match load (right after 952 RouteJunctionTable.InitTable) ended in SIGSEGV in the Unity log formatter 5/5 times
    # (the known "DIAG hangs/crashes on the loading screen" race). Re-enable only for exception-origin hunts.
    # 2026-09-20 later: the 5/5 loading crash was the 8230 probe's x19 reuse, not this hook. Opt-in with KF_NRE_LR=1
    # (KFDIAG prints the decimal RVA of the `bl 0x12141ec` site + 4 for every NullReferenceException).
    *([{
        "description": "DIAG hookH: il2cpp NRE throw helper entry (0x12141EC) -> b cave H (logs LR, re-runs displaced sub sp, jumps back)",
        "offset": 0x012141EC,
        "expected": bytes.fromhex("ff8300d1"),  # sub sp, sp, #0x20
        "replacement": bytes.fromhex("5d730d14"),
    }] if os.environ.get("KF_NRE_LR") == "1" else []),
    {
        "description": "DIAG: cave I — log LR + 3 frame-pointer return addresses of every il2cpp generic exception raise (0x121415C)",
        "offset": 0x1570f78,
        "expected": bytes.fromhex("940f7294f30300aa530000b59a8cf297e00313aae1031faa4a2d079460000036e00700323f000014800240f9089c44398800083608d840b9480000356b18f297"),
        "replacement": bytes.fromhex("fd7bbca9e00701a9e20f02a9f45703a9e0031e2aef2cf997e02340f9ed2cf997e02740f9eb2cf997f45743a9e20f42a9e00741a9fd7bc4a8f30f1ef86b8cf217"),
    },
    # DISABLED 2026-09-20: hooks every il2cpp exception raise on EVERY thread; a raise on UnityPreload during the
    # match load (right after 952 RouteJunctionTable.InitTable) ended in SIGSEGV in the Unity log formatter 5/5 times
    # (the known "DIAG hangs/crashes on the loading screen" race). Re-enable only for exception-origin hunts.
    #     {
    #         "description": "DIAG hookI: il2cpp generic raise entry -> b cave I (logs LR, re-runs displaced str x19, jumps back)",
    #         "offset": 0x0121415C,
    #         "expected": bytes.fromhex("f30f1ef8"),  # str x19, [sp, #-0x20]!
    #         "replacement": bytes.fromhex("87730d14"),
    #     },
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
    *([{
        "description": "DIAG: region C caves in dead body of GameReadyScene.GetGameReadyAnimationClip (900 ExecuteUpdate, 901 Execute, 902 UpdateTarget, 903 SetCurrentTarget)",
        "offset": 0x176030c,
        "expected": bytes.fromhex("fd7b02a9fd830091537b01f068e25239f40301aae20f00b9e80000376867019008c545f9000140b9b726ea97e803003268e21239a86601f008b545f9000140f9e30eeb97e1031faaf30300aa4b146794740000b5e0031faaa2cfea97e00314aae1031faa4a136794f40300aa730000b5e0031faa9bcfea97e00313aae10314aae2031faa80146794686801b0084940f9e0330091e2031faa010140f95a581794"),
        "replacement": bytes.fromhex("fd7bbda9e00701a9e20f02a9807080520b70f197e20f42a9e00741a9fd7bc3a8f30300aac0035fd6fd7bbda9e00701a9e20f02a9a07080520170f197e20f42a9e00741a9fd7bc3a8f30300aac0035fd6fd7bbda9e00701a9e20f02a9c0708052f76ff197e20f42a9e00741a9fd7bc3a8882e6b39c0035fd6fd7bbda9e00701a9e20f02a9e0708052ed6ff197e20f42a9e00741a9fd7bc3a8f40301aac0035fd6"),
    }] if not READY_SCENE else []),
    *([{
        "description": "DIAG hook: AIPlayerEngine.ExecuteUpdate -> log 900",
        "offset": 0x018049e8,
        "expected": bytes.fromhex("f30300aa"),
        "replacement": bytes.fromhex("496efd97"),
    }] if not READY_SCENE else []),
    *([{
        "description": "DIAG hook: AIPlayerEngine.Execute -> log 901",
        "offset": 0x01804e10,
        "expected": bytes.fromhex("f30300aa"),
        "replacement": bytes.fromhex("496dfd97"),
    }] if not READY_SCENE else []),
    *([{
        "description": "DIAG hook: AIPlayerEngine.UpdateTarget -> log 902",
        "offset": 0x01807170,
        "expected": bytes.fromhex("882e6b39"),
        "replacement": bytes.fromhex("7b64fd97"),
    }] if not READY_SCENE else []),
    *([{
        "description": "DIAG hook: AIPlayerEngine.SetCurrentTarget -> log 903",
        "offset": 0x01806834,
        "expected": bytes.fromhex("f40301aa"),
        "replacement": bytes.fromhex("d466fd97"),
    }] if not READY_SCENE else []),
    *([{
        "description": "DIAG: region C (cont.) caves — 921 WaitForWarpOut, 922 ApplyCancelWarp, 923 ApplyWarp",
        "offset": 0x17603ac,
        "expected": bytes.fromhex("486801b0080540f9e10300aae2031faa080140f9e00308aae34f1894f40300aa730000b5e0031faa86cfea97e00313aae10314aae2031faa88146794a86601d0084146f9f30300aa080140f9099d4439a900083609d940b969000035e00308aa555bea97e00313aae1031faae2031faac5323294e00313aafd7b42a9f44f41a9ffc30091c0035fd6"),
        "replacement": bytes.fromhex("fd7bbda9e00701a9e20f02a920738052e36ff197e20f42a9e00741a9fd7bc3a8f30300aac0035fd6fd7bbda9e00701a9e20f02a940738052d96ff197e20f42a9e00741a9fd7bc3a8f30300aac0035fd6fd7bb9a9e00701a9e20f02a9e08701ade28f02ad60738052cd6ff197e28f42ade08741ade20f42a9e00741a9fd7bc7a828876039c0035fd6"),
    }] if not READY_SCENE else []),
    *([{
        "description": "DIAG hook: WaitForWarpOut -> log 921",
        "offset": 0x0180589c,
        "expected": bytes.fromhex("f30300aa"),
        "replacement": bytes.fromhex("c46afd97"),
    }] if not READY_SCENE else []),
    *([{
        "description": "DIAG hook: ApplyCancelWarp -> log 922",
        "offset": 0x013e4a20,
        "expected": bytes.fromhex("f30300aa"),
        "replacement": bytes.fromhex("6dee0d94"),
    }] if not READY_SCENE else []),
    *([{
        "description": "DIAG hook: ApplyWarp -> log 923",
        "offset": 0x013e45b8,
        "expected": bytes.fromhex("28876039"),
        "replacement": bytes.fromhex("91ef0d94"),
    }] if not READY_SCENE else []),
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
        "description": "DIAG: region D caves in dead body of LoadManager.LoadDeckSummonModel (950+routeCount UpdateRoute, 951 SearchRoute, 952 RouteJunctionTable.InitTable) [relocated 2026-09-20 from LoadDeckSummonModel to the dead PlayerCharacter.UpdateLookTarget body]",
        "offset": 0x13cd990,
        "expected": bytes.fromhex("e923036dfc6f04a9fa6705a9f85f06a9f65707a9f44f08a9fd7b09a9fd430291f497019088566039f30300aae800003788800190081d42f9000140b91171f897e80300328856203974a640f9740000b5e0031faa021af997e00314aa8f98ff970820201ee801005474a640f9740000b5e0031faafa19f997e00314aac985ff970001003674a240f9740000b5e0031faaf319f997e00314aae7bbff970700001474a240f9740000b5e0031faaec19f997e00314aa57bbff97e00313aa48f4ff971f2c007140040054c0120035e00313aae1031f2ab1cbff97f40300aad41000b4358501f0b5c244f9890240f9"),
        "replacement": bytes.fromhex("fd7bb5a9e00701a9e20f02a9e41703a9e61f04a9e08702ade28f03ada10000b4201840b900d80e1164baff9703000014c076805261baff97e28f43ade08742ade61f44a9e41743a9e20f42a9e00741a9fd7bcba8f30301aac0035fd6fd7bb5a9e00701a9e20f02a9e41703a9e61f04a9e08702ade28f03ade07680524fbaff97e28f43ade08742ade61f44a9e41743a9e20f42a9e00741a9fd7bcba8f80304aac0035fd6fd7bb5a9e00701a9e20f02a9e41703a9e61f04a9e08702ade28f03ad007780523dbaff97e28f43ade08742ade61f44a9e41743a9e20f42a9e00741a9fd7bcba8c81a4639c0035fd6"),
    },
    {
        "description": "DIAG hook: UpdateRoute -> region D",
        "offset": 0x1807650,
        "expected": bytes.fromhex("f30301aa"),
        "replacement": bytes.fromhex("d018ef97"),
    },
    {
        "description": "DIAG hook: SearchRoute -> region D",
        "offset": 0x1701c9c,
        "expected": bytes.fromhex("f80304aa"),
        "replacement": bytes.fromhex("542ff397"),
    },
    {
        "description": "DIAG hook: InitTable -> region D",
        "offset": 0x16fe480,
        "expected": bytes.fromhex("c81a4639"),
        "replacement": bytes.fromhex("6d3df397"),
    },
    {
        "description": "DIAG: region D (cont.) — 970+flags set_AutoMoveFlags, 971 PerformAttack, 972 PerformGetScore, 973 PerformMove [relocated 2026-09-20 from LoadDeckSummonModel to the dead PlayerCharacter.UpdateLookTarget body]",
        "offset": 0x13cda80,
        "expected": bytes.fromhex("2b8144390a8144397f010a6bc3000054296540f9290d0a8b29815ff83f0108eb80000054e0031faad119f997a80240f9890240f90a8144392b8144397f010a6b430e0054296540f9290d0a8b29815ff83f0108eb80029f9a6d00001461018052e00313aa91cbff97f40300aad40100b4088401d0082941f9890240f9080140f92b8144390a8144397f010a6bc3000054296540f9290d0a8b29815ff83f0108eb00150054e0031faab119f997f4031faaf6030032e00314aae1031faa0c901094800b00b476000034e0031faaa819f997e00314aae1031faa05901094f50300aa550000b5a219f997e00315aae1031faabf430194e00900b476000034e0031faa9b19f997e00314aae1031faaf88f1094f50300aa550000b59519f997e00315aa"),
        "replacement": bytes.fromhex("fd7bb5a9e00701a9e20f02a9e41703a9e61f04a9e08702ade28f03ad20280f112abaff97e28f43ade08742ade61f44a9e41743a9e20f42a9e00741a9fd7bcba8f303012ac0035fd6fd7bb5a9e00701a9e20f02a9e41703a9e61f04a9e08702ade28f03ad6079805218baff97e28f43ade08742ade61f44a9e41743a9e20f42a9e00741a9fd7bcba8f30301aac0035fd6fd7bb5a9e00701a9e20f02a9e41703a9e61f04a9e08702ade28f03ad8079805206baff97e28f43ade08742ade61f44a9e41743a9e20f42a9e00741a9fd7bcba8f40300aac0035fd6fd7bb5a9e00701a9e20f02a9e41703a9e61f04a9e08702ade28f03ada0798052f4b9ff97e28f43ade08742ade61f44a9e41743a9e20f42a9e00741a9fd7bcba8c8da5c39c0035fd6"),
    },
    {
        "description": "DIAG hook: PlayerCharacter.set_AutoMoveFlags(970+flags)",
        "offset": 0x13bf2b8,
        "expected": bytes.fromhex("f303012a"),
        "replacement": bytes.fromhex("f2390094"),
    },
    {
        "description": "DIAG hook: PlayerCharacter.PerformAttack",
        "offset": 0x13bef78,
        "expected": bytes.fromhex("f30301aa"),
        "replacement": bytes.fromhex("d43a0094"),
    },
    {
        "description": "DIAG hook: PlayerCharacter.PerformGetScore",
        "offset": 0x13c0200,
        "expected": bytes.fromhex("f40300aa"),
        "replacement": bytes.fromhex("44360094"),
    },
    {
        "description": "DIAG hook: PlayerCharacter.PerformMove",
        "offset": 0x13bf870,
        "expected": bytes.fromhex("c8da5c39"),
        "replacement": bytes.fromhex("ba380094"),
    },
    {
        "description": "DIAG: region E (keystone-generated, scripts/re/mkcave.py) in dead body of LoadManager.LoadDeckSummonModel: safe LOG helper that preserves x0-x18/q0-q7/q16-q31 (the region A helper at 0x13BC348 branches here; without it caves clobbered x8 between a method's metadata-init flag load and its tbnz and randomly skipped il2cpp method init -> SIGSEGV fault addr 0x127), plus PerformMove destination-selection trace caves [relocated 2026-09-20 from LoadDeckSummonModel to the dead PlayerCharacter.UpdateLookTarget body]",
        "offset": 0x13cdba0,
        "expected": bytes.fromhex("e1031faab2430194f50300aa550000b58f19f997e00315aae1031faa3ed311948007003676000034e0031faa8819f997e00314aae1031faae58f1094f40300aa540000b58219f997e00314aae1031faacd430194488301b0084146f9f40300aa080140f9099d4439a900083609d940b969000035e00308aa52a5f897e00314aae1031faae2031faa5a88409420040036680240f9e00313aa090541f9010941f920013fd6f503002a740000b5e0031faa6719f997880240f9e00314aa090541f9010941f920013fd6e103002ae003152ae2031faa6a0d0994c001003673a240f9460000145a19f997e0031faae1031faa1b6410941f140071e8020054e80300320821c01a890580520801090a4802003473a240f9730000b5e0031faa4c19f997e00313aae1031faafd7b49a9f44f48a9f65747a9f85f46a9fa6745a9fc6f44a9e923436deb2b426ded33416dee074afc7abaff17e00313aa2dc6ff97c0000036742a41f973a240f9940400b5e0031faa2100001474ca40f9740000b5e0031faa3319f997e00314aae1031faa4b3111945b8301b07b4346f9f40300aa680340f9099d4439a900083609d940b969000035e00308aa03a5f897e00314aae1031faae2031faa0b8840940003003674ca40f973a240f9740000b5e0031faa1c19f997e00314aae1031faa34311194f40300aa540000b51619f997e00314aae1031faa27bb1a94f40300aa730000b5e0031faa0f19f997e00313aae10314aac3ffff17f6031f2a5cffff17680240f9e00313aa090541f9010941f920013fd6e1031faa090d0994a88501b008fd43f9f403002a080140f9099d4439a900083609d940b969000035e00308aad6a4f897e003142ae1031faacadb0094c8f200b01c8501f0398101b0fa8501f00e254ebd9cc746f9394746f95a2745f9f50300aaf6031f2af4031faa56000014750000b5e0031faae718f997220340f9e00315aae103162a1c626c94f70300aa570000b5e018f997600340f9f82a41f9089c44398800083608d840b948000035b6a4f897e00318aae10313aae2031faabe874094e0070037e00317aae1031faae5ba1a94f80300aa580000b5ce18f997e00318aae1031faab1ed4e94e00313aae1031faa081ca04e291ca14e4a1ca24ed9ba1a94f80300aa580000b5c218f997e00318aae1031faaa5ed4e942885019008f542f90b1ca04e2c1ca14e4d1ca24e000140f9089c44398800083608d840b94800003591a4f897001da84e211da94e421daa4e631dab4e841dac4ea51dad4e"),
        "replacement": bytes.fromhex("ff0309d1fd7b00a9e00701a9e20f02a9e41703a9e61f04a9e82705a9ea2f06a9ec3707a9ee3f08a9f04709a9f25300f9e08705ade28f06ade49707ade69f08adf0c709adf2cf0aadf4d70badf6df0cadf8e70dadfaef0eadfcf70fadfeff10ade303002a6000805281030010a20300109821f497feff50adfcf74fadfaef4eadf8e74dadf6df4cadf4d74badf2cf4aadf0c749ade69f48ade49747ade28f46ade08745adf25340f9f04749a9ee3f48a9ec3747a9ea2f46a9e82745a9e61f44a9e41743a9e20f42a9e00741a9fd7b40a9ff030991c0035fd64b46444941470000763d256400000000ff0309d1fd7b00a9e00701a9e20f02a9e41703a9e61f04a9e82705a9ea2f06a9ec3707a9ee3f08a9f04709a9f25300f9e08705ade28f06ade49707ade69f08adf0c709adf2cf0aadf4d70badf6df0cadf8e70dadfaef0eadfcf70fadfeff10ad00a00f1197b9ff97feff50adfcf74fadfaef4eadf8e74dadf6df4cadf4d74badf2cf4aadf0c749ade69f48ade49747ade28f46ade08745adf25340f9f04749a9ee3f48a9ec3747a9ea2f46a9e82745a9e61f44a9e41743a9e20f42a9e00741a9fd7b40a9ff030991e803002ac0035fd6ff0309d1fd7b00a9e00701a9e20f02a9e41703a9e61f04a9e82705a9ea2f06a9ec3707a9ee3f08a9f04709a9f25300f9e08705ade28f06ade49707ade69f08adf0c709adf2cf0aadf4d70badf6df0cadf8e70dadfaef0eadfcf70fadfeff10ad60e640b90030111162b9ff97e01340b9005014115fb9ff9760ea40b95db9ff97feff50adfcf74fadfaef4eadf8e74dadf6df4cadf4d74badf2cf4aadf0c749ade69f48ade49747ade28f46ade08745adf25340f9f04749a9ee3f48a9ec3747a9ea2f46a9e82745a9e61f44a9e41743a9e20f42a9e00741a9fd7b40a9ff03099168864339c0035fd6ff0309d1fd7b00a9e00701a9e20f02a9e41703a9e61f04a9e82705a9ea2f06a9ec3707a9ee3f08a9f04709a9f25300f9e08705ade28f06ade49707ade69f08adf0c709adf2cf0aadf4d70badf6df0cadf8e70dadfaef0eadfcf70fadfeff10ad0000381e00401f1128b9ff970109281e62092b1e2128221e82092c1e2128221e21c0211e2000381e00e02e111fb9ff97feff50adfcf74fadfaef4eadf8e74dadf6df4cadf4d74badf2cf4aadf0c749ade69f48ade49747ade28f46ade08745adf25340f9f04749a9ee3f48a9ec3747a9ea2f46a9e82745a9e61f44a9e41743a9e20f42a9e00741a9fd7b40a9ff030991031ca04ec0035fd6"),
    },
    {
        "description": "DIAG hook: PerformMove after get_TargetActive -> 1000+active",
        "offset": 0x13bf8b4,
        "expected": bytes.fromhex("e803002a"),
        "replacement": bytes.fromhex("f5380094"),
    },
    {
        "description": "DIAG hook: PerformMove after route count check -> 1100+AIOption, 1300+count, raw _aiAutoMoveDefaultGoalDistance bits",
        "offset": 0x13bf8f4,
        "expected": bytes.fromhex("68864339"),
        "replacement": bytes.fromhex("19390094"),
    },
    {
        "description": "DIAG hook: PerformMove per segment -> 2000+int(goalDistance), 3000+int(|segment|)",
        "offset": 0x13bfa10,
        "expected": bytes.fromhex("031ca04e"),
        "replacement": bytes.fromhex("0c390094"),
    },
    {
        "description": "DIAG: region E (cont.) minimal caves (safe LOG preserves everything) — 38xx SubState, 39xx auto-move flags consumed, 399x UpdateAutoSmoothMove result [relocated 2026-09-20 from LoadDeckSummonModel to the dead PlayerCharacter.UpdateLookTarget body]",
        "offset": 0x13cdf38,
        "expected": bytes.fromhex("e0031faa4b167494400340f9081ca04e291ca14e4a1ca24e089c44398800083608d840b94800003580a4f897001da84e211da94e421daa4ee0031faa9b1b1e94081ca04e00212e1ecc000054e00317aae1031faaacba1a94f40300aa0e1da84ed6060011750000b5"),
        "replacement": bytes.fromhex("fd7bbea9e00b00f900613b1101b9ff97e00b40f9fd7bc2a81f150071c0035fd6fd7bbea9e00b00f9609a41b900f03c11f8b8ff97e00b40f9fd7bc2a8749a41b9c0035fd6fd7bbea9e00b00f91f0000f1e0079f1a00583e11eeb8ff97e00b40f9fd7bc2a884551014"),
    },
    {
        "description": "DIAG hook: PlayerStateNormal.UpdateAction -> 3800+SubState each tick",
        "offset": 0x17e14e4,
        "expected": bytes.fromhex("1f150071"),
        "replacement": bytes.fromhex("95b2ef97"),
    },
    {
        "description": "DIAG hook: PlayerStateNormal.InputActionFly -> 3900+consumed CurrentAutoMoveFlags",
        "offset": 0x17e20a4,
        "expected": bytes.fromhex("749a41b9"),
        "replacement": bytes.fromhex("adafef97"),
    },
    {
        "description": "DIAG hook: InputActionFly after UpdateAutoSmoothMove -> 3990+(result!=null)",
        "offset": 0x17e3768,
        "expected": bytes.fromhex("91ffff17"),
        "replacement": bytes.fromhex("05aaef97"),
    },
    {
        "description": "DIAG: region E (cont. 2) minimal caves — 3700 UpdateFly reached CanTakeOff, 3701 CanTakeOff true [relocated 2026-09-20 from LoadDeckSummonModel to the dead PlayerCharacter.UpdateLookTarget body]",
        "offset": 0x13cdfa0,
        "expected": bytes.fromhex("e0031faa9218f997810340f9e00315aaa0616c94df02006b8bf4ff54600340f9089c44398800083608d840b94800003564a4f897e00314aae1031faae2031faa"),
        "replacement": bytes.fromhex("fd7bbea9e00b00f980ce8152e7b8ff97e00b40f9fd7bc2a8aa2e032dc0035fd6fd7bbea9e00b00f9a0ce8152dfb8ff97e00b40f9fd7bc2a8e00313aac0035fd6"),
    },
    {
        "description": "DIAG hook: PlayerStateNormal.UpdateFly before CanTakeOff -> 3700",
        "offset": 0x17e48b4,
        "expected": bytes.fromhex("aa2e032d"),
        "replacement": bytes.fromhex("bba5ef97"),
    },
    {
        "description": "DIAG hook: UpdateFly CanTakeOff true -> 3701 (then SetSubStateTakeOff)",
        "offset": 0x17e48c0,
        "expected": bytes.fromhex("e00313aa"),
        "replacement": bytes.fromhex("c0a5ef97"),
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
    # Hitagi warp / SetVisible probes (scripts/re/warp_diag_caves.py)
    {"description": "DIAG cave: PlayerCharacter.SetVisible entry -> 7800+visible, 7810/7820/7830 + non-null(_modelCtr/EffectCtr/Weapons)", "offset": 0x159d420, "expected": bytes.fromhex("e0031faa72dbf197e00317aae1031faae8d70294e0031faa081ca04e6cdbf197e00317aae1031faae6d70294687701f0082545f9091ca04e000140f9089c44398800083608d840b9480000353d67f197e203271e001da84e211da94ee0031faaf0de1694081ca04e291ca14e4a1ca24e780000b5e0031faa55dbf197e00318aa001da84e211da94e421daa4ee1031faaaeb04794781640f9780000b5e0031faa4bdbf197e00318aae1031faad7053994f80300aa570100b4e00317aae1031faac8d70294e00317aae1031faa081ca04ec8d70294091ca04e0f000014e0031faa3bdbf197e00317aae1031faabdd70294e0031faa081ca04e35dbf197e00317aae1031faabbd70294e0031faa091ca04e2fdbf197e00317aae1031faab9d70294021ca04e"), "replacement": bytes.fromhex("ff0309d1fd7b00a9e00701a9e20f02a9e41703a9e61f04a9e82705a9ea2f06a9ec3707a9ee3f08a9f04709a9f25300f9e08705ade28f06ade49707ade69f08adf0c709adf2cf0aadf4d70badf6df0cadf8e70dadfaef0eadfcf70fadfeff10adf40300aa2000001201cf83520000010bae7bf89788b640f91f0100f1e0079f1a41d083520000010ba87bf89788ba40f91f0100f1e0079f1a81d183520000010ba27bf89788aa40f91f0100f1e0079f1ac1d283520000010b9c7bf897feff50adfcf74fadfaef4eadf8e74dadf6df4cadf4d74badf2cf4aadf0c749ade69f48ade49747ade28f46ade08745adf25340f9f04749a9ee3f48a9ec3747a9ea2f46a9e82745a9e61f44a9e41743a9e20f42a9e00741a9fd7b40a9ff030991f40300aac0035fd6")},
    {"description": "DIAG hook: PlayerCharacter.SetVisible entry -> 7800+visible, 7810/7820/7830 + non-null(_modelCtr/EffectCtr/Weapons)", "offset": 0x13c5c44, "expected": bytes.fromhex("f40300aa"), "replacement": bytes.fromhex("f75d0794")},
    {"description": "DIAG cave: JapaneseSwordSkillAction.OnBeginFinish -> 7700 + (PushBackCollider != null)", "offset": 0x159d560, "expected": bytes.fromhex("780000b5e0031faa21dbf197e00318aa001da84e211da94e421daa4ee1031faa05b14794770000b5e0031faa18dbf197e00317aae1031faa96d70294081ca04e760000b5e0031faa11dbf197fc7501d0c80240f99cdb46f9093d4279810340f9690100b40b5940f9ea031faa6b2100916c815ff89f0101eb200100544a0500915f0109eb6b41009143ffff54e2031f32e00316aa4415f19705000014690140b9290900110851298b00a10491080440a9e00316aa00013fd6f80300aa580000b5f3daf197e00318aae1031faa86dbfe97091ca04e760000b5e0031faa"), "replacement": bytes.fromhex("ff0309d1fd7b00a9e00701a9e20f02a9e41703a9e61f04a9e82705a9ea2f06a9ec3707a9ee3f08a9f04709a9f25300f9e08705ade28f06ade49707ade69f08adf0c709adf2cf0aadf4d70badf6df0cadf8e70dadfaef0eadfcf70fadfeff10ad1f0000f1e0079f1a81c283520000010b5e7bf897feff50adfcf74fadfaef4eadf8e74dadf6df4cadf4d74badf2cf4aadf0c749ade69f48ade49747ade28f46ade08745adf25340f9f04749a9ee3f48a9ec3747a9ea2f46a9e82745a9e61f44a9e41743a9e20f42a9e00741a9fd7b40a9ff030991f40300aac0035fd6")},
    {"description": "DIAG hook: JapaneseSwordSkillAction.OnBeginFinish -> 7700 + (PushBackCollider != null)", "offset": 0x15201ec, "expected": bytes.fromhex("f40300aa"), "replacement": bytes.fromhex("ddf40194")},
    {"description": "DIAG cave: JapaneseSwordSkillAction.OnBeginFinish -> 7710, end.x, 7711, end.z (_noTargetEndPosition), 7712, pos.x, pos.z", "offset": 0x159d640, "expected": bytes.fromhex("c80240f9810340f9093d4279690100b40b5940f9ea031faa6b2100916c815ff89f0101eb200100544a0500915f0109eb6b41009143ffff54e2031f32e00316aa2115f19705000014690140b9290900110851298b00a10491080440a9e00316aa0809291e00013fd6f80300aa580000b5cfdaf197e00318aa001da84ee1031faa88e1fe97781a40f9780000b5e0031faac7daf197e00318aae1031faa53053994f80300aad70000b4e00317aae1031faa50d70294081ca04e09000014e0031faabbdaf197e00317aae1031faa49d70294e0031faa081ca04eb5daf197e00317aae1031faa47d70294011ca04ee203271e001da84ee0031faa42de1694081ca04e291ca14e4a1ca24e780000b5e0031faaa7daf197e00318aa001da84e211da94e421daa4e"), "replacement": bytes.fromhex("ff0309d1fd7b00a9e00701a9e20f02a9e41703a9e61f04a9e82705a9ea2f06a9ec3707a9ee3f08a9f04709a9f25300f9e08705ade28f06ade49707ade69f08adf0c709adf2cf0aadf4d70badf6df0cadf8e70dadfaef0eadfcf70fadfeff10adc0c38352297bf8970000381e277bf897e0c38352257bf8974000381e237bf897e00313aae1031faacc09fa97e1031faadb7c1394e1031faaabaf4794081ca04e491ca24e00c48352187bf8970001381e167bf8972001381e147bf897feff50adfcf74fadfaef4eadf8e74dadf6df4cadf4d74badf2cf4aadf0c749ade69f48ade49747ade28f46ade08745adf25340f9f04749a9ee3f48a9ec3747a9ea2f46a9e82745a9e61f44a9e41743a9e20f42a9e00741a9fd7b40a9ff030991608e01bdc0035fd6")},
    {"description": "DIAG hook: JapaneseSwordSkillAction.OnBeginFinish -> 7710, end.x, 7711, end.z (_noTargetEndPosition), 7712, pos.x, pos.z", "offset": 0x15202a4, "expected": bytes.fromhex("608e01bd"), "replacement": bytes.fromhex("e7f40194")},
    {"description": "DIAG cave: WarpSkillAction.UpdateFinish -> 7720 (IsWarp, checking IsVisible)", "offset": 0x159d7a0, "expected": bytes.fromhex("e1031faa081ca04e32d70294091ca04e0f000014e0031faa8ddaf197e00317aae1031faa27d70294e0031faa081ca04e87daf197e00317aae1031faa25d70294e0031faa091ca04e81daf197e00317aae1031faa23d70294021ca04e001da84e211da94ee0031faa0ede1694081ca04e291ca14e4a1ca24e780000b5e0031faa73daf197e00318aa001da84e211da94e421daa4ee1031faa57b04794760000b5e0031faa6adaf197c80240f9810340f9093d4279690100b40b5940f9ea031faa6b2100916c815ff89f0101eb20010054"), "replacement": bytes.fromhex("ff0309d1fd7b00a9e00701a9e20f02a9e41703a9e61f04a9e82705a9ea2f06a9ec3707a9ee3f08a9f04709a9f25300f9e08705ade28f06ade49707ade69f08adf0c709adf2cf0aadf4d70badf6df0cadf8e70dadfaef0eadfcf70fadfeff10ad00c58352d17af897feff50adfcf74fadfaef4eadf8e74dadf6df4cadf4d74badf2cf4aadf0c749ade69f48ade49747ade28f46ade08745adf25340f9f04749a9ee3f48a9ec3747a9ea2f46a9e82745a9e61f44a9e41743a9e20f42a9e00741a9fd7b40a9ff030991e00314aac0035fd6")},
    {"description": "DIAG hook: WarpSkillAction.UpdateFinish -> 7720 (IsWarp, checking IsVisible)", "offset": 0x1817174, "expected": bytes.fromhex("e00314aa"), "replacement": bytes.fromhex("8b19f697")},
    {"description": "DIAG cave: WarpSkillAction.UpdateFinish -> 7721 (invisible: UpdateTransform runs)", "offset": 0x159d880, "expected": bytes.fromhex("e2031f32e00316aa9f14f19705000014690140b9290900110851298b00a10491080440a9e00316aa00013fd6f60300aa770000b5e0031faa4ddaf197e00317aae1031faae3d60294081ca04e760000b5e0031faa46daf19748e400d0003942bde00316aae1031faa0009201ec1e1fe97400340f9a20c4e94f60300aa560000b53bdaf197e00316aae1031faa2bf10794f60300aa560000b535daf197620340f9e00316aae103152a514c1294f60300aa560000b52edaf197e00316aae1031faa87d60294287101d0081143f9f603002a"), "replacement": bytes.fromhex("ff0309d1fd7b00a9e00701a9e20f02a9e41703a9e61f04a9e82705a9ea2f06a9ec3707a9ee3f08a9f04709a9f25300f9e08705ade28f06ade49707ade69f08adf0c709adf2cf0aadf4d70badf6df0cadf8e70dadfaef0eadfcf70fadfeff10ad20c58352997af897feff50adfcf74fadfaef4eadf8e74dadf6df4cadf4d74badf2cf4aadf0c749ade69f48ade49747ade28f46ade08745adf25340f9f04749a9ee3f48a9ec3747a9ea2f46a9e82745a9e61f44a9e41743a9e20f42a9e00741a9fd7b40a9ff030991e00313aac0035fd6")},
    {"description": "DIAG hook: WarpSkillAction.UpdateFinish -> 7721 (invisible: UpdateTransform runs)", "offset": 0x1817184, "expected": bytes.fromhex("e00313aa"), "replacement": bytes.fromhex("bf19f697")},
    {"description": "DIAG cave: WarpSkillAction.UpdateTransform -> 7730, lerp.x, lerp.z (position handed to PlayerCharacter.SetPosition)", "offset": 0x159d960, "expected": bytes.fromhex("570000b522daf197e5030032e00317aae103152ae203162ae3031faae4031f2ae6031faa64dbfa97771640f9f60300aa762600f9770000b5e0031faa14daf197e00317aae1031faaa0043994f70300aa760000b5e0031faa0ddaf197c80240f9e00316aae103152ae203142a099157a9e30317aa20013fd6742640f9740000b5e0031faa02daf197e00314aae1031faa137c1394601e00f9a8760190081941f9000140f93519f297e1031faaf40300aac9c70294742200f9200340f9752640f9089c44398800083608d840b948000035cc65f197e00315aae1031faae2031faad4483994f5031faa"), "replacement": bytes.fromhex("ff0309d1fd7b00a9e00701a9e20f02a9e41703a9e61f04a9e82705a9ea2f06a9ec3707a9ee3f08a9f04709a9f25300f9e08705ade28f06ade49707ade69f08adf0c709adf2cf0aadf4d70badf6df0cadf8e70dadfaef0eadfcf70fadfeff10ad081ca04e491ca24e40c683525f7af8970001381e5d7af8972001381e5b7af897feff50adfcf74fadfaef4eadf8e74dadf6df4cadf4d74badf2cf4aadf0c749ade69f48ade49747ade28f46ade08745adf25340f9f04749a9ee3f48a9ec3747a9ea2f46a9e82745a9e61f44a9e41743a9e20f42a9e00741a9fd7b40a9ff030991e2031faac0035fd6")},
    {"description": "DIAG hook: WarpSkillAction.UpdateTransform -> 7730, lerp.x, lerp.z (position handed to PlayerCharacter.SetPosition)", "offset": 0x1817534, "expected": bytes.fromhex("e2031faa"), "replacement": bytes.fromhex("0b19f697")},
    # SetDisplayAngles' body hosts the region-A caves above, but only its first instruction (str d10,[sp,#-0x40]!)
    # was left in place: any call fell into the caves and returned with SP off by 0x40. Harmless while GetDisplayAngles
    # was stubbed to zero (UpdateFly / UpdateAngles never took the SetDisplayAngles branch); with the production
    # GetDisplayAngles fix the branch is live and DIAG builds crashed (SIGSEGV in the Unity log formatter right after
    # 3900 InputActionFly, 2026-09-20). DIAG-only: make SetDisplayAngles a no-op at its entry.
    {"description": "DIAG: stub PlayerBoneController.SetDisplayAngles entry (its body is region A) -> ret", "offset": 0x13BC314, "expected": bytes.fromhex("ea0f1cfc"), "replacement": bytes.fromhex("c0035fd6")},
    # Basic-attack loop probes (scripts/re/attack_diag_caves.py): 8100-8600
    {"description": "DIAG cave: WeaponAttackActionBase.AddComboCount -> 8100 + combo index just attacked", "offset": 0x13ba660, "expected": bytes.fromhex("ee8300fdedb3106debab116de9a3126dfc9f00f9f65714a9f44f15a9fd7b16a9fd830591749801f0882a5c39f30300aae8000037a88601f0081142f9000140b9dcbdf897e8030032882a1c39"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d686240b9690080520a09c91a48a1091b81f483520001010b2f070094f013c03dea1b40f9e82742a9e00741a9fd7bc5a8686240b9c0035fd6")},
    {"description": "DIAG hook: WeaponAttackActionBase.AddComboCount -> 8100 + combo index just attacked", "offset": 0x181c8e8, "expected": bytes.fromhex("686240b9"), "replacement": bytes.fromhex("5e77ee97")},
    {"description": "DIAG cave: JapaneseSwordAttackAction.UpdateAction: IsReset (target null) -> ResetComboCount -> 8210", "offset": 0x13ba6ac, "expected": bytes.fromhex("088501b008c147f9000140f9089c44398800083608d840b948000035a6f2f897e0031faae2ad2394743240f9081ca04e740000b5e0031faac266f997a82302d1e00314aa"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d680e40f90881433968000035400284521e070094f013c03dea1b40f9e82742a9e00741a9fd7bc5a8e00313aac0035fd6")},
    {"description": "DIAG hook: JapaneseSwordAttackAction.UpdateAction: IsReset (target null) -> ResetComboCount -> 8210", "offset": 0x151e674, "expected": bytes.fromhex("e00313aa"), "replacement": bytes.fromhex("0e70fa97")},
    {"description": "DIAG cave: JapaneseSwordAttackAction.UpdateAction: IsUpdateAction false -> ResetComboCount -> 8211", "offset": 0x13ba6f0, "expected": bytes.fromhex("e1031faa0990241e67bc0994757e40f9750000b5e0031faab966f997e8c30291e00315aae1031faaf62302910809291e5dbc099468840190080540f9000140f9089c4439"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d680e40f90881433968000035600284520d070094f013c03dea1b40f9e82742a9e00741a9fd7bc5a8e00313aac0035fd6")},
    {"description": "DIAG hook: JapaneseSwordAttackAction.UpdateAction: IsUpdateAction false -> ResetComboCount -> 8211", "offset": 0x151e6c0, "expected": bytes.fromhex("e00313aa"), "replacement": bytes.fromhex("0c70fa97")},
    {"description": "DIAG cave: WeaponAttackActionBase.IsUpdateAction -> 8230 (false) + reasons 8710 sync/8720 enableAttack/8730 transitionMotion/8740 stateNormal/8750 land/8760 crouch/8770 ssTargeting (+1 = true; human only)", "offset": 0x13ba734, "expected": bytes.fromhex("8800083608d840b94800003588f2f897a88359b8c08642ade9d340b9e38b45ade88300b9e00703ade8230291e0830191e1c30091001da84ee2031faae95300b9e38b01ada4ba0994740000b5e0031faa9a66f997e8ab40b9c10240ade1030091e00314aae2031faae82300b9e10300ade3bc09946882019008c545f9697a40bd6a0241bd000140f9089c44398800083608d840b94800003565f2f897201da94e411daa4e021da84ee0031faabbb54094627e40bd610641bd607a00bde0031faa401ca24e021da84eb4b540946606502d628a40bd630a41bd640e41bd651241bd607e00bdc01ca64e061da84ee0031faa1a65209463aa40bd641641bd6006102d628a00bd601ca34e811ca44e021da84ee0031faaa1b5409462ba40bd611a41bd60aa00bde0031faa401ca24e021da84e9ab5409460ba00bda88501f069aa552d08f542f96eb640bd6d1e41bd6b2241bd"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803df33740f9f30800b4740e40f9b40800b48882433968080035c0048452f9060094e00314aae1031faac9f00b9400000012c14084520000010bf2060094e00314aae1031faa7cf00b94f50300aaf50100b4e00315aae1031faa5909109400000012014284520000010be6060094e00315aae1031faa8909109400000012414384520000010bdf060094e00314aae1031f2ae2031faa050e009400000012814484520000010bd7060094e00314aae1031faadd400094c14a84520000010bd1060094e00314aae1031f2ae2031faa45180094f50300aaf50100b4e00315aae1031faa48b1109400000012c14584520000010bc4060094e00315aae1031faa38b1109400000012014784520000010bbd06009480a24a39414884520000010bb9060094f013c03dea1b40f9e82742a9e00741a9fd7bc5a8e0031f2ac0035fd6")},
    {"description": "DIAG hook: WeaponAttackActionBase.IsUpdateAction -> 8230 (false) + reasons 8710 sync/8720 enableAttack/8730 transitionMotion/8740 stateNormal/8750 land/8760 crouch/8770 ssTargeting (+1 = true; human only)", "offset": 0x181ad0c, "expected": bytes.fromhex("e0031f2a"), "replacement": bytes.fromhex("8a7eee97")},
    {"description": "DIAG cave: IsUpdateAction: SS gauge full while SS targeting is up -> 8220 (attacks suspended if EnableSpecialSkill)", "offset": 0x13ba884, "expected": bytes.fromhex("000140f96c2641bd089c44398800083608d840b94800003531f2f897201da94e411daa4ec21dae4ea31dad4e641dab4e851dac4e061da84e"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d80038452ab060094f013c03dea1b40f9e82742a9e00741a9fd7bc5a8e1031faac0035fd6")},
    {"description": "DIAG hook: IsUpdateAction: SS gauge full while SS targeting is up -> 8220 (attacks suspended if EnableSpecialSkill)", "offset": 0x181ac68, "expected": bytes.fromhex("e1031faa"), "replacement": bytes.fromhex("077fee97")},
    {"description": "DIAG cave: PlayerCharacter.IsTargetInAttackSearchDistance -> 8300 out of range / 8301 in range", "offset": 0x13ba8f8, "expected": bytes.fromhex("eb2b016de923026df51b00f9f44f04a9fd7b05a9fd430191759801f0a82e5c39f40301aaf30300aae8000037688301b008cd47f9000140b938bdf897e8030032a82e1c39751a40f9750000b5e0031faa"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d68824339c80000352021201ee0879f1a810d84520000010b89060094f013c03dea1b40f9e82742a9e00741a9fd7bc5a82021201ee0879f1ac0035fd6")},
    {"description": "DIAG hook: PlayerCharacter.IsTargetInAttackSearchDistance -> 8300 out of range / 8301 in range", "offset": 0x13c6c2c, "expected": bytes.fromhex("e0879f1a"), "replacement": bytes.fromhex("33cfff97")},
    {"description": "DIAG cave: IsAttack idle yaw check -> 8320, |dx|, limit", "offset": 0x13ba948, "expected": bytes.fromhex("2966f997e00315aae1031faaf83b4f94081ca04e291ca14e4a1ca24e740000b5e0031faa2066f997a88501f008f542f98d2e432d8c2240bd000140f9089c44398800083608d840b948000035f3f1f897001da84e211da94e"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d680e40f90881433908010035001084527706009430c0201e0002381e740600940000381e72060094f013c03dea1b40f9e82742a9e00741a9fd7bc5a82020201ec0035fd6")},
    {"description": "DIAG hook: IsAttack idle yaw check -> 8320, |dx|, limit", "offset": 0x181c198, "expected": bytes.fromhex("2020201e"), "replacement": bytes.fromhex("ec79ee97")},
    {"description": "DIAG cave: IsAttack idle pitch check -> 8321, |dy|, limit", "offset": 0x13ba9a0, "expected": bytes.fromhex("421daa4ea31dad4e641dab4e851dac4ee0031faae5637494081ca04e291ca14e4a1ca24e750000b5e0031faa0866f997e00315aa001da84e211da94e421daa4ee1031faaec3b4f94751e40f9750000b5e0031faafe65f997"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d680e40f90881433908010035201084526106009410c0201e0002381e5e0600942000381e5c060094f013c03dea1b40f9e82742a9e00741a9fd7bc5a80020211ec0035fd6")},
    {"description": "DIAG hook: IsAttack idle pitch check -> 8321, |dy|, limit", "offset": 0x181c1c4, "expected": bytes.fromhex("0020211e"), "replacement": bytes.fromhex("f779ee97")},
    {"description": "DIAG cave: IsAttack moving yaw check -> 8322, |dx|, limit", "offset": 0x13ba9f8, "expected": bytes.fromhex("e00315aae1031faacd3b4f948392442d852e40bde0031faace637494081ca04e291ca14e4a1ca24e750000b5e0031faaf165f997e00315aa001da84e211da94e421daa4ee1031faad53b4f948006462d823a40bd6312502d"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d680e40f90881433908010035401084524b06009430c0201e0002381e480600940001381e46060094f013c03dea1b40f9e82742a9e00741a9fd7bc5a82020281ec0035fd6")},
    {"description": "DIAG hook: IsAttack moving yaw check -> 8322, |dx|, limit", "offset": 0x181c1f8, "expected": bytes.fromhex("2020281e"), "replacement": bytes.fromhex("007aee97")},
    {"description": "DIAG cave: IsAttack moving pitch check -> 8323, |dy|, limit", "offset": 0x13ba090, "expected": bytes.fromhex("f44f01a9fd7b02a9fd830091749801f088265c39f30300aae800003788820190082140f9000140b956bff897e803003288261c39e00313aa33000094f5830190b54246f9743240f9a00240f9089c44398800083608d840b9"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d680e40f9088143390801003560108452a508009410c0201e0002381ea20800940001381ea0080094f013c03dea1b40f9e82742a9e00741a9fd7bc5a80020281ec0035fd6")},
    {"description": "DIAG hook: IsAttack moving pitch check -> 8323, |dy|, limit", "offset": 0x181c21c, "expected": bytes.fromhex("0020281e"), "replacement": bytes.fromhex("9d77ee97")},
    {"description": "DIAG cave: IsAttack -> 8310 (true: attack this frame)", "offset": 0x13ba0e8, "expected": bytes.fromhex("480000351df4f897e00314aae1031faae2031faa8dcb4094a0000036fd7b42a9f44f41a9f50743f8c0035fd6a00240f9741640f9089c4439"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803dc00e845292080094f013c03dea1b40f9e82742a9e00741a9fd7bc5a8e0030032c0035fd6")},
    {"description": "DIAG hook: IsAttack -> 8310 (true: attack this frame)", "offset": 0x181c224, "expected": bytes.fromhex("e0030032"), "replacement": bytes.fromhex("b177ee97")},
    {"description": "DIAG cave: WeaponAttackActionBase.PlayAttackIn -> 8400 + comboCount", "offset": 0x13ba120, "expected": bytes.fromhex("8800083608d840b9480000350df4f897e00314aae1031faae2031faa15d7409460010036741640f9740000b5e0031faa2768f997e00314aae1031faa"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d001a84520000010b83080094f013c03dea1b40f9e82742a9e00741a9fd7bc5a8f60300aac0035fd6")},
    {"description": "DIAG hook: WeaponAttackActionBase.PlayAttackIn -> 8400 + comboCount", "offset": 0x181e518, "expected": bytes.fromhex("f60300aa"), "replacement": bytes.fromhex("026fee97")},
    {"description": "DIAG cave: WeaponAttackActionBase.PlayMoveAttackIn -> 8500 + comboCount", "offset": 0x13ce3e0, "expected": bytes.fromhex("ed33016deb2b026de923036df65704a9f44f05a9fd7b06a9fd830191d49701f0885a6039f30300aae8000037288601d0082141f9000140b97e6ef897"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d802684520000010bd3b7ff97f013c03dea1b40f9e82742a9e00741a9fd7bc5a8f60300aac0035fd6")},
    {"description": "DIAG hook: WeaponAttackActionBase.PlayMoveAttackIn -> 8500 + comboCount", "offset": 0x181e5b0, "expected": bytes.fromhex("f60300aa"), "replacement": bytes.fromhex("8cbfee97")},
    {"description": "DIAG cave: WeaponAttackActionBase.PlayGroundMoveAttackIn -> 8600 + comboCount", "offset": 0x13ce41c, "expected": bytes.fromhex("e8030032885a2039e00313aae1031faa54a10b94f40300aa540000b56d17f997e1071e32e2030032e00314aae3031faadebc0f9474a640f91f000072"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d003384520000010bc4b7ff97f013c03dea1b40f9e82742a9e00741a9fd7bc5a8f60300aac0035fd6")},
    {"description": "DIAG hook: WeaponAttackActionBase.PlayGroundMoveAttackIn -> 8600 + comboCount", "offset": 0x181e648, "expected": bytes.fromhex("f60300aa"), "replacement": bytes.fromhex("75bfee97")},
    {"description": "DIAG cave: CollisionBase.OnDestroy -> 8800 + destroy type, 8810 + hit count (capped at 9)", "offset": 0x13ce458, "expected": bytes.fromhex("e003271e0e102e1ec91d201e740000b5e0031faa6017f997e00314aaa796ff97d6810190d6c645f9081ca04ec00240f9089c44398800083608d840b94800003532a3f897f58401b0b57642f92939281ea00240f9089c4439"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d014c84526002010bb5b7ff97a81a40b9290180521f01096b08b1891a414d84520001010baeb7ff97f013c03dea1b40f9e82742a9e00741a9fd7bc5a8940a40f9c0035fd6")},
    {"description": "DIAG hook: CollisionBase.OnDestroy -> 8800 + destroy type, 8810 + hit count (capped at 9)", "offset": 0x31e2928, "expected": bytes.fromhex("940a40f9"), "replacement": bytes.fromhex("ccae8797")},
    # ---- bomb probes (scripts/re/bomb_diag_caves.py, 9001-9041) ----
    {"description": "DIAG cave: BatBombTrapAction.AcceptAction -> 9001", "offset": 0x13ce540, "expected": bytes.fromhex("001da84e5296ff9760ca40f9a00b00b4e1031faa3d2f1194e1031faafa4b1194000b003674ca40f9740000b5e0031faa1f17f997e00314aa"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d206584527cb7ff97f013c03dea1b40f9e82742a9e00741a9fd7bc5a8e8030032c0035fd6")},
    {"description": "DIAG hook: BatBombTrapAction.AcceptAction -> 9001", "offset": 0x143bcb0, "expected": bytes.fromhex("e8030032"), "replacement": bytes.fromhex("244afe97")},
    {"description": "DIAG cave: BatBombTrapAction.OnApplyAction entered -> 9002", "offset": 0x13ce578, "expected": bytes.fromhex("e1031faa332f11941f30007160010054e903271ee0020035e00313aae1031faaf9a00b94f40300aa540000b51217f997a101805208000014"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d406584526eb7ff97f013c03dea1b40f9e82742a9e00741a9fd7bc5a8e00313aac0035fd6")},
    {"description": "DIAG hook: BatBombTrapAction.OnApplyAction entered -> 9002", "offset": 0x143bf44, "expected": bytes.fromhex("e00313aa"), "replacement": bytes.fromhex("8d49fe97")},
    {"description": "DIAG cave: BatBombTrapAction.OnApplyAction: explosion action -> 9003", "offset": 0x13ce5b0, "expected": bytes.fromhex("e00313aae1031faaf1a00b94f40300aa540000b50a17f99741048052e2030032e00314aae3031faa7bbc0f941f000072e003271ec91d201e"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d6065845260b7ff97f013c03dea1b40f9e82742a9e00741a9fd7bc5a8e00313aac0035fd6")},
    {"description": "DIAG hook: BatBombTrapAction.OnApplyAction: explosion action -> 9003", "offset": 0x143bf80, "expected": bytes.fromhex("e00313aa"), "replacement": bytes.fromhex("8c49fe97")},
    {"description": "DIAG cave: BatBombTrapAction.OnApplyAction -> ApplyExplosion -> 9004", "offset": 0x13ce5e8, "expected": bytes.fromhex("74a640f9740000b5e0031faafe16f997e00314aa8396ff97c00240f9081ca04e089c44398800083608d840b948000035d2a2f897a00240f9"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d8065845252b7ff97f013c03dea1b40f9e82742a9e00741a9fd7bc5a8e00313aac0035fd6")},
    {"description": "DIAG hook: BatBombTrapAction.OnApplyAction -> ApplyExplosion -> 9004", "offset": 0x143bff8, "expected": bytes.fromhex("e00313aa"), "replacement": bytes.fromhex("7c49fe97")},
    {"description": "DIAG cave: CreateExplosionCollision: GetCollisionInitInfo -> 9010 + non-null", "offset": 0x13ce620, "expected": bytes.fromhex("2939281e089c4439a800083608d840b968000035cba2f897a00240f9085c40f9e00313aae1031faa2dc1201e0a2d402d0c0940bd48af0094f40300aa540000b5e316f997"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d1f0000f1e0079f1a416684520000010b41b7ff97f013c03dea1b40f9e82742a9e00741a9fd7bc5a8753240f9c0035fd6")},
    {"description": "DIAG hook: CreateExplosionCollision: GetCollisionInitInfo -> 9010 + non-null", "offset": 0x143c244, "expected": bytes.fromhex("753240f9"), "replacement": bytes.fromhex("f748fe97")},
    {"description": "DIAG cave: CreateExplosionCollision: GetDamageInitInfo -> 9012 + non-null", "offset": 0x13ce664, "expected": bytes.fromhex("e00314aae1031faa68ff1d94041ca04ea01dad4e411daa4e621dab4e831dac4ee0031faa4ab01a940a1ca04e201da94ee0031faaf365409474a640f94009201e0829201e"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d1f0000f1e0079f1a816684520000010b30b7ff97f013c03dea1b40f9e82742a9e00741a9fd7bc5a8f60300aac0035fd6")},
    {"description": "DIAG hook: CreateExplosionCollision: GetDamageInitInfo -> 9012 + non-null", "offset": 0x143c274, "expected": bytes.fromhex("f60300aa"), "replacement": bytes.fromhex("fc48fe97")},
    {"description": "DIAG cave: CreateExplosionCollision: AddCollision -> 9014 + non-null", "offset": 0x13ce6a8, "expected": bytes.fromhex("740000b5e0031faacf16f997e00314aa001da84e3296ff97e00313aabac3ff9774a640f91f000072e003271ec91d201e740000b5e0031faac316f997e00314aacc95ff97"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d1f0000f1e0079f1ac16684520000010b1fb7ff97f013c03dea1b40f9e82742a9e00741a9fd7bc5a8603a00f9c0035fd6")},
    {"description": "DIAG hook: CreateExplosionCollision: AddCollision -> 9014 + non-null", "offset": 0x143c394, "expected": bytes.fromhex("603a00f9"), "replacement": bytes.fromhex("c548fe97")},
    {"description": "DIAG cave: CreateExplosionEffect: IsMine, SyncEffect being built -> 9022", "offset": 0x13ce6ec, "expected": bytes.fromhex("c00240f9081ca04e089c44398800083608d840b94800003597a2f897a00240f92939281e089c4439a800083608d840b96800003590a2f897"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803dc067845211b7ff97f013c03dea1b40f9e82742a9e00741a9fd7bc5a8e00314aac0035fd6")},
    {"description": "DIAG hook: CreateExplosionEffect: IsMine, SyncEffect being built -> 9022", "offset": 0x143c440, "expected": bytes.fromhex("e00314aa"), "replacement": bytes.fromhex("ab48fe97")},
    {"description": "DIAG cave: OnManagedUpdate (_isAction): _damageCollision -> 9030 + non-null", "offset": 0x13ce724, "expected": bytes.fromhex("a00240f9085c40f9e00313aae1031faa2dc1201e0a2d402d0c0940bd0daf0094f40300aa540000b5a816f997e00314aae1031faa2dff1d94041ca04ea01dad4e411daa4e621dab4e"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d683a40f91f0100f1e0079f1ac16884520000010bffb6ff97f013c03dea1b40f9e82742a9e00741a9fd7bc5a8683a40f9c0035fd6")},
    {"description": "DIAG hook: OnManagedUpdate (_isAction): _damageCollision -> 9030 + non-null", "offset": 0x143b750, "expected": bytes.fromhex("683a40f9"), "replacement": bytes.fromhex("f54bfe97")},
    {"description": "DIAG cave: SyncEffect.CreateEffect: InstantiateEffect -> 9040 + non-null", "offset": 0x13ce76c, "expected": bytes.fromhex("831dac4ee0031faa0fb01a940a1ca04e201da94ee0031faab865409473a640f94009201e0829201e730000b5e0031faa9416f997e00313aa001da84efd7b46a9f44f45a9"), "replacement": bytes.fromhex("fd7bbba9e00701a9e82702a9ea1b00f9f013803d1f0000f1e0079f1a016a84520000010beeb6ff97f013c03dea1b40f9e82742a9e00741a9fd7bc5a8f40300aac0035fd6")},
    {"description": "DIAG hook: SyncEffect.CreateEffect: InstantiateEffect -> 9040 + non-null", "offset": 0x160c268, "expected": bytes.fromhex("f40300aa"), "replacement": bytes.fromhex("4109f797")},
    # ---- END DIAGNOSTIC ----
] if os.environ.get("KF_DIAG") == "1" else []

# Isolated ResultManager / ResultScene trace (Gixarde3, 2026-09-17): the state probes plus the region-A log helper and
# the region-E safe logger they `bl` into. Region E lives in LoadDeckSummonModel's body, hence the stub. Kept verbatim
# from the Photon branch; it is NOT compatible with the relocated KF_DIAG set above (overlapping caves), so it is its
# own mode: KF_RESULT_DIAG=1.
RESULT_DIAG_PATCHES_ARM64: list[dict[str, object]] = [
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
        "description": "DIAG: region E (keystone-generated, scripts/re/mkcave.py) in dead body of LoadManager.LoadDeckSummonModel: safe LOG helper that preserves x0-x18/q0-q7/q16-q31 (the region A helper at 0x13BC348 branches here; without it caves clobbered x8 between a method's metadata-init flag load and its tbnz and randomly skipped il2cpp method init -> SIGSEGV fault addr 0x127), plus PerformMove destination-selection trace caves",
        "offset": 0x16e6ed0,
        "expected": bytes.fromhex("f80300aa780000b5e0031faac4b4ec97e00318aae1031faa94cb0294f80300aae00317aae1031faa0715fd97f703002a780000b5e0031faab9b4ec97686a01b0087d45f9020140f9e00318aae103172ad3260d94f70300aa17f8ffb4750000b5e0031faaaeb4ec97086d01d008fd43f9020140f9e00315aae10317aae26a5394c0020036750000b5e0031faaa4b4ec97c869019008c940f9020140f9e00315aae10317aa7e695394f803002a750000b5e0031faa9ab4ec97e86801f008d143f902070011030140f9e00315aae10317aab0695394a1ffff17750000b5e0031faa8fb4ec97286a01b0086145f9030140f9e2030032e00315aae10317aabb69539496ffff17a80351f85a070011e91a805209d93ab8110000140b0000140a0000140900001408000014070000140600001405000014040000140300001402000014010000143f040071011800542dc0e797140040f90fbfe797086b01f008f542f9a00302d1010140f9762816945f07003120010054a80351f808d97ab81f5d0371a100005408008012087d9a4a5a03080b07000014d40000b4e00314aae1031faae2031faa3ab4ec97f4031faa9c070011760000b5e0031faa59b4ec97c81a40b99f03086b2be9ff54750000b5e0031faa53b4ec97a86601d0081544f9e00315aa010140f9a8a303d1836b5394a88353f8a083d23ca183d13c536a01d0196b01d0fc6801d01b6a01f0731246f939a340f99c6f47f97b0f41f9a80317f8a1833aad610240f9a0c302d17c4a1194a00a0036210340f9a0c302d10a4b1194880340f9a00734a9e00308aa70f3ec97f50300aae00315aae1031faaeb813794610340f9a00303d181a45194f60300aa760000b5e0031faa2ab4ec97e00316aae1031faa25620594f603002a750000b5e0031faa23b4ec97b61200b9a86601b0081940f9000140f982e64894f60300aa760000b5e0031faa1ab4ec97e00316aae1031faa0acb0294f60300aab71240b9760000b5e0031faa12b4ec97486c01f0080540f9020140f9e00316aae103172a2c260d94f60300aa760000b5e0031faa08b4ec97e00316aae1031faaaeacfd97a01600b9886701b0085d44f9010140f9a00303d154a45194a01a00b9486d01d0b65e4229081940f9000140f934f3ec97f80300aae86601f008a944f9020140f9e00318aae10315aae3031faad8682b94a0c350b8e1031faa29fafc97e303002ae003162ae103172ae20318aa42f0ff97a9ffff17a90351f85a0700116830805228d93ab8140000140e000014"),
        "replacement": bytes.fromhex("ff0309d1fd7b00a9e00701a9e20f02a9e41703a9e61f04a9e82705a9ea2f06a9ec3707a9ee3f08a9f04709a9f25300f9e08705ade28f06ade49707ade69f08adf0c709adf2cf0aadf4d70badf6df0cadf8e70dadfaef0eadfcf70fadfeff10ade303002a6000805281030010a2030010ccbce797feff50adfcf74fadfaef4eadf8e74dadf6df4cadf4d74badf2cf4aadf0c749ade69f48ade49747ade28f46ade08745adf25340f9f04749a9ee3f48a9ec3747a9ea2f46a9e82745a9e61f44a9e41743a9e20f42a9e00741a9fd7b40a9ff030991c0035fd64b46444941470000763d256400000000ff0309d1fd7b00a9e00701a9e20f02a9e41703a9e61f04a9e82705a9ea2f06a9ec3707a9ee3f08a9f04709a9f25300f9e08705ade28f06ade49707ade69f08adf0c709adf2cf0aadf4d70badf6df0cadf8e70dadfaef0eadfcf70fadfeff10ad00a00f11cb54f397feff50adfcf74fadfaef4eadf8e74dadf6df4cadf4d74badf2cf4aadf0c749ade69f48ade49747ade28f46ade08745adf25340f9f04749a9ee3f48a9ec3747a9ea2f46a9e82745a9e61f44a9e41743a9e20f42a9e00741a9fd7b40a9ff030991e803002ac0035fd6ff0309d1fd7b00a9e00701a9e20f02a9e41703a9e61f04a9e82705a9ea2f06a9ec3707a9ee3f08a9f04709a9f25300f9e08705ade28f06ade49707ade69f08adf0c709adf2cf0aadf4d70badf6df0cadf8e70dadfaef0eadfcf70fadfeff10ad60e640b9003011119654f397e01340b9005014119354f39760ea40b99154f397feff50adfcf74fadfaef4eadf8e74dadf6df4cadf4d74badf2cf4aadf0c749ade69f48ade49747ade28f46ade08745adf25340f9f04749a9ee3f48a9ec3747a9ea2f46a9e82745a9e61f44a9e41743a9e20f42a9e00741a9fd7b40a9ff03099168864339c0035fd6ff0309d1fd7b00a9e00701a9e20f02a9e41703a9e61f04a9e82705a9ea2f06a9ec3707a9ee3f08a9f04709a9f25300f9e08705ade28f06ade49707ade69f08adf0c709adf2cf0aadf4d70badf6df0cadf8e70dadfaef0eadfcf70fadfeff10ad0000381e00401f115c54f3970109281e62092b1e2128221e82092c1e2128221e21c0211e2000381e00e02e115354f397feff50adfcf74fadfaef4eadf8e74dadf6df4cadf4d74badf2cf4aadf0c749ade69f48ade49747ade28f46ade08745adf25340f9f04749a9ee3f48a9ec3747a9ea2f46a9e82745a9e61f44a9e41743a9e20f42a9e00741a9fd7b40a9ff030991031ca04ec0035fd6"),
    },
    {
        "description": "DIAG only: stub LoadDeckSummonModel (region D/E caves live in its body; production builds keep it so disc pets load)",
        "offset": 0x016E6CA8,
        "expected": bytes.fromhex("fc6fbaa9"),
        "replacement": bytes.fromhex("c0035fd6"),  # ret
    },
    {
        "description": "DIAG: ResultManager Begin/Collect/predicate state logger caves (8000/8100/8200)",
        "offset": 0x1571000,
        "expected": bytes.fromhex("089c44398800083608d840b9480000355418f297e0031faa00ae7194f30300aa530000b5728cf297e00313aae1031faa660f7294f30300aa530000b56c8cf297e00313aae1031faa142d07941f04007121020054487301f0086d44f9000140f9089c44398800083608d840b9480000353c18f297e0031faaab1f0194e1031faabc670294"),
        "replacement": bytes.fromhex("fd7bbfa900e883520000080bcf2cf997681240b9fd7bc1a8c0035fd61f2003d5fd7bbfa980f483520000080bc72cf997881240b9fd7bc1a8c0035fd61f2003d5f37bbfa9f30300aa687640b9090184522001080bbd2cf99768264e291f01096be0079f1af37bc1a8c0035fd61f2003d51f2003d51f2003d51f2003d51f2003d51f2003d5"),
    },
    {"description": "DIAG ResultManager.BeginAsync state -> 8000+state", "offset": 0x18A66F4, "expected": bytes.fromhex("681240b9"), "replacement": bytes.fromhex("432af397")},
    {"description": "DIAG ResultManager.CollectResultInfoAsync state -> 8100+state", "offset": 0x18A6B60, "expected": bytes.fromhex("881240b9"), "replacement": bytes.fromhex("3029f397")},
    {"description": "DIAG ResultScene asset predicate -> 8200+loadedCount", "offset": 0x18A4924, "expected": bytes.fromhex("08244e29"), "replacement": bytes.fromhex("c731f317")},
    {
        "description": "DIAG: ResultScene.PreBeginAsync state logger cave (8300+state)",
        "offset": 0x1571080,
        "expected": bytes.fromhex("1f2003d51f000072a80080520005881a02000014e0031f2afd7b41a9"),
        "replacement": bytes.fromhex("fd7bbfa9800d84520000080baf2cf997681240b9fd7bc1a8c0035fd6"),
    },
    {
        "description": "DIAG ResultScene.PreBeginAsync state -> 8300+state",
        "offset": 0x18B1714,
        "expected": bytes.fromhex("681240b9"),
        "replacement": bytes.fromhex("5bfef297"),
    },
] if os.environ.get("KF_RESULT_DIAG") == "1" else []

if DIAG_PATCHES_ARM64 and RESULT_DIAG_PATCHES_ARM64:
    raise SystemExit("KF_DIAG=1 and KF_RESULT_DIAG=1 are mutually exclusive (their logger caves overlap)")


# Basic-attack fire rate. The interval between two shots/swings is NOT master data: every XxxAttackAction..cctor builds
# its static float[] ATTACK_INTERVAL from immediates (WeaponAttackActionBase.SetAttackInterval then divides it by the
# ConditionActionParameter.AttackSpeedRate of any active condition 28 and by PlayerParameter._overrideAttackSpeed).
# The ranged weapons have a single value, written by a `movz w8`/`movk w8` pair (or one `movz ... lsl #16` for
# Drone / RocketLauncher, whose value must then be exactly representable with a zero low half: 0.5, 0.625, 0.75,
# 0.875, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0 ...). Edit the seconds below and rebuild the APK. Melee combos keep
# their per-hit arrays (RuntimeHelpers.InitializeArray blobs, not patched here).
RANGED_ATTACK_INTERVALS = {
    # weapon: (seconds, address of the movz, address of the movk or None)   -- original values shown
    "TwoGuns":        (0.4, 0x147DBA8, 0x147DBAC),  # Ruriha
    "Gun":            (0.3, 0x168FF14, 0x168FF18),  # Anna
    "Bowgun":         (0.7, 0x15CB508, 0x15CB50C),  # Grenhawk
    "ThrowingStar":   (0.7, 0x1617E6C, 0x1617E70),  # Kite
    "Drone":          (1.0, 0x149EA74, None),       # Owlbert (single-instruction form, original `orr w8, wzr, #0x40000000`)
    "RocketLauncher": (0.75, 0x16F3BEC, None),       # Pitophy (single-instruction form, original `orr w8, wzr, #0x3fc00000`)
    "Laser":          (0.7, 0x16D8AF8, 0x16D8AFC),  # Sid
}
_ORIGINAL_RANGED_ATTACK_INTERVALS = {"TwoGuns": 0.8, "Gun": 0.6, "Bowgun": 1.4, "ThrowingStar": 1.4, "Drone": 2.0,
                                     "RocketLauncher": 1.5, "Laser": 1.4}
_ORIGINAL_SINGLE_INSN = {"Drone": bytes.fromhex("e8030232"), "RocketLauncher": bytes.fromhex("e81f0a32")}  # orr w8, wzr, #imm


def _attack_interval_patches() -> list[dict[str, object]]:
    import struct as _struct
    out = []
    for weapon, (seconds, movz_at, movk_at) in RANGED_ATTACK_INTERVALS.items():
        new_bits = _struct.unpack("<I", _struct.pack("<f", float(seconds)))[0]
        old_bits = _struct.unpack("<I", _struct.pack("<f", _ORIGINAL_RANGED_ATTACK_INTERVALS[weapon]))[0]
        if new_bits == old_bits:
            continue
        lo, hi = new_bits & 0xFFFF, new_bits >> 16
        olo, ohi = old_bits & 0xFFFF, old_bits >> 16
        if movk_at is None:
            if lo != 0:
                raise SystemExit(f"{weapon}: {seconds} s needs a low half; only *.0/.25/.5/.75-style floats fit the single movz")
            out.append({"description": f"{weapon} basic-attack interval {seconds} s (movz lsl #16)", "offset": movz_at,
                        "expected": _ORIGINAL_SINGLE_INSN[weapon], "replacement": _struct.pack("<I", 0x52A00008 | (hi << 5))})
        else:
            out.append({"description": f"{weapon} basic-attack interval {seconds} s (movz)", "offset": movz_at,
                        "expected": _struct.pack("<I", 0x52800008 | (olo << 5)), "replacement": _struct.pack("<I", 0x52800008 | (lo << 5))})
            out.append({"description": f"{weapon} basic-attack interval {seconds} s (movk)", "offset": movk_at,
                        "expected": _struct.pack("<I", 0x72A00008 | (ohi << 5)), "replacement": _struct.pack("<I", 0x72A00008 | (hi << 5))})
    return out


# Matchmaking flow. The offline set bridges matchmaking completion straight into a local (bot-filled) room and never
# touches Photon; the Photon set joins the room on a LuxonServer after /battle/start. They cannot coexist in one
# binary (whichever callback fires first wins, the other flow hangs in the lobby), so KF_PHOTON=1 selects the
# Photon flow and drops the six offline bridge patches; the default keeps the offline flow. Everything else
# (crash guards, result scene, RPC handling) is installed in both flavours.
PHOTON_FLOW = os.environ.get("KF_PHOTON") == "1"


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
        *([{
            "description": "diagnostic: transition to GameScene via ChangeGameSceneSync at end of ApplyBattleProperties",
            "offset": 0x17A2430,
            "expected": bytes.fromhex("c0035fd6"),  # ret
            "replacement": bytes.fromhex("0f03f517"),  # b #0x14e306c (ChangeGameSceneSync)
        }] if os.environ.get("KF_FORCE_GAME_SCENE") == "1" else []),
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
        *([{
            "description": "bypass _isUnloading check in LoadManager.LoadCacheAsync so scene transition models are always queued",
            "offset": 0x16E2AD8,
            "expected": bytes.fromhex("88724039a8000034"),
            "replacement": bytes.fromhex("060000141f2003d5"),
        }] if os.environ.get("KF_UNLOAD_BYPASS") == "1" else []),
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
            "replacement": bytes.fromhex("19000014"),  # b #0x13ea0b8
        },
        {
            # The GuardianParameter row predicate compares rank AND ArchiveData.BattleRuleInfo.MatchType, which is null
            # at that point; we serve a single row, so accept the first one.
            "description": "NormalMatchingController.<CallbackBattleStartSuccess>b__46_0 (GuardianParameter predicate) -> true",
            "offset": 0x13ED894,
            "expected": bytes.fromhex("f50f1df8f44f01a9"),
            "replacement": bytes.fromhex("20008052c0035fd6"),  # mov w0, #1; ret
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
            # b__6 is the WaitWhile right before GameManager.InitializeUI. Its original condition
            # !IsCreatedCommonObject(true) also covers crystals/gimmicks (never "created" in the offline room, so it
            # was stubbed to false), but skipping it entirely made InitializeUI run before the guardians finished
            # ObjectManager.AddObjectAsync: GuardianHpGaugePresenter.Initialize only builds gauges for the NPCs
            # present at that moment, so the turrets had no HP bar. Wait for IsCreatedGuardian(this) instead
            # (true when ObjectManager.GetNpcs().Count >= the field's guardian points, or the field has none).
            "description": "GameManager.<BeginAsync>b__6: wait for IsCreatedGuardian instead of IsCreatedCommonObject (guardian HP gauges need the NPCs registered before InitializeUI)",
            "offset": 0x01579C68,
            "expected": bytes.fromhex("53d6ff97"),  # bl IsCreatedCommonObject
            "replacement": bytes.fromhex("39ab1294"),  # bl GameManagerBase<GameManager>.IsCreatedGuardian
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
            # EndAsync clears the reconnect state after the Photon room has
            # already been reset.  Offline/private-server rooms never create
            # GameManager._reconnectInfo, so SetReconnectState(0) throws and
            # aborts the coroutine before ResultScene can request
            # /battle/result.  This call is cleanup-only; skip it at this one
            # call site and let the rest of EndAsync continue normally.
            "description": "skip EndAsync reconnect-state cleanup when offline rooms have no ReconnectInfo",
            "offset": 0x0157AC0C,
            "expected": bytes.fromhex("a9e5ff97"),  # bl GameManager.SetReconnectState
            "replacement": bytes.fromhex("1f2003d5"),  # nop
        },
        {
            # ResultManager.BeginAsync waits for a Photon-instantiated
            # ResultActionManagerRPCController before it can finish loading
            # ResultScene. Luxon does not reproduce Photon scene-object
            # instantiation, so that optional social-action controller never
            # appears and the result screen remains behind Cargando forever.
            # The controller is not needed to render winners, losers or stats;
            # make only this wait predicate complete immediately.
            "description": "skip ResultScene wait for optional Photon result-action RPC object",
            "offset": 0x018A48F4,
            "expected": bytes.fromhex("08104139e8000035"),
            "replacement": bytes.fromhex("e0031f2ac0035fd6"),  # mov w0, wzr; ret
        },
        {
            # ResultScene normally wraps ResultManager in
            # SystemManager.RegisterManagerAsync. That helper treats an
            # already-present singleton as a completed no-op, so a stale
            # ManagerInfo can leave the scene on Cargando without ever
            # resuming ResultManager.BeginAsync. ResultManager's three managed
            # tick methods are empty; start its initialization coroutine
            # directly at this scene-specific call site. ResultUIManager still
            # follows the normal registration path immediately afterwards.
            "description": "start ResultManager.BeginAsync directly instead of skipping it when SystemManager already contains the singleton",
            "offset": 0x018B18C4,
            "expected": bytes.fromhex("88111094"),  # bl SystemManager.RegisterManagerAsync
            "replacement": bytes.fromhex("d1b7ff97"),  # bl ResultManager.BeginAsync
        },
        {
            # BeginAsync snapshots PhotonUtil.IsJoinedRoom into
            # _isChangedResult immediately after ResultScene is entered.  Room
            # teardown races the scene transition: whichever peer observes the
            # room as already left stores false, skips CollectResultInfoAsync's
            # HTTP result request, and remains on Cargando while the other peer
            # renders normally.  Result collection itself is HTTP/local and is
            # valid after Photon teardown, so keep this per-scene gate true on
            # both clients.  This avoids depending on peer teardown ordering.
            "description": "collect ResultScene data even when Photon room teardown wins the transition race",
            "offset": 0x018A69F0,
            "expected": bytes.fromhex("a8020012"),  # and w8,w21,#1 (IsJoinedRoom)
            "replacement": bytes.fromhex("28008052"),  # mov w8,#1
        },
        {
            # CallbackDisconnected/CallbackLeftRoom may clear the same flag
            # while CollectResultInfoAsync is running.  Aborting BeginAsync at
            # this point leaves the loading overlay up even when result data
            # and assets are otherwise ready. Photon is no longer required by
            # the local/HTTP result presentation path.
            "description": "do not abort ResultManager.BeginAsync when Photon disconnects during result collection",
            "offset": 0x018A682C,
            "expected": bytes.fromhex("a8030034"),  # cbz w8, completion
            "replacement": bytes.fromhex("1f2003d5"),  # nop
        },
        {
            # The collection coroutine checks the flag a second time directly
            # before SendFollowSearch/SendResult. Let the HTTP request run even
            # if room teardown has already delivered its callback.
            "description": "send battle result after Photon teardown instead of silently ending collection",
            "offset": 0x018A7B8C,
            "expected": bytes.fromhex("28110034"),  # cbz w8, coroutine completion
            "replacement": bytes.fromhex("1f2003d5"),  # nop
        },
        {
            # BeginActionTargeting already tolerates a missing _skillAction,
            # but its update used to dereference it unconditionally. The v18
            # whole-method return also removed UpdateTargeting and the Ready /
            # Cancel transitions for valid human discs. Keep the original body
            # and skip only the absent reference, using its existing epilogue.
            # x20 is null here, so GetPlayerActionInfo receives the normal
            # no-action value. No cave or virtual method is replaced.
            "description": "guard missing skill action while preserving disc targeting and Ready transitions",
            "offset": 0x017F3214,
            "expected": bytes.fromhex("740000b5e0031faaf483e897"),
            "replacement": bytes.fromhex("940500b41f2003d51f2003d5"),  # cbz x20, #0x17f32c4; nop; nop
        },
        {
            "description": "guard missing skill action after targeting callback using existing epilogue",
            "offset": 0x017F3260,
            "expected": bytes.fromhex("750000b5e0031faae183e897"),
            "replacement": bytes.fromhex("350300b41f2003d51f2003d5"),  # cbz x21, #0x17f32c4; nop; nop
        },
        {
            "description": "guard missing skill parameter after targeting without disabling valid disc actions",
            "offset": 0x017F327C,
            "expected": bytes.fromhex("550000b5db83e897"),
            "replacement": bytes.fromhex("550200b41f2003d5"),  # cbz x21, #0x17f32c4; nop
        },
        {
            # Runtime auto64: the private master manifest omits
            # BattleRuleFlagFlightScore. GetScore throws every update and in
            # BattleEnd/CreateBattleResult. Missing optional personal-score
            # data must not abort those callers. Return neutral personal score
            # only for an absent table/row; preserve every valid coefficient
            # and the independent team-goal/pickup/respawn paths. Do not invent
            # original bonus weights to fill an unavailable master.
            "description": "return neutral personal flag score when its master table is absent",
            "offset": 0x015F24D8,
            "expected": bytes.fromhex("e0031faa4487f097"),
            "replacement": bytes.fromhex("e0031f2aa2000014"),  # mov w0,wzr; b existing epilogue 0x15f2764
        },
        {
            "description": "return neutral personal flag score when both selected and fallback master rows are absent",
            "offset": 0x015F2518,
            "expected": bytes.fromhex("e0031faa3487f097"),
            "replacement": bytes.fromhex("e0031f2a92000014"),
        },
        {
            # x0 is the null getter result on this exception-only branch.
            "description": "guard flag score fallback table disappearing during result collection",
            "offset": 0x015F27B0,
            "expected": bytes.fromhex("8f86f097"),
            "replacement": bytes.fromhex("edffff17"),  # b existing epilogue, w0 already zero
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
        *([{
            "description": "ponytail: stub GameReadyScene.GetGameReadyAnimationClip entry to return null, one guard covers all three null-throw sites inside (0x176035c/0x1760378/0x17603cc); sole caller 0x175fa7c skips clip-use region via 0x175fab4 guard",
            "offset": 0x01760304,
            "expected": bytes.fromhex("ffc300d1f44f01a9"),  # sub sp, sp, #0x30; stp x20, x19, [sp, #0x10]
            "replacement": bytes.fromhex("e0031faac0035fd6"),  # mov x0, xzr; ret (return null clip)
        }] if not READY_SCENE else []),
        *([{
            "description": "ponytail: skip clip-use region when clip is null (cbz x26 to 0x175fb88 cbnz, falls to throw-safe path via existing checks), non-null falls through via b to 0x175fac0; lands before x25 null-check so str preserves loop state (x24/x25) and reaches timeline tail 0x175fdc4",
            "offset": 0x0175FAB4,
            "expected": bytes.fromhex("7a0000b5e0031faaccd1ea97"),  # cbnz x26, #0x175fac0; mov x0, xzr; bl throw
            "replacement": bytes.fromhex("ba0600b4020000141f2003d5"),  # cbz x26, #0x175fb88; b #0x175fac0; nop
        }] if not READY_SCENE else []),
        *([{
            "description": "ponytail: force Play past w2 gate (bypass tbz w21 at 0x175aff4, sole caller w2=0) so shared-gate result is ignored and setup runs; downstream cbnz null-throws preserved, epilogue still reachable via normal ret",
            "offset": 0x0175AFF4,
            "expected": bytes.fromhex("55030036"),  # tbz w21, #0, #0x175b05c (epilogue ret)
            "replacement": bytes.fromhex("1f2003d5"),  # nop (always fall through to state-check/setup)
        }] if not READY_SCENE else []),
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
        *([{
            "description": "ponytail: force Play gate 0x175b530 to always return false (nop tbz at 0x175b598 falls through to mov w0,wzr, skipping the 0x23ecf30-gated true path with its x19 null-throw at 0x175ba8); Play then uses AFE4 state-check + 0x175aff4 nop to reach setup",
            "offset": 0x0175B598,
            "expected": bytes.fromhex("60000036"),  # tbz w0, #0, #0x175b5a4 (little-endian: 36 00 00 60)
            "replacement": bytes.fromhex("1f2003d5"),  # nop (fall through to return false)
        }] if not READY_SCENE else []),
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
        # Offline battle start: the ponytail patches skip the GameReadyScene
        # timeline, so its completion event never publishes PlayerState Readied.
        # Re-emit that completion at countdown start. In this patched flow the
        # asynchronous Readied update can land after Playing, so accept either
        # state when GameManager writes RoomStartTime.
        *([{
            "description": "cave: call GameManager.CompleteGameReady, then run displaced PlayGoAnimation state load",
            "offset": 0x01570EF8,
            "expected": bytes.fromhex("e0031faa5717fc9760000036e0031f3264000014487801d008e142f9000140f9089c4439"),
            "replacement": bytes.fromhex("fd7bbfa9687301b0087941f9000140f94abe4e94fb060094fd7bc1a868b240b9c0035fd6"),
        }] if not READY_SCENE else []),
        *([{
            "description": "GameStartAnimation.PlayGoAnimation: complete GameReadyScene at countdown start",
            "offset": 0x017630EC,
            "expected": bytes.fromhex("68b240b9"),  # ldr w8, [x19, #0xb0]
            "replacement": bytes.fromhex("8337f897"),  # bl #0x1570ef8
        }] if not READY_SCENE else []),
        *([{
            "description": "GameManager.UpdateState: write RoomStartTime when local PlayerState is at least Readied",
            "offset": 0x0156EB14,
            "expected": bytes.fromhex("1f10007121050054"),  # cmp w0, #4; b.ne #0x156ebbc
            "replacement": bytes.fromhex("1f0c00712b050054"),  # cmp w0, #3; b.lt #0x156ebbc
        }] if not READY_SCENE else []),
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
        *([{
            "description": "set NormalMatchingJoinBattleRoomState.GetDelayTime to 0.0s to eliminate lobby join stagger",
            "offset": 0x13EFE74,
            "expected": bytes.fromhex("ff4302d1e82300fd"),  # sub sp, sp, #0x90; str d8, [sp, #0x40]
            "replacement": bytes.fromhex("e003271ec0035fd6"),  # fmov s0, wzr; ret
        }] if PHOTON_FLOW else []),
        {
            "description": "safely bypass ReconnectInfo null dereference in GameManager.InitializeReconnect",
            "offset": 0x1570164,
            "expected": bytes.fromhex("f70f1cf8"),  # str x23, [sp, #-0x40]!
            "replacement": bytes.fromhex("c0035fd6"),  # ret
        },
        {
            # InitializeReconnect is intentionally disabled above because the
            # preserved demo response has no ReconnectInfo.  Leaving its frame
            # update enabled makes it invoke the null state delegate at +0xa0
            # every frame, flooding logcat and eventually entering the forced
            # disconnect path before gameplay can begin.
            "description": "disable GameManager.UpdateReconnect when reconnect initialization is bypassed",
            "offset": 0x156E89C,
            "expected": bytes.fromhex("f44fbea9"),  # stp x20, x19, [sp, #-0x20]!
            "replacement": bytes.fromhex("c0035fd6"),  # ret
        },
        {
            # The original client force-disconnects after only 20 seconds of
            # unrecognised flight input. Emulator swipes made during the long
            # translated team presentation do not reset this counter, so the
            # modal can appear as the first playable frame is reached.
            "description": "disable PlayerCharacter.UpdateNoInputTime force-disconnect watchdog",
            "offset": 0x13CE888,
            "expected": bytes.fromhex("e80f1dfc"),  # str d8, [sp, #-0x30]!
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
        *([{
            "description": "dispatch CallbackGetAssignments: Case 0 when Assignment.connection_ is empty, Case 1 when populated",
            "offset": 0x13EE484,
            "expected": bytes.fromhex("df120071280b0054c9f100b0e803162a298104912879a8b80801098b00011fd6"),
            # GetAssignmentsResponse.assignment_ is at +0x18 and Assignment.connection_
            # is also at +0x18. The latter is an Il2CppString whose length is at +0x10;
            # protobuf uses a non-null empty-string object for Stages 1/2, so testing only
            # the connection_ pointer incorrectly classifies those updates as Success.
            "replacement": bytes.fromhex("880e40f9480200b4090d40f9090200b4291140b9c9010034170000141f2003d5"),
        }] if PHOTON_FLOW else []),
        *([{
            "description": "commit Stage 3 through the captured NormalMatchingController instead of the racy MatchingManager singleton",
            "offset": 0x13EE548,
            # The original success tail restores the callback frame and calls
            # MatchingManager.SetState(4). That static helper first checks
            # SingletonMonoBehaviour.HasInstance and silently returns while
            # MatchingScene is replacing the singleton, losing Stage 3 after
            # GetAssignments has already been cancelled. The display-class
            # callback still holds the authoritative NormalMatchingController
            # in x19 here, so dispatch its virtual SetState(4) directly before
            # restoring the frame. The overwritten Error case is unreachable:
            # the guarded dispatch above only selects Update or Success.
            "expected": bytes.fromhex("fd7b43a9f44f42a9f65741a9e0031e32e1031faaf70744f80dd40314740a40f9740000b5e0031faa"),
            "replacement": bytes.fromhex("680240f9e00313aa8100805203895aa960003fd6fd7b43a9f44f42a9f65741a9f70744f8c0035fd6"),
        }] if PHOTON_FLOW else []),
        {
            # LoadDeckSummonModel successfully enqueues the eight distinct summon
            # bundles used by the two human/bot decks.  Its completion callback
            # only pre-instantiates throwaway copies into ModelManager's cache;
            # on the x86_64 AVD through ndk_translation that callback never
            # returns, so LoadManager remains at 8 even though the bundles are
            # present in the Octo cache.  Keep the bundle loads and their normal
            # queue accounting, but skip this optional pre-instantiation.  The
            # actual deck/SkillMaster data and runtime disc instantiation paths
            # are untouched.
            "description": "skip summon-model cache warmup callback so completed deck bundle loads can drain LoadManager.Remaincount",
            "offset": 0x016EA480,
            "expected": bytes.fromhex("f85fbca9f65701a9"),
            "replacement": bytes.fromhex("c0035fd61f2003d5"),  # ret; nop
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
        # ---- offline / bot combat patches (tanuki-discs, ea19edf) ----
        # Everything from here to the DIAG splats comes from the offline/solo-battle work: bot special skills, gym
        # mannequins, bat-bomb traps, basic-attack combos, null-safe GetDisplayAngles, GetRange master fallback ...
        {
            # Octo.OctoFullSettings..ctor copies OctoSettings.maxParallelDownload (a ScriptableObject value we cannot
            # edit in data.unity3d). ~10 parallel transfers over a slow remote link starve each other and trip the
            # downloader's read timeout; 4 keeps the per-file throughput up (scripts/patch-octo-http-timeout.py
            # raises the timeout itself).
            "description": "OctoFullSettings..ctor: MaxParallelDownload = 4 instead of the OctoSettings asset value",
            "offset": 0x2746F30,
            "expected": bytes.fromhex("884640b9"),  # ldr w8, [x20, #0x44]
            "replacement": bytes.fromhex("88008052"),  # mov w8, #4
        },
        {
            # Octo.BaseDownloadRequest<T>..cctor: StallTimeout = 10.0f. The TimeoutWatcher coroutine aborts a file
            # download (Error 2, "octo.network.timeout") when _receivedLength has not grown for that long, and the
            # DownloadScene then shows "communication error". On a slow mobile link with 4 parallel transfers a
            # single TCP stall easily exceeds 10 s (server log 2026-09-14 04:01: every cycle died on the first file
            # that took >10 s), so give the stream 120 s before declaring it dead.
            "description": "BaseDownloadRequest..cctor: StallTimeout = 120 s instead of 10 s",
            "offset": 0x222DCEC,
            "expected": bytes.fromhex("0924a852"),  # mov w9, #0x41200000 (10.0f)
            "replacement": bytes.fromhex("095ea852"),  # mov w9, #0x42f00000 (120.0f)
        },
        *([{
            "description": "bridge matchmaking completion to offline battle room and launch GameScene",
            "offset": 0x13EF4C0,
            "expected": bytes.fromhex("687e019008a141f9000140f947c554948002003657820190f78243f9e00240f9d4c45494f40300aa540000b5"),
            "replacement": bytes.fromhex("e0031f2a01a68e52e2031faadca01394fd7b43a9f44f42a9f65741a9f70744f8c0035fd61f2003d51f2003d5"),
        }] if not PHOTON_FLOW else []),
        *([{
            "description": "force MatchingManager.IsRoomLocalPlayerMaster to true",
            "offset": 0x14E16AC,
            "expected": bytes.fromhex("e0031faa75d50f14"),  # mov x0, xzr; b #0x18d6c84
            "replacement": bytes.fromhex("20008052c0035fd6"),  # mov w0, #1; ret
        }] if not PHOTON_FLOW else []),
        *([{
            "description": "store battleRuleInfo and battleInfo into ArchiveData and launch ChangeGameSceneSync in ApplyBattleProperties",
            "offset": 0x17A2148,
            "expected": bytes.fromhex("ffc301d1fc6f01a9fa6702a9f85f03a9f65704a9f44f05a9fd7b06a9fd830191557901b0a87a5d39f40302aaf30301aa"),
            "replacement": bytes.fromhex("f44fbea9fd7b01a9f30301aaf40302aae00314aa94a90394aee96894131801f9141c01f9fd7b41a9f44fc2a8be03f517"),
        }] if not PHOTON_FLOW else []),
        *([{
            "description": "bypass IsMatched check in NormalMatchingController.BattleStart to allow local battle setup",
            "offset": 0x13EB238,
            "expected": bytes.fromhex("00080037"),
            "replacement": bytes.fromhex("1f2003d5"),
        }] if not PHOTON_FLOW else []),
        *([{
            "description": "bypass IsRoomLocalPlayerMaster check in NormalMatchingController.BattleStart to allow local battle setup",
            "offset": 0x13EB25C,
            "expected": bytes.fromhex("e0060036"),
            "replacement": bytes.fromhex("1f2003d5"),
        }] if not PHOTON_FLOW else []),
        *([{
            "description": "bypass premature scene change in CallbackRoomPropertiesUpdate on status 3",
            "offset": 0x13EB720,
            "expected": bytes.fromhex("400a0054"),
            "replacement": bytes.fromhex("1f2003d5"),
        }] if not PHOTON_FLOW else []),
        {
            # GetDisplayAngles = _modelCtr.t.eulerAngles + _displayOffsetAngles, i.e. the direction the kicker faces.
            # It used to be stubbed to Vector3.zero (crash on combat start while _modelCtr was still null), which made
            # WeaponAttackActionBase.IsAttack compare the *world* yaw/pitch of the target against the idle limits
            # (60/30 deg) instead of the angle relative to the kicker: basic attacks only fired when the enemy happened
            # to sit in world +Z, melee never chained a combo (2026-09-20). Cave = null-check _modelCtr, then the
            # original prologue and a jump back into the method; null still returns zero.
            "description": "cave: null-safe PlayerBoneController.GetDisplayAngles (dead body of HomeSummonModelController.SetModel, after the AI cave)",
            "offset": 0x159D3E0,
            "expected": bytes.fromhex("a34d1294781640f9f70300aa780000b5e0031faa7edbf197e00318aae1031faa0a063994f80300aad70000b4"),
            "replacement": bytes.fromhex("080840f9c80000b4ed33bb6deb2b016de923026df44f03a9f07bf817e003271ee103271ee203271ec0035fd6"),
        },
        {
            # SkillParameterBase.GetRange returned EventItemGroup._targetRange, a value baked into the per-kicker
            # actioneditor/aed_NNN bundle. Nine of those bundles are donor copies (docs/DISC_ACTION_TIMELINES.md) whose
            # kicker-skill group carries the DONOR's id, so for kickers 2,3,6,7,9,10,12,13,14 the own kicker skill has no
            # group and GetRange was 0: Hitagi's no-target warp distance (JapaneseSwordSkillAction.OnBeginFinish ->
            # MoveSphereCollision(forward * GetRange())) was 0, so she never moved (KFDIAG 7710/7711 == 7712, 2026-09-20).
            # New body (same 44 bytes): _targetRange if > 0, else the served masters_skill.json `range` (SkillMasterData
            # +0x34), else 0 - which also makes the kicker-skill range tunable from the balance WebUI.
            "description": "SkillParameterBase.GetRange: fall back to SkillMasterData.range when the aed bundle's _targetRange is 0",
            "offset": 0x184320C,
            "expected": bytes.fromhex("f30f1ef8fd7b01a9fd430091132840f9730000b5e0031faaf243e797605e40bdfd7b41a9f30742f8c0035fd6"),
            "replacement": bytes.fromhex("082840f9880000b4005d40bd0820201ecc000054082040f9680000b4003540bdc0035fd6e003271ec0035fd6"),
        },
        {
            # WeaponAttackActionBase.IsUpdateAction refuses to run the basic attack while PlayerStateNormal.IsCrouch (the
            # DashReady crouch sub-state, entered from InputActionFly whenever CanDash() sees a dash input). On our builds
            # that sub-state shows up ~0.13 s after every swing even when the player is not dashing (KFDIAG 8230 +
            # crouch=YES, 2026-09-20), and each time it resets the combo, so melee never got past hit 2. Let the attack
            # loop keep running through the crouch; the dash itself still interrupts via the Dash sub-state.
            "description": "WeaponAttackActionBase.IsUpdateAction: do not block the basic-attack loop while in the DashReady crouch sub-state",
            "offset": 0x181ACEC,
            "expected": bytes.fromhex("00010037"),  # tbnz w0, #0, #0x181ad0c  (IsCrouch -> return false)
            "replacement": bytes.fromhex("1f2003d5"),  # nop
        },
        {
            "description": "PlayerBoneController.GetDisplayAngles entry -> b null-safe cave (was: stub returning Vector3.zero)",
            "offset": 0x013BC3A8,
            "expected": bytes.fromhex("ed33bb6d"),  # stp d13, d12, [sp, #-0x50]!  (re-executed by the cave)
            "replacement": bytes.fromhex("0e840714"),  # b 0x159d3e0
        },
        {
            # Bots never cast their special skill: PlayerCharacter.CollectSkillsForAI only registers the kicker skill and
            # the deck discs, and the only SS trigger in the game is the human's button (SpecialSkillPresenter.OnClick ->
            # SetState(SpecialSkill) + ApplyForcedAction). This cave runs at the top of PlayerCharacter.UpdateAi (every
            # frame, AI players only via _enableAi): from Normal with Param.SP >= GetMaxSP() and
            # ConditionActionCtr.EnableSpecialSkill it does SetState(13, null) + ApplyForcedAction(info); while in the
            # SpecialSkill state it ends the cut-in itself (SpecialSkillActionBase.OnEndCutScene, only the main
            # player's cut UI raises it, so bots froze in CutStaging forever), fires ExecuteSkillEffect itself one frame
            # later (retail fires it from the cut-in scene's timeline via SetEvents/AddSpecialSkillEvent, so bots' specials
            # had no effect at all) and then presses/releases the execute
            # button once the action reaches AttackStaging; a progress byte in the state routine's padding (+0x3C)
            # fires each step once per cast. While the special runs the cave returns from UpdateAi without running
            # AIPlayerEngine.ManagedUpdate (the engine kept boosting the bot through its special: boost pose in the
            # banner, no pause, animation-event effects never fired).
            # Lives in the dead body of the entry-stubbed HomeSummonModelController.SetModel (0x159D1BC-0x159DAB0).
            # Source (keystone): scripts/re/bot_special_skill_cave.py.
            "description": "cave: gym mannequins (kickerAiParameterId >= 100 or -1 (offline Trial AI) -> AIOption 63) + AI casts its special skill when the SP gauge is full and presses execute in AttackStaging (dead body of HomeSummonModelController.SetModel)",
            "offset": 0x159D200,
            "expected": bytes.fromhex("000140b90333f197e8030032c81e1c39d97401b0394346f9761640f9200340f9089c44398800083608d840b948000035cc67f197e00316aae1031faae2031faa3c3f3994e0030036a87601d0086146f9000140f9211bf297e87101f0081542f9e2031faaf60300aa010140f988043994761600f9760000b5e0031faadcdbf197e00316aae1031faa68063994f60300aae00313aae1031faae97d1394f70300aa760000b5e0031faad1dbf197e00316aae10317aae2031f2ae3031faadab34794200340f9761a40f9089c44398800083608d840b948000035a267f197e00316aae1031faae2031faa123f3994e0030036a87601d0086146f9000140f9f71af297287801b0080d45f9e2031faaf60300aa010140f95e043994761a00f9760000b5e0031faab2dbf197e00316aae1031faa3e063994f60300aae00313aae1031faabf7d1394f70300aa760000b5e0031faaa7dbf197e00316aae10317aae2031f2ae3031faab0b34794887501b008c146f9000140f9089c44398800083608d840b9480000357767f197e0031faa6be5fe97fa7001f05a1b40f9f60300aa480340f9e00308aaf60d4e94f70300aa570000b58fdbf197e00317aae1031faa7ff20794f70300aa570000b589dbf197bb7601b07b0740f9"),
            "replacement": bytes.fromhex("08804339480e003408c440b91f050031600000541f9101718b000054e807805208e400b96a000014fd7bbda9f35301a9f51300f9f30300aae1031faa4cb6f8971f34007180050054a1018052e2031faae00313aab58df897400000b41f780079e00313aae1031faa41b6f897800a0035e00313aae1031faafe83f897000a00b4f50300aae1031faaaadd0694e02b00bde00315aae1031faa0dde06940100221ee02b40bd0020211eab080054e00313aae1031faab2650494200800b4e1031faaa57e0894c0070036e00313aaa1018052e2031faae3031faae19df897000700b4e10300aae00313aae2031faac19ef89733000014e00313aaa1018052e2031faa8a8df897c00500b4f50300aab41240f9740500b4e00314aae1031faa6897fd97e02b00b9a8f240391f04007181020054e8030037a9f6403929050011a9f600393fe101714303005408010032a8f20039880240f908210991e00314aa030540a960003fd6880240f9e00314aae1031f2a03895da960003fd60d000014e02b40b91f080071410100542801103708011e32a8f20039e00315aae1031faa58a9fc97e00315aae1031faa64a9fc97f51340f9f35341a9fd7bc3a8c0035fd6e00313aaf51340f9f35341a9fd7bc3a8f44fbea9c885f817"),
        },
        {
            "description": "PlayerCharacter.UpdateAi entry -> b bot special-skill cave",
            "offset": 0x13BEAEC,
            "expected": bytes.fromhex("f44fbea9"),  # stp x20, x19, [sp, #-0x20]!
            "replacement": bytes.fromhex("c5790714"),  # b 0x159d200
        },
        # AI kickers in this offline flow have a PlayerAnimator whose Unity Animator is null/dead; every
        # PlayerStateNormal.UpdateAction then dies in Animator.SetFloat (NRE raised by libunity, ~40/s) and the
        # exception aborts ObjectManager.ManagedUpdate for the frame, starving every later manager (GameManager
        # never ticks -> no RoomStartTime). Guard the one direct Animator call on that path.
        # (Not installed in KF_RESULT_DIAG builds: that mode's ResultManager logger cave starts at 0x1571000, inside
        # this guard's 28 bytes - the Photon branch never had the guard, so its result trace is reproduced verbatim.)
        *([{
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
        }] if not os.environ.get("KF_RESULT_DIAG") == "1" else []),
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
        # Jay's passive bomb (BatAbilityParameter -> Trap type 10 BatBomb). The explosion needs the TrapInfo fields that
        # DiscSkillParameter..ctor only fills from a sensor Collider clip of the skill's aed_NNN timeline (CollisionMasterId,
        # CollisionStart/EndRadius, CollisionEaseType, CollisionLifeTime, CollisionEffectPath, CollisionType). No captured
        # bundle has a skill_40001 group, so BatBombTrapAction.CreateExplosionCollision asked the ability for collision
        # master 0 (null -> DamageCollisionData with no shape) and the bomb never blew up. Fill them at the end of
        # BatAbilityParameter..ctor (x0 = TrapInfo there, the function tail-calls TrapInfo.set_IsTimeExecute(true)):
        # CollisionMasterId 198 (skill_40001's explosion collider in aed_master), Sphere, start radius 2 -> end radius =
        # served SkillTrap.radius, Linear ease, lifetime = served SkillTrap.interval, effect = served SkillTrap.effectPath,
        # CollisionStartTrigger 1 (SyncEffect.PlayStartEffect only kicks a trigger > 0; the common effects such as
        # ef_cm_006 Dead only play when kicked - 1 = team-0 colour, GetTeamTrigger(team, 1) = 1 + 16 * team).
        # Cave in the dead body of the entry-stubbed PlayerCharacter.UpdateIdleTypeRate, past the DIAG probes (< 0x13CE4B0).
        {
            "description": "cave: BatAbilityParameter..ctor tail -> fill TrapInfo explosion collision fields from skill_40001 / served SkillTrap row, then TrapInfo.set_IsTimeExecute(true)",
            "offset": 0x13CE500,
            "expected": bytes.fromhex("411daa4e621dab4e831dac4ee0031faaa8b01a940a1ca04e201da94ee0031faa5166409474a640f94009201e0829201e740000b5e0031faa2d17f997e00314aa"),
            "replacement": bytes.fromhex("c8188052082400b92800805208b000b9082000b9083000b90010201e001800bd083c40b9081c00b9084840b9083800b9082840f9081400f9210080526c217814"),
        },
        {
            "description": "BatAbilityParameter..ctor tail `b TrapInfo.set_IsTimeExecute` -> b bat-bomb TrapInfo cave",
            "offset": 0x1439B60,
            "expected": bytes.fromhex("e3737614"),
            "replacement": bytes.fromhex("6852fe17"),
        },
        # Second half of the same bug: DiscSkillParameter.HitInfo is only assigned by SetSkillActionHitData from a damage
        # Collider clip of the aed timeline, so for 40001 it is null, BatAbilityParameter.HitInfo = null and every
        # explosion hit died with NullReferenceException in PlayerCharacter.AcceptDamageInfo (DamageCollisionData.OnEnter,
        # emulator logcat 2026-09-20 11:19:43 after KFDIAG 9001..9041 proved the collider itself was created). When the
        # ctor's `HitInfo = discSkillParameter.HitInfo` comes back null, take skill_40001's hit 207 (SlashL + SE 53, the
        # explosion hit) from DiscSkillParameter._hitInfos (Dictionary<int, AttackHitInfo>, +0xA8). Cave in the free
        # tail of the entry-stubbed HomeSummonModelController.SetModel (0x159DA48-0x159DAB0).
        {
            "description": "cave: BatAbilityParameter..ctor HitInfo fallback -> _hitInfos[207] of skill_40001 when the timeline gave none",
            "offset": 0x159DA48,
            "expected": bytes.fromhex("60010036732640f9730000b5e0031faae5d9f19768750190083947f9e00313aa010140f953d50d94f50300aa740000b5"),
            "replacement": bytes.fromhex("400100b5fe0f1ff8805640f9c00000b4e1198052e87001f0084547f9020140f9b7695a94fe0741f8e10300aac0035fd6"),
        },
        {
            "description": "BatAbilityParameter..ctor `mov x1, x0` after get_HitInfo -> bl HitInfo fallback cave",
            "offset": 0x1439AEC,
            "expected": bytes.fromhex("e10300aa"),
            "replacement": bytes.fromhex("d78f0594"),
        },
        # Third piece: the explosion SPFX. EffectManager.InstantiateEffect only knows what LoadManager cached for the
        # match (common effects, kicker effects, the summon effects of the discs in the decks), so a disc explosion such
        # as Hyper Bomb's effect/ds/ef_ds_0037 is only there when someone equips that disc. Preload the bat bomb's served
        # SkillTrap.effectPath (row 40001) together with the common effects: hook LoadManager.LoadInGameCommonEffect
        # before its loop (`mov w21, wzr`) and call LoadEffect(path, null, DestroyFlagExtensions.Flag(1)) exactly like
        # the loop does. Cave in the dead body of the entry-stubbed NormalMatchingController.<CallbackBattleStartSuccess>
        # b__46_0 (stub = first 8 bytes, body free to 0x13ED998, nothing branches in).
        {
            "description": "cave: LoadInGameCommonEffect -> also LoadEffect(SkillTrapMaster[40001].effectPath) (bat-bomb explosion SPFX)",
            "offset": 0x13ed89c,
            "expected": bytes.fromhex("fd7b02a9fd830091f5960190a8ce6139f30301aaf40300aae8000037e88401b0084541f9000140b953f1f797e8030032a8ce2139730000b5e0031faa459af897e00313aae1031faa83830a94f503002ae00314aae1031faae0c90e94bf02006b"),
            "replacement": bytes.fromhex("fd7bbea9687e01f0081940f9000140f9b4cc5494e1031faa35b10e9421889352e2031faafd551194600100b4001840f9200100b4e00b00f920008052e1031faa7fe00894e203002ae00b40f9e1031faa9dd90b94fd7bc2a8f5031f2ac0035fd6"),
        },
        {
            "description": "LoadManager.LoadInGameCommonEffect `mov w21, wzr` -> bl effect-preload cave",
            "offset": 0x16e7a4c,
            "expected": bytes.fromhex("f5031f2a"),
            "replacement": bytes.fromhex("9417f497"),
        },
        *_attack_interval_patches(),
        # Diagnostics: KF_DIAG=1 installs the full KFDIAG probe set (regions relocated out of LoadDeckSummonModel on
        # 2026-09-20 so disc pets still load); KF_RESULT_DIAG=1 installs only the isolated ResultManager/ResultScene
        # trace with its own logger caves (the two are mutually exclusive, see the check below the lists).
        *DIAG_PATCHES_ARM64,
        *RESULT_DIAG_PATCHES_ARM64,
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
            # Under Android's ARM64 native bridge this container destructor
            # reaches native_bridge_free with a buffer owned by Unity's other
            # allocator. Scudo consistently aborts at the return address
            # 0x614C04 with "corrupted chunk header" while entering Matching.
            # The next instruction clears the sole pointer, so skip only the
            # incompatible free instead of globally rebinding Unity allocators.
            "description": "skip native-bridge invalid free in scene-load container destructor",
            "offset": 0x614C00,
            "expected": bytes.fromhex("fbcffb97"),  # bl 0x508bec
            "replacement": bytes.fromhex("1f2003d5"),  # nop
        },
        *([{
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
        # Global allocator rebinding (tanuki-discs, validated for weeks): libunity frees pointers owned by Unity's
        # MemoryManager through the native-bridge libc free from several sites; the targeted nop above covers only
        # 0x614C00 and the merged build aborted at boot on the emulator from libunity+0x32fa10 ("Scudo ERROR:
        # corrupted chunk header", 2026-09-21). On by default; KF_UNITY_NO_ALLOCATOR_REBIND=1 builds without it.
        }] if os.environ.get("KF_UNITY_NO_ALLOCATOR_REBIND") != "1" else []),
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


def patch_metadata(path: Path, base_url: str, authority: str, photon_host: str | None = None) -> list[dict[str, object]]:
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
            # Photon NameServer host (ns.exitgames.com). Defaults to the API host; --photon-host / KF_PHOTON_HOST points it
            # at a separately hosted LuxonServer (e.g. 51.79.241.70, 2026-09-21).
            parsed_host = urlsplit(base_url).hostname
            replacement = photon_host or (parsed_host if parsed_host else "10.0.2.2")
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
    parser.add_argument("--photon-host", required=False, default=os.environ.get("KF_PHOTON_HOST") or None,
                        help="host for the Photon NameServer literal (default: the --base-url host; env KF_PHOTON_HOST)")
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
        "photonHost": args.photon_host,
        "metadata": patch_metadata(args.metadata, base_url, authority, args.photon_host),
        "native": native_reports,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
