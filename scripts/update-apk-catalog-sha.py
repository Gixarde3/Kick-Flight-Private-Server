#!/usr/bin/env python3
"""Refresh the sha256 of the hosted APK entries in config/resources/catalog.json (ids apk-*) after a rebuild.

ResourceCatalogStore checks every catalog entry's sha256 at startup and /health/ready reports a mismatch as
not-ready, so the pinned hash of .local/KickFlight-2.11.0-remote-kickflightsg.apk (entry apk-remote-kickflightsg)
goes stale on every build-all-apks.bat run. Run this (build-all-apks.bat does) and restart the server.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config" / "resources" / "catalog.json"


def main() -> int:
    raw = CATALOG.read_bytes()
    text = raw.decode("utf-8")
    doc = json.loads(text)
    changed = 0
    for entry in doc["resources"]:
        if not str(entry.get("id", "")).startswith("apk-"):
            continue
        path = ROOT / entry["sourcePath"]
        if not path.is_file():
            print(f"{entry['id']}: {entry['sourcePath']} missing, left as is")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if entry.get("sha256") != digest:
            print(f"{entry['id']}: {entry.get('sha256', '')[:12]}... -> {digest[:12]}...")
            entry["sha256"] = digest
            changed += 1
    if changed:
        out = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
        CATALOG.write_bytes(out.replace("\n", "\r\n").encode("utf-8") if b"\r\n" in raw else out.encode("utf-8"))
    print(f"{changed} entr{'y' if changed == 1 else 'ies'} updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
