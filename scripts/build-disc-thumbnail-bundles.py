#!/usr/bin/env python3
"""
build-disc-thumbnail-bundles.py

Builds placeholder ui/disc/thumbnail_3010NNN bundles for discs whose real thumbnail was never captured
(3010045 Amun-Ra, 054 Scorpius, 096 Combat Turtle, 121 Solar Purr, 133 Pegasia): the art is cut out of a
disc-detail card screenshot (../Disc_data/thumbnail_source/<discId>.png, the 551x292 card layout), stretched to
the thumbnail's arch and masked with the alpha of a captured thumbnail. The in-game UI draws the rarity frame,
the top marker and the rarity badge over the sprite, so the card's own frame remnants stay hidden.

A captured thumbnail bundle is used as the donor: its Texture2D is replaced (RGBA32, 512x512), the Sprite /
AssetBundle names are renamed, the serialized file gets a fresh CAB name (UnityPy re-serialises the file; the
Octo container is then rebuilt by build-action-asset-bundles' helpers).

Output: content/resources/ui-disc/<hex('A'+objectName)>_<md5>.bundle + entries in title-minimum.json
(objectName "thb0NN", octoId 5200+NN). Then bump "revision" and run scripts/build-title-resource-catalog.py.

    pip install UnityPy lz4 pillow
    python scripts/build-disc-thumbnail-bundles.py [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from pathlib import Path

import UnityPy
from PIL import Image, ImageDraw, ImageFilter

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
octo = importlib.import_module("build-action-asset-bundles")

TITLE_MINIMUM = REPO_ROOT / "config" / "resources" / "title-minimum.json"
SOURCE_DIR = REPO_ROOT.parent / "Disc_data" / "thumbnail_source"
OUTPUT_DIR = REPO_ROOT / "content" / "resources" / "ui-disc"
DONOR = "ui/disc/thumbnail_3010001.unity3d"
CARD_SIZE = (551, 292)
ART_RECT = (29, 37, 137, 159)      # inside the card's arch frame, on a 551x292 card
ARCH = (24, 0, 462, 512)           # where the arch sits inside the 512x512 thumbnail texture (x, y, w, h)
OCTO_ID_BASE = 5200
PLACEHOLDER_DISC_IDS = (3010045, 3010096, 3010133, 3010136, 3010138)


def make_generic_card(disc_id: int) -> Image.Image:
    """Create deterministic neutral art when the original card screenshot is unavailable."""
    hue = disc_id % 360
    # Keep the generated art deliberately abstract so it cannot be mistaken for captured game art.
    base = Image.new("RGB", CARD_SIZE, (22 + hue % 28, 38 + hue % 42, 64 + hue % 52))
    draw = ImageDraw.Draw(base)
    colors = (
        (70 + hue % 90, 115 + (hue * 3) % 100, 155 + (hue * 7) % 90),
        (180 + hue % 70, 120 + (hue * 5) % 90, 55 + (hue * 11) % 100),
    )
    for radius in range(150, 10, -14):
        color = colors[(radius // 14) % 2]
        cx, cy = 82 + (disc_id % 17), 98 + (disc_id % 13)
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color)
    draw.polygon(((30, 150), (82, 38), (136, 150)), fill=(235, 242, 248))
    draw.ellipse((58, 73, 106, 121), fill=(45, 61, 82))
    return base


def make_bundle(donor_octo: bytes, card: Image.Image, disc_id: int) -> bytes:
    env = UnityPy.load(octo.octo_to_unityfs(donor_octo))
    donor_tex = next(o.read() for o in env.objects if o.type.name == "Texture2D")
    alpha = donor_tex.image.split()[3]
    art = card.convert("RGB").resize(CARD_SIZE, Image.LANCZOS).crop(ART_RECT)
    art = art.resize((ARCH[2], ARCH[3]), Image.LANCZOS).filter(ImageFilter.SMOOTH)
    tex_img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    tex_img.paste(art, (ARCH[0], ARCH[1]))
    tex_img.putalpha(alpha)

    donor_name = DONOR.split("/")[-1].split(".")[0]           # thumbnail_3010001
    donor_id = donor_name.split("_")[1]
    for o in env.objects:
        if o.type.name == "Texture2D":
            d = o.read()
            d.m_Name = f"thumbnail_{disc_id}"
            d.m_TextureFormat = 4                                 # RGBA32: no ASTC encoder needed
            d.image = tex_img
            d.save()
        elif o.type.name == "Sprite":
            d = o.read()
            d.m_Name = f"thumbnail_{disc_id}"
            d.save()
        elif o.type.name == "AssetBundle":
            tree = o.read_typetree()
            tree["m_Name"] = f"ui/disc/thumbnail_{disc_id}.unity3d"
            tree["m_Container"] = [[k.replace(donor_id, str(disc_id)), v] for k, v in tree["m_Container"]]
            if "m_AssetBundleName" in tree:
                tree["m_AssetBundleName"] = tree["m_AssetBundleName"].replace(donor_id, str(disc_id))
            o.save_typetree(tree)
    std = env.file.save(packer="lz4")
    (header_prefix, info_hash), _blocks, nodes, raw = octo.parse_unityfs(std)
    files = [(n[3], raw[n[0]:n[0] + n[1]]) for n in nodes]
    old_cab = next(n for n, _ in files if not n.endswith(".resS"))
    new_cab = "CAB-" + hashlib.md5(f"kickflight thumbnail_{disc_id} placeholder".encode()).hexdigest()
    paths = [n.replace(old_cab, new_cab) for n, _ in files]
    datas = [d.replace(old_cab.encode(), new_cab.encode()) for _, d in files]
    if len(files) == 2 and (new_cab + ".resS").encode() not in datas[0]:
        paths, datas = paths[:1], datas[:1]                   # UnityPy stored the new image inline; drop the stale resS
    return octo.unityfs_to_octo(octo.build_unityfs(header_prefix, info_hash, paths, datas))


def verify(bundle: bytes, disc_id: int) -> None:
    env = UnityPy.load(octo.octo_to_unityfs(bundle))
    names = {o.type.name: getattr(o.read(), "m_Name", None) for o in env.objects}
    assert names.get("Sprite") == f"thumbnail_{disc_id}", names
    assert names.get("AssetBundle") == f"ui/disc/thumbnail_{disc_id}.unity3d", names
    tex = next(o.read() for o in env.objects if o.type.name == "Texture2D")
    assert tex.image.size == (512, 512)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    definition = json.loads(TITLE_MINIMUM.read_text(encoding="utf-8-sig"))
    entries = definition["entries"]
    by_name = {n: e for e in entries for n in e["names"]}
    by_id = {e["id"]: e for e in entries}
    donor_octo = (REPO_ROOT / by_name[DONOR]["sourcePath"]).read_bytes()
    if not args.dry_run:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    source_by_id = {int(src.stem): src for src in SOURCE_DIR.glob("3010*.png")}
    for disc_id in sorted(set(source_by_id) | set(PLACEHOLDER_DISC_IDS)):
        src = source_by_id.get(disc_id)
        name = f"ui/disc/thumbnail_{disc_id}.unity3d"
        entry_id = f"disc-thumbnail-{disc_id}"
        if name in by_name and by_name[name]["id"] != entry_id:
            print(f"{name}: a captured bundle exists ({by_name[name]['id']}), skipping")
            continue
        card = Image.open(src) if src else make_generic_card(disc_id)
        bundle = make_bundle(donor_octo, card, disc_id)
        verify(bundle, disc_id)
        object_name = f"thb{disc_id - 3010000:03d}"
        prefix = ("A" + object_name).encode("ascii").hex().upper()
        file_name = f"{prefix}_{hashlib.md5(bundle).hexdigest()}.bundle"
        rel = Path("content/resources/ui-disc") / file_name
        source_label = src.name if src else "generated neutral art"
        print(f"{name}: {source_label} -> {rel.as_posix()} ({len(bundle)} bytes)")
        if args.dry_run:
            continue
        for stale in OUTPUT_DIR.glob(f"{prefix}_*.bundle"):
            if stale.name != file_name:
                stale.unlink()
        (REPO_ROOT / rel).write_bytes(bundle)
        entry = {"id": entry_id, "kind": "assetBundle", "octoId": OCTO_ID_BASE + disc_id - 3010000, "names": [name],
                 "objectName": object_name, "sourcePath": rel.as_posix(), "logicalName": f"Unity AssetBundle {name}",
                 "description": f"Placeholder disc thumbnail for {disc_id} built from "
                                f"{'a card screenshot' if src else 'generated neutral art'} "
                                f"(scripts/build-disc-thumbnail-bundles.py); the original was never captured"}
        if entry_id in by_id:
            by_id[entry_id].update(entry)
        else:
            entries.append(entry)
            by_id[entry_id] = entry
    if not args.dry_run:
        text = json.dumps(definition, indent=2, ensure_ascii=False) + "\n"
        TITLE_MINIMUM.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        print(f"updated {TITLE_MINIMUM.relative_to(REPO_ROOT).as_posix()}; now bump its revision and run scripts/build-title-resource-catalog.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
