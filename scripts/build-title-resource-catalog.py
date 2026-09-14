#!/usr/bin/env python3
"""Build the minimal Octo database and local CDN routes for the title screen."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse


def encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("Only non-negative protobuf varints are supported")
    output = bytearray()
    while value > 0x7F:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def field_varint(number: int, value: int) -> bytes:
    return encode_varint(number << 3) + encode_varint(value)


def field_bytes(number: int, value: bytes) -> bytes:
    return encode_varint((number << 3) | 2) + encode_varint(len(value)) + value


def field_string(number: int, value: str) -> bytes:
    return field_bytes(number, value.encode("utf-8"))


def resolve_path(repo: Path, configured_path: str) -> Path:
    candidate = Path(configured_path)
    return candidate.resolve() if candidate.is_absolute() else (repo / candidate).resolve()


# The client's initial download (DownloadScene -> ColorfulManager.GetUpdateResourceNames) only fetches the rows
# tagged "common", "title" (+ "tutorial", "localize"); everything else is loaded on demand from the cache and a
# miss is a native crash. Tag every row "common" so a fresh install downloads the whole catalogue up front and
# no scripts/seed-device-cache.py is needed. tagid is 1-based into Database.tagname (Octo.Data.Item.SetData:
# tags[tagid - 1]) and the names must be unique: Octo keys them in a dictionary and a duplicate throws
# ArgumentException in DataManager.SerializeDatabase, leaving the client database half-applied (phone logcat
# 2026-09-14 09:25:51 - the "communication error" on every download attempt).
DOWNLOAD_TAG_NAMES = ["common"]
DOWNLOAD_TAG_ID = 1


# The Octo client rejects the Chinese-localised bundles on a non-zh device: each `ui/localize/zh/*` file is
# re-requested and the start-up download then aborts with "communication error" (HONOR phone, 2026-09-14; bytes
# verified identical to the catalogue). Neither leaving them untagged nor publishing them with State DELETE kept the
# DownloadScene from queueing them, so they are simply not part of the served database any more (the files stay in
# catalog.json for direct /cdn requests). The es/en client never asks for zh assets anyway.
def is_removed(name: str) -> bool:
    return name.startswith("ui/localize/zh/")


# Octo names a cache file after the item's MD5 (Octo.GetAssetBundleFileName / GetResourceFileName ->
# Item.md5.ToString()), so the alias rows of an entry (same bytes under another name) share one storage file with
# the primary row. The client walks the database rows in list order, 4 downloads at a time (patched
# MaxParallelDownload); a row whose storage file is already complete is skipped instantly, but a row whose twin is
# still in flight (or completed milliseconds ago and not yet registered) is downloaded again, collides with it
# (LockStorage), is retried once and then fails the whole DownloadScene with "communication error" (phone
# 2026-09-14: every failed cycle ended 1-4 s after a duplicated object request; emulator repro at 83%).
# Distance in rows means nothing because cache-skips take no time, so the layout separates twins by real
# downloads instead:
#   1. primaries of entries that have aliases, largest first (they are certain to be complete long before the tail),
#   2. primaries of alias-free entries, in definition order (a buffer of genuine downloads),
#   3. all alias rows (round-robin over the entries) - by now every one of them is a cache hit and is skipped.
# The first surviving name of an entry is its primary (zh names are removed, see is_removed).
def order_rows(rows: list[tuple[int, int, str, int, bytes]]) -> list[bytes]:
    """rows = (entry index, alias index among the emitted names, md5, size, message)."""
    entries_with_aliases = {entry_index for entry_index, alias_index, _, _, _ in rows if alias_index > 0}
    primaries = [row for row in rows if row[1] == 0]
    aliased_primaries = sorted(
        (row for row in primaries if row[0] in entries_with_aliases), key=lambda row: (-row[3], row[0])
    )
    plain_primaries = [row for row in primaries if row[0] not in entries_with_aliases]
    aliases = sorted((row for row in rows if row[1] > 0), key=lambda row: (row[1], row[0]))
    ordered = aliased_primaries + plain_primaries + aliases
    first_seen: dict[str, int] = {}
    for index, (_, alias_index, md5, _, _) in enumerate(ordered):
        if alias_index == 0 and md5 in first_seen:
            raise ValueError(f"two primary entries share content {md5}; make one an alias of the other")
        first_seen.setdefault(md5, index)
    return [message for _, _, _, _, message in ordered]


def encode_data(*, octo_id: int, name: str, object_name: str, source: bytes) -> bytes:
    # Octo.Proto.Data field numbers recovered from the IL2CPP protobuf model.
    return b"".join(
        (
            field_varint(1, octo_id),
            field_string(2, name),
            field_string(3, name),
            field_varint(4, len(source)),
            field_varint(5, binascii.crc32(source) & 0xFFFFFFFF),
            field_varint(7, DOWNLOAD_TAG_ID),  # tagid -> Database.tagname ("common")
            field_varint(9, 1),  # Data.State ADD
            field_string(10, hashlib.md5(source).hexdigest()),
            field_string(11, object_name),
            field_varint(12, 1),
            field_varint(13, 1),
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--definition", default="config/resources/title-minimum.json")
    parser.add_argument("--direct-config", default="config/apk-direct-server.local.json")
    parser.add_argument(
        "--server-base-url",
        help="Override serverBaseUrl (useful for the first-party proxy mode)",
    )
    parser.add_argument("--catalog", default="config/resources/catalog.json")
    parser.add_argument("--fixtures", default="config/fixtures")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parent.parent
    definition_path = resolve_path(repo, args.definition)
    direct_config_path = resolve_path(repo, args.direct_config)
    catalog_path = resolve_path(repo, args.catalog)
    fixtures_path = resolve_path(repo, args.fixtures)
    definition = json.loads(definition_path.read_text(encoding="utf-8-sig"))
    if args.server_base_url:
        server_base_url = args.server_base_url.rstrip("/")
    else:
        direct_config = json.loads(direct_config_path.read_text(encoding="utf-8-sig"))
        server_base_url = direct_config["serverBaseUrl"].rstrip("/")
    parsed_url = urlparse(server_base_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        raise ValueError(f"Invalid serverBaseUrl: {server_base_url}")
    url_format = server_base_url + definition["urlPathFormat"]

    asset_rows: list[tuple[int, int, str, int, bytes]] = []
    resource_rows: list[tuple[int, int, str, int, bytes]] = []
    seen_names: set[str] = set()
    managed_catalog_entries: list[dict[str, object]] = []
    next_alias_id = 1000

    for entry_index, entry in enumerate(definition["entries"]):
        source_path = resolve_path(repo, entry["sourcePath"])
        source = source_path.read_bytes()
        sha256 = hashlib.sha256(source).hexdigest()
        md5 = hashlib.md5(source).hexdigest()
        emitted = 0
        for alias_index, name in enumerate(entry["names"]):
            octo_id = entry["octoId"] if alias_index == 0 else next_alias_id
            next_alias_id += alias_index > 0
            if is_removed(name):
                continue
            if name in seen_names:  # e.g. common_se.awb is listed twice on the placeholder wave bank
                continue
            seen_names.add(name)
            message = encode_data(
                octo_id=octo_id,
                name=name,
                object_name=entry["objectName"],
                source=source,
            )
            (asset_rows if entry["kind"] == "assetBundle" else resource_rows).append(
                (entry_index, emitted, md5, len(source), message)
            )
            emitted += 1

        req_path = definition["urlPathFormat"].replace("{o}", entry["objectName"])
        if not any(m["requestPath"] == req_path for m in managed_catalog_entries):
            managed_catalog_entries.append(
                {
                    "id": entry["id"],
                    "enabled": True,
                    "host": parsed_url.hostname,
                    "requestPath": req_path,
                    "logicalName": entry["logicalName"],
                    "description": entry["description"],
                    "sourcePath": Path(entry["sourcePath"]).as_posix(),
                    "contentType": "application/octet-stream",
                    "sha256": sha256,
                }
            )

    asset_messages = order_rows(asset_rows)
    resource_messages = order_rows(resource_rows)

    fixtures_path.mkdir(parents=True, exist_ok=True)
    fixture_paths = []
    for from_revision in definition.get("fromRevisions", [0]):
        database = field_varint(1, definition["revision"])
        if from_revision < definition["revision"]:
            database += b"".join(field_bytes(2, item) for item in asset_messages)
            database += b"".join(field_string(3, tag) for tag in DOWNLOAD_TAG_NAMES)
            database += b"".join(field_bytes(4, item) for item in resource_messages)
        # Octo calls SetUrls for every successfully decoded database, including
        # an up-to-date response with no asset delta. Omitting this field makes
        # the client overwrite its working CDN formats with an empty string.
        database += field_string(5, url_format)
        fixture_id = (
            f'accepted-octo-title-minimum-{definition["assetVersion"]}-from-{from_revision}'
        )
        fixture = {
            "id": fixture_id,
            "enabled": True,
            "host": "kickflight-resource-api.grenge.jp",
            "method": "GET",
            "path": f'/v1/list/{definition["assetVersion"]}/{from_revision}',
            "statusCode": 200,
            "contentType": "application/x-protobuf",
            "headers": {"x-kickflight-fixture": fixture_id},
            "bodyBase64": base64.b64encode(database).decode("ascii"),
        }
        suffix = "" if from_revision == 0 else f'-from-{from_revision}'
        fixture_path = fixtures_path / f'resource-list-{definition["assetVersion"]}{suffix}.json'
        fixture_path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
        fixture_paths.append(fixture_path)

    catalog = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
    managed_paths = {entry["requestPath"] for entry in managed_catalog_entries}
    catalog["resources"] = [
        entry for entry in catalog.get("resources", []) if entry.get("requestPath") not in managed_paths
    ] + managed_catalog_entries
    catalog_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Octo revision: {definition['revision']}")
    print(f"URL format:    {url_format}")
    print(f"Fixtures:      {', '.join(str(path) for path in fixture_paths)}")
    print(f"CDN entries:   {len(managed_catalog_entries)} in {catalog_path}")


if __name__ == "__main__":
    main()
