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
NATIVE_PATCHES = {
    "arm64-v8a": {
        "offset": 0x31B5024,
        "expected": bytes.fromhex("28118a9a"),
        "replacement": bytes.fromhex("e8030aaa"),  # mov x8, x10 (always HTTP)
    },
    "armeabi-v7a": {
        "offset": 0x2AC1798,
        "expected": bytes.fromhex("02309f17"),
        "replacement": bytes.fromhex("0000a0e1"),  # mov r0, r0 (skip HTTPS override)
    },
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

    targets: dict[str, tuple[int, int]] = {}
    for index in range(literal_count // 8):
        length, data_index = struct.unpack_from("<II", data, literal_offset + index * 8)
        raw = bytes(data[literal_data_offset + data_index : literal_data_offset + data_index + length])
        try:
            value = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if value in ORIGINAL_LITERALS:
            if value in targets:
                raise ValueError(f"duplicate target literal: {value}")
            targets[value] = (index, data_index)

    missing = sorted(set(ORIGINAL_LITERALS) - set(targets))
    if missing:
        raise ValueError(f"missing expected endpoint literals: {missing}")

    replacement_blob = bytearray()
    report: list[dict[str, object]] = []
    for original, kind in ORIGINAL_LITERALS.items():
        replacement = base_url if kind == "base_url" else f"{authority}/"
        encoded = replacement.encode("utf-8")
        index, _ = targets[original]
        new_data_index = literal_data_count + len(replacement_blob)
        struct.pack_into("<II", data, literal_offset + index * 8, len(encoded), new_data_index)
        replacement_blob.extend(encoded)
        report.append({"literalIndex": index, "from": original, "to": replacement})

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


def patch_native(path: Path, abi: str) -> dict[str, object]:
    patch = NATIVE_PATCHES[abi]
    data = bytearray(path.read_bytes())
    offset = int(patch["offset"])
    expected = bytes(patch["expected"])
    replacement = bytes(patch["replacement"])
    actual = bytes(data[offset : offset + len(expected)])
    if actual != expected:
        raise ValueError(
            f"{abi} native patch guard failed at 0x{offset:x}: "
            f"expected {expected.hex()}, found {actual.hex()}"
        )
    data[offset : offset + len(replacement)] = replacement
    path.write_bytes(data)
    return {"abi": abi, "offset": f"0x{offset:x}", "from": expected.hex(), "to": replacement.hex()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--arm64", required=True, type=Path)
    parser.add_argument("--armv7", required=True, type=Path)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()

    base_url, authority = normalize_base_url(args.base_url)
    report = {
        "baseUrl": base_url,
        "metadata": patch_metadata(args.metadata, base_url, authority),
        "native": [
            patch_native(args.arm64, "arm64-v8a"),
            patch_native(args.armv7, "armeabi-v7a"),
        ],
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
