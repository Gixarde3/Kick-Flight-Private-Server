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


def encode_data(*, octo_id: int, name: str, object_name: str, source: bytes) -> bytes:
    # Octo.Proto.Data field numbers recovered from the IL2CPP protobuf model.
    return b"".join(
        (
            field_varint(1, octo_id),
            field_string(2, name),
            field_string(3, name),
            field_varint(4, len(source)),
            field_varint(5, binascii.crc32(source) & 0xFFFFFFFF),
            field_varint(9, 1),  # ADD
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
    parser.add_argument("--catalog", default="config/resources/catalog.json")
    parser.add_argument("--fixtures", default="config/fixtures")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parent.parent
    definition_path = resolve_path(repo, args.definition)
    direct_config_path = resolve_path(repo, args.direct_config)
    catalog_path = resolve_path(repo, args.catalog)
    fixtures_path = resolve_path(repo, args.fixtures)
    definition = json.loads(definition_path.read_text(encoding="utf-8-sig"))
    direct_config = json.loads(direct_config_path.read_text(encoding="utf-8-sig"))

    server_base_url = direct_config["serverBaseUrl"].rstrip("/")
    parsed_url = urlparse(server_base_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        raise ValueError(f"Invalid serverBaseUrl: {server_base_url}")
    url_format = server_base_url + definition["urlPathFormat"]

    asset_messages: list[bytes] = []
    resource_messages: list[bytes] = []
    managed_catalog_entries: list[dict[str, object]] = []
    next_alias_id = 1000

    for entry in definition["entries"]:
        source_path = resolve_path(repo, entry["sourcePath"])
        source = source_path.read_bytes()
        sha256 = hashlib.sha256(source).hexdigest()
        for alias_index, name in enumerate(entry["names"]):
            octo_id = entry["octoId"] if alias_index == 0 else next_alias_id
            next_alias_id += alias_index > 0
            message = encode_data(
                octo_id=octo_id,
                name=name,
                object_name=entry["objectName"],
                source=source,
            )
            (asset_messages if entry["kind"] == "assetBundle" else resource_messages).append(message)

        managed_catalog_entries.append(
            {
                "id": entry["id"],
                "enabled": True,
                "host": parsed_url.hostname,
                "requestPath": definition["urlPathFormat"].replace("{o}", entry["objectName"]),
                "logicalName": entry["logicalName"],
                "description": entry["description"],
                "sourcePath": Path(entry["sourcePath"]).as_posix(),
                "contentType": "application/octet-stream",
                "sha256": sha256,
            }
        )

    database = field_varint(1, definition["revision"])
    database += b"".join(field_bytes(2, item) for item in asset_messages)
    database += b"".join(field_bytes(4, item) for item in resource_messages)
    database += field_string(5, url_format)

    fixtures_path.mkdir(parents=True, exist_ok=True)
    fixture_paths = []
    for from_revision in definition.get("fromRevisions", [0]):
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
    managed_ids = {entry["id"] for entry in managed_catalog_entries}
    catalog["resources"] = [
        entry for entry in catalog.get("resources", []) if entry.get("id") not in managed_ids
    ] + managed_catalog_entries
    catalog_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Octo revision: {definition['revision']}")
    print(f"URL format:    {url_format}")
    print(f"Fixtures:      {', '.join(str(path) for path in fixture_paths)}")
    print(f"CDN entries:   {len(managed_catalog_entries)} in {catalog_path}")


if __name__ == "__main__":
    main()
