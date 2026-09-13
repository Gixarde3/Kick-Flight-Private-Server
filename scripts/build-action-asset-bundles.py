#!/usr/bin/env python3
"""
build-action-asset-bundles.py

Builds the per-kicker disc action-timeline bundles (actioneditor/aed_NNN.unity3d) that are missing from the
capture. Only aed_001/004/005/008/011 (+ aed_master) were preserved; the client asks for one per kicker
(ResourceUtil.GetActionAssetPath -> LoadManager.LoadActionAsset) and without it every disc runs with an empty
timeline (MoveAttack discs throw in MoveAttackSkillAction..ctor and freeze the kicker, the rest fire nothing).

For each missing kicker the donor bundle (DONORS below) is copied with a fresh serialized-file name -- Unity
refuses to load two bundles that share a CAB name, and MatchingScene loads all 14 action assets at once -- and
its internal names renamed aed_DDD -> aed_NNN. The event data itself (collider/bullet/hit ids, forced-move
parameters) is identical in every captured bundle; only the hand-tuned timings and pet offsets are the donor's.

Output: content/resources/actioneditor/<hex('A'+objectName)>_<md5>.bundle (the Octo cache naming used by
scripts/seed-device-cache.py) and matching entries in config/resources/title-minimum.json. Afterwards bump
"revision" in title-minimum.json (clients with a cached Octo database only fetch rows of a newer revision) and run
    python scripts/build-title-resource-catalog.py
to regenerate config/fixtures/resource-list-*.json and config/resources/catalog.json.

Octo bundle container (verified on all captured bundles): standard UnityFS 6 where the 8-byte "UnityFS\\0"
signature is replaced by XOR("UnityFS", 6F 0F FA 46 D3 28 3A) + the tail "tyFS\\0" (file is 4 bytes longer, the size
field is the standard one) and byte 5 of the LZ4-compressed blocks-info is XOR 0xFF.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import lz4.block

REPO_ROOT = Path(__file__).resolve().parent.parent
TITLE_MINIMUM = REPO_ROOT / "config" / "resources" / "title-minimum.json"
OUTPUT_DIR = REPO_ROOT / "content" / "resources" / "actioneditor"

# kicker -> donor kicker. Donor = smallest mean difference of the skill_*_action clip lengths in the kickers'
# pc_NNN_001 animator controllers (docs/DISC_ACTION_TIMELINES.md). Edit and rerun to try another donor.
DONORS = {2: 5, 3: 5, 6: 5, 7: 4, 9: 5, 10: 5, 12: 5, 13: 11, 14: 11}
OCTO_ID_BASE = 5000  # octoId 5000 + kickerId (unused range; the client keys its database by name anyway)

XOR_KEY = bytes((0x6F, 0x0F, 0xFA, 0x46, 0xD3, 0x28, 0x3A))
HEADER_SIZE = 50  # standard UnityFS 6 header: "UnityFS\0" + version + 2 version strings + size + 2 sizes + flags


def octo_to_unityfs(data: bytes) -> bytes:
    sig = bytes(b ^ XOR_KEY[i] for i, b in enumerate(data[:7]))
    if sig != b"UnityFS":
        raise ValueError("not an Octo UnityFS bundle")
    out = bytearray(b"Uni" + data[7:])
    out[HEADER_SIZE + 5] ^= 0xFF
    return bytes(out)


def unityfs_to_octo(data: bytes) -> bytes:
    if data[:8] != b"UnityFS\0":
        raise ValueError("not a UnityFS bundle")
    out = bytearray(bytes(b ^ XOR_KEY[i] for i, b in enumerate(data[:7])) + data[3:])
    out[HEADER_SIZE + 4 + 5] ^= 0xFF
    return bytes(out)


def parse_unityfs(data: bytes):
    """-> ((header prefix, blocks-info hash), [(usize, csize, flags)], [(offset, size, flags, path)], serialized bytes)."""
    version = struct.unpack(">I", data[8:12])[0]
    if version != 6:
        raise ValueError(f"unsupported UnityFS format {version}")
    _size, cinfo, uinfo, flags = struct.unpack(">QIII", data[30:50])
    at_end = bool(flags & 0x80)   # UnityPy writes the blocks-info after the payload; Unity's own tools put it first
    raw_info = data[len(data) - cinfo:] if at_end else data[50:50 + cinfo]
    info = lz4.block.decompress(raw_info, uncompressed_size=uinfo) if flags & 0x3F in (2, 3) else raw_info
    block_count = struct.unpack(">I", info[16:20])[0]
    blocks = [struct.unpack(">IIH", info[20 + i * 10:30 + i * 10]) for i in range(block_count)]
    p = 20 + block_count * 10
    node_count = struct.unpack(">I", info[p:p + 4])[0]
    p += 4
    nodes = []
    for _ in range(node_count):
        off, sz, fl = struct.unpack(">QQI", info[p:p + 20])
        p += 20
        end = info.index(b"\0", p)
        nodes.append((off, sz, fl, info[p:end].decode("utf-8")))
        p = end + 1
    payload = data[50:len(data) - cinfo] if at_end else data[50 + cinfo:]
    raw = b""
    q = 0
    for usize, csize, bflags in blocks:
        chunk = payload[q:q + csize]
        q += csize
        raw += lz4.block.decompress(chunk, uncompressed_size=usize) if bflags & 0x3F in (2, 3) else chunk
    return (data[:30], info[:16]), blocks, nodes, raw


def build_unityfs(header_prefix: bytes, info_hash: bytes, node_path, serialized) -> bytes:
    """One LZ4HC block holding the given files. `node_path`/`serialized` may be a single path + bytes or two
    parallel lists (e.g. CAB-x and CAB-x.resS); files are stored back to back like Unity does."""
    paths = [node_path] if isinstance(node_path, str) else list(node_path)
    datas = [serialized] if isinstance(serialized, (bytes, bytearray)) else list(serialized)
    payload = b"".join(datas)
    chunks = [payload[i:i + 0x20000] for i in range(0, len(payload), 0x20000)]   # Unity's 128 KiB block size
    bodies = [lz4.block.compress(c, mode="high_compression", compression=9, store_size=False) for c in chunks]
    body = b"".join(bodies)
    info = bytearray(info_hash)
    info += struct.pack(">I", len(chunks))
    for c, cb in zip(chunks, bodies):
        info += struct.pack(">IIH", len(c), len(cb), 3)
    info += struct.pack(">I", len(paths))
    off = 0
    for path, data in zip(paths, datas):
        info += struct.pack(">QQI", off, len(data), 4 if not path.endswith(".resS") else 0) + path.encode("utf-8") + bytes(1)
        off += len(data)
    cinfo = lz4.block.compress(bytes(info), mode="high_compression", compression=9, store_size=False)
    total = HEADER_SIZE + len(cinfo) + len(body)
    header = header_prefix + struct.pack(">QIII", total, len(cinfo), len(info), 0x43)
    assert len(header) == HEADER_SIZE
    return header + cinfo + body


def make_bundle(donor_octo: bytes, donor_kicker: int, kicker: int) -> bytes:
    (header_prefix, info_hash), _blocks, nodes, serialized = parse_unityfs(octo_to_unityfs(donor_octo))
    if len(nodes) != 1:
        raise ValueError(f"expected one serialized file in the donor bundle, found {len(nodes)}")
    old, new = f"aed_{donor_kicker:03d}".encode(), f"aed_{kicker:03d}".encode()
    patched = serialized.replace(old, new)
    if patched.count(new) != serialized.count(old) or len(patched) != len(serialized):
        raise AssertionError("name patch changed the serialized size")
    cab = "CAB-" + hashlib.md5(f"kickflight actioneditor/aed_{kicker:03d} from aed_{donor_kicker:03d}".encode()).hexdigest()
    return unityfs_to_octo(build_unityfs(header_prefix, info_hash, cab, patched))


def verify(octo: bytes, kicker: int) -> None:
    (_, _), _blocks, nodes, serialized = parse_unityfs(octo_to_unityfs(octo))
    assert nodes[0][3].startswith("CAB-") and f"aed_{kicker:03d}".encode() in serialized
    try:
        import UnityPy  # optional deeper check
    except ImportError:
        return
    env = UnityPy.load(octo_to_unityfs(octo))
    names = {obj.type.name: getattr(obj.read(), "m_Name", None) for obj in env.objects if obj.type.name in ("AssetBundle", "MonoBehaviour")}
    assert names.get("MonoBehaviour") == f"aed_{kicker:03d}", names
    assert names.get("AssetBundle") == f"actioneditor/aed_{kicker:03d}.unity3d", names


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    ap.add_argument("--dry-run", action="store_true", help="build and verify, write nothing")
    args = ap.parse_args()

    definition = json.loads(TITLE_MINIMUM.read_text(encoding="utf-8-sig"))
    entries = definition["entries"]
    by_name = {name: e for e in entries for name in e["names"]}
    by_id = {e["id"]: e for e in entries}
    used_objects = {e["objectName"] for e in entries}
    if not args.dry_run:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for kicker, donor in sorted(DONORS.items()):
        name = f"actioneditor/aed_{kicker:03d}.unity3d"
        entry_id = f"action-asset-aed-{kicker:03d}"
        if name in by_name and by_name[name]["id"] != entry_id:
            print(f"{name}: already served by {by_name[name]['id']}, skipping")
            continue
        donor_entry = by_name[f"actioneditor/aed_{donor:03d}.unity3d"]
        donor_path = (REPO_ROOT / donor_entry["sourcePath"]).resolve()
        octo = make_bundle(donor_path.read_bytes(), donor, kicker)
        verify(octo, kicker)
        object_name = f"aed0{kicker:02d}"  # Octo objectName: exactly six characters, must be unique
        if object_name in used_objects and by_id.get(entry_id, {}).get("objectName") != object_name:
            raise SystemExit(f"objectName {object_name} already used")
        prefix = ("A" + object_name).encode("ascii").hex().upper()
        file_name = f"{prefix}_{hashlib.md5(octo).hexdigest()}.bundle"
        rel = Path("content/resources/actioneditor") / file_name
        print(f"{name}: donor aed_{donor:03d} -> {rel.as_posix()} ({len(octo)} bytes)")
        if args.dry_run:
            continue
        for stale in OUTPUT_DIR.glob(f"{prefix}_*.bundle"):
            if stale.name != file_name:
                stale.unlink()
        (REPO_ROOT / rel).write_bytes(octo)
        new_entry = {
            "id": entry_id,
            "kind": "assetBundle",
            "octoId": OCTO_ID_BASE + kicker,
            "names": [name],
            "objectName": object_name,
            "sourcePath": rel.as_posix(),
            "logicalName": f"Unity AssetBundle {name}",
            "description": f"Disc action timelines for kicker {kicker}: copy of the captured aed_{donor:03d} bundle "
                           f"(kicker {donor}) with its own serialized-file name; built by scripts/build-action-asset-bundles.py",
        }
        if entry_id in by_id:
            by_id[entry_id].update(new_entry)
        else:
            entries.append(new_entry)
            by_id[entry_id] = new_entry
        used_objects.add(object_name)
    if not args.dry_run:
        text = json.dumps(definition, indent=2, ensure_ascii=False) + "\n"
        TITLE_MINIMUM.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        print(f"updated {TITLE_MINIMUM.relative_to(REPO_ROOT).as_posix()}; now bump its revision and run scripts/build-title-resource-catalog.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
