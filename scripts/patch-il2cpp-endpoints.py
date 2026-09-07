"""Patch Kick-Flight IL2CPP endpoint literals for a direct private server.

This script is intentionally specific to the preserved 2.11.0 APK. It validates
the metadata layout and native instruction bytes before changing anything.
"""

from __future__ import annotations

import argparse
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
NATIVE_PATCHES: dict[str, list[dict[str, object]]] = {
    "arm64-v8a": [
        {
            "description": "force HTTP for direct server access",
            "offset": 0x31B5024,
            "expected": bytes.fromhex("28118a9a"),
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
            "description": "transition from GrpcGetAssignments response to NormalMatchingJoinBattleRoomState",
            "offset": 0x13EE4EC,
            "expected": bytes.fromhex("e8031e32681a00b93e000014"),
            "replacement": bytes.fromhex("100000141f2003d51f2003d5"),
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
            "expected": bytes.fromhex("f50f1df8"),  # str x21, [sp, #-0x30]!
            "replacement": bytes.fromhex("c0035fd6"),  # ret
        },
        {
            "description": "bypass null _button crash in TitleView.Initialize",
            "offset": 0x31C7950,
            "expected": bytes.fromhex("770000b5e0031faa25328197"),
            "replacement": bytes.fromhex("f70000b4020000141f2003d5"),
        },
        {
            "description": "bypass null _canvasGroup crash in TitleView.Initialize",
            "offset": 0x31C7970,
            "expected": bytes.fromhex("740000b5e0031faa1d328197"),
            "replacement": bytes.fromhex("f40000b4020000141f2003d5"),
        },
        {
            "description": "safely skip weapon attachment when WeaponModelController is null in PlayerCharacter.SetModel",
            "offset": 0x13C941C,
            "expected": bytes.fromhex("770000b5e0031faa722bf997"),
            "replacement": bytes.fromhex("970600b41f2003d51f2003d5"),
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


def patch_native(path: Path, abi: str) -> list[dict[str, object]]:
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
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--arm64", required=True, type=Path)
    parser.add_argument("--armv7", required=True, type=Path)
    parser.add_argument("--arm64-unity", required=False, type=Path)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()

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
