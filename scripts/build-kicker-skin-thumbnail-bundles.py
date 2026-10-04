#!/usr/bin/env python3
"""Build generated kicker-skin thumbnail AssetBundles from durable RGBA PNG sources.

The image source is assets/generated/skin-thumbnails/thumbnail_pc_NNN_CCC.png. Each
skin is emitted as four independent Unity AssetBundles (direct, oblique, circle,
r20); container keys, Sprite/Texture2D names, CABs and Octo filenames are unique.

By default this builds every configured skin and refuses to run while any PNG is
missing. Once all 11 final PNGs exist, the full build automatically adds revision
32 and its 44 entries, then regenerates catalog and fixtures. Use --only to
prototype available images; partial builds go to .local and never update catalogs.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path

import UnityPy
from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
OCTO_PATH = ROOT / "scripts" / "build-action-asset-bundles.py"
_spec = importlib.util.spec_from_file_location("octo_bundle_helpers", OCTO_PATH)
octo = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(octo)

_alias_spec = importlib.util.spec_from_file_location(
    "weapon_alias_name_helpers", ROOT / "scripts" / "add_weapon_costume_aliases.py"
)
weapon_aliases = importlib.util.module_from_spec(_alias_spec)
assert _alias_spec and _alias_spec.loader
_alias_spec.loader.exec_module(weapon_aliases)

TITLE_MINIMUM = ROOT / "config/resources/title-minimum.json"
PNG_DIR = ROOT / "assets/generated/skin-thumbnails"
FINAL_DIR = ROOT / "content/resources/ui-kicker-skin-thumbnails"
LOCAL_DIR = ROOT / ".local/missing-icons/search/built-bundles"
ASSETS_DIR = ROOT.parent / "Kick-Flight-Assets/octo_sorted/3_unity_bundles"

SKINS = {
    "001_022": {"kicker_id": 1, "kicker": "Tsubame", "costume_id": 22, "row_id": 2012201},
    "002_022": {"kicker_id": 2, "kicker": "Ruriha", "costume_id": 22, "row_id": 2022201},
    "003_022": {"kicker_id": 3, "kicker": "Coco", "costume_id": 22, "row_id": 2032201},
    "003_052": {"kicker_id": 3, "kicker": "Coco", "costume_id": 52, "row_id": 2035201},
    "006_022": {"kicker_id": 6, "kicker": "Pitophy", "costume_id": 22, "row_id": 2062201},
    "008_052": {"kicker_id": 8, "kicker": "Anna", "costume_id": 52, "row_id": 2085201},
    "011_051": {"kicker_id": 11, "kicker": "Diatrius", "costume_id": 51, "row_id": 2115101},
    "012_022": {"kicker_id": 12, "kicker": "BuzzyBig", "costume_id": 22, "row_id": 2122201},
    "014_002": {"kicker_id": 14, "kicker": "Sid", "costume_id": 2, "row_id": 2140201},
    "014_003": {"kicker_id": 14, "kicker": "Sid", "costume_id": 3, "row_id": 2140301},
    "014_051": {"kicker_id": 14, "kicker": "Sid", "costume_id": 51, "row_id": 2145101},
}

# One canonical donor per route. These carry the correct Unity Sprite and texture
# serialization for their route; the original sprite mesh is replaced with a full
# rectangular quad so headwear/ears are not clipped by the donor character's trim.
STYLES = {
    "direct": {
        "route": "ui/kicker",
        "donor_name": "ui/kicker/thumbnail_pc_001_001.unity3d",
        "donor_file": "41425373765375_aed8b0ebda9b0935a3521d8847b57adb.bundle",
        "fit": "contain",
    },
    "oblique": {
        "route": "ui/kicker/oblique",
        "donor_name": "ui/kicker/oblique/thumbnail_pc_001_001.unity3d",
        "donor_file": "414E4B6B545232_78662efe39974516d105c377f6286412.bundle",
        "fit": "contain",
    },
    "circle": {
        "route": "ui/kicker/circle",
        "donor_name": "ui/kicker/circle/thumbnail_pc_001_001.unity3d",
        "donor_file": "4157385A4F3876_7364768ded34d1df947fb70d87719332.bundle",
        "fit": "cover-circle-mask",
    },
    "r20": {
        "route": "ui/kicker/r20",
        "donor_name": "ui/kicker/r20/thumbnail_pc_001_001.unity3d",
        "donor_file": "41733256663375_1b78af6cdac24f7f8f2e5a25db4291d2.bundle",
        "fit": "cover-rounded-mask",
    },
}

MIN_REVISION = 32


def write_if_changed(path: Path, data: bytes) -> bool:
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def image_for_style(source: Image.Image, style: str, size: tuple[int, int]) -> Image.Image:
    policy = STYLES[style]["fit"]
    if policy == "contain":
        fitted = ImageOps.contain(source, size, Image.Resampling.LANCZOS)
        out = Image.new("RGBA", size, (0, 0, 0, 0))
        out.alpha_composite(fitted, ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2))
        return out
    out = ImageOps.fit(source, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    if policy == "cover-rounded-mask":
        backing = Image.new("RGBA", size, (255, 255, 255, 255))
        backing.alpha_composite(out)
        out = backing
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    if policy == "cover-circle-mask":
        draw.ellipse((0, 0, size[0] - 1, size[1] - 1), fill=255)
    else:
        draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=20, fill=255)
    out.putalpha(Image.composite(out.getchannel("A"), Image.new("L", size, 0), mask))
    return out


def set_full_quad(sprite) -> None:
    rect, ppu = sprite.m_Rect, float(sprite.m_PixelsToUnits)
    width, height = float(rect.width) / ppu, float(rect.height) / ppu
    left = -float(sprite.m_Pivot.x) * width
    bottom = -float(sprite.m_Pivot.y) * height
    right, top = left + width, bottom + height
    positions = [(left, bottom, 0.0), (right, bottom, 0.0), (right, top, 0.0), (left, top, 0.0)]
    uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    rd = sprite.m_RD
    vd = rd.m_VertexData
    vd.m_VertexCount = 4
    vd.m_Channels[0].dimension = 3
    vd.m_Channels[4].dimension = 2
    vd.m_DataSize = b"".join(struct.pack("<3f", *v) for v in positions) + b"".join(struct.pack("<2f", *v) for v in uvs)
    rd.m_IndexBuffer = list(struct.pack("<6H", 0, 1, 2, 0, 2, 3))
    rd.m_SubMeshes[0].indexCount = 6
    rd.m_SubMeshes[0].vertexCount = 4
    rd.m_SubMeshes[0].firstVertex = 0
    rd.textureRect.x = 0.0
    rd.textureRect.y = 0.0
    rd.textureRect.width = float(rect.width)
    rd.textureRect.height = float(rect.height)
    rd.textureRectOffset.x = 0.0
    rd.textureRectOffset.y = 0.0


def make_bundle(style: str, skin_key: str, source: Image.Image) -> tuple[bytes, dict]:
    spec = STYLES[style]
    target = f"thumbnail_pc_{skin_key}"
    logical_name = f"{spec['route']}/{target}.unity3d"
    donor_raw = (ASSETS_DIR / spec["donor_file"]).read_bytes()
    env = UnityPy.load(octo.octo_to_unityfs(donor_raw))
    tex_obj = next(o for o in env.objects if o.type.name == "Texture2D")
    sprite_obj = next(o for o in env.objects if o.type.name == "Sprite")
    donor_texture = tex_obj.read()
    size = (int(donor_texture.m_Width), int(donor_texture.m_Height))
    generated = image_for_style(source, style, size)
    texture_info = {
        "width": size[0], "height": size[1], "source_format": int(donor_texture.m_TextureFormat),
        "output_format": 4, "mip_count": 1, "alpha_extrema": list(generated.getchannel("A").getextrema()),
        "fit_policy": spec["fit"],
        "alpha_mask": "circle" if style == "circle" else "rounded_rectangle_radius_20px" if style == "r20" else "source_alpha",
        "background_fill": "opaque_white_under_portrait" if style == "r20" else "transparent",
    }

    donor_texture.m_Name = target
    donor_texture.m_TextureFormat = 4  # RGBA32, matching the uncompressed inline pixel bytes.
    donor_texture.m_MipCount = 1
    donor_texture.m_CompleteImageSize = size[0] * size[1] * 4
    donor_texture.m_StreamData.path = ""
    donor_texture.m_StreamData.offset = 0
    donor_texture.m_StreamData.size = 0
    donor_texture.image = generated
    donor_texture.save()

    sprite = sprite_obj.read()
    sprite.m_Name = target
    set_full_quad(sprite)
    sprite.save()

    for obj in env.objects:
        if obj.type.name == "AssetBundle":
            tree = obj.read_typetree()
            donor_base = "thumbnail_pc_001_001"
            tree["m_Name"] = logical_name
            tree["m_Container"] = [
                [str(k).replace(donor_base, target), value] for k, value in tree["m_Container"]
            ]
            if "m_AssetBundleName" in tree:
                tree["m_AssetBundleName"] = str(tree["m_AssetBundleName"]).replace(donor_base, target)
            obj.save_typetree(tree)

    std = env.file.save(packer="lz4")
    (header_prefix, info_hash), _blocks, nodes, raw = octo.parse_unityfs(std)
    files = [(node[3], raw[node[0]:node[0] + node[1]]) for node in nodes]
    old_cab = next(name for name, _ in files if not name.endswith(".resS"))
    new_cab = "CAB-" + hashlib.md5(f"kickflight generated {logical_name}".encode()).hexdigest()
    paths = [name.replace(old_cab, new_cab) for name, _ in files]
    payloads = [data.replace(old_cab.encode(), new_cab.encode()) for _, data in files]
    if len(files) == 2 and (new_cab + ".resS").encode() not in payloads[0]:
        paths, payloads = paths[:1], payloads[:1]
    result = octo.unityfs_to_octo(octo.build_unityfs(header_prefix, info_hash, paths, payloads))
    check = verify_bundle(result, logical_name, target, texture_info)
    return result, {"logical_name": logical_name, "texture": texture_info, "serialized_names": check}


def verify_bundle(data: bytes, logical_name: str, target: str, texture_info: dict) -> dict:
    env = UnityPy.load(octo.octo_to_unityfs(data))
    result = {}
    textures = {obj.path_id: obj for obj in env.objects if obj.type.name == "Texture2D"}
    for obj in env.objects:
        if obj.type.name == "Texture2D":
            texture = obj.read()
            assert texture.m_Name == target
            assert (texture.m_Width, texture.m_Height) == (texture_info["width"], texture_info["height"])
            assert texture.m_TextureFormat == 4 and texture.m_MipCount == 1
            assert texture.m_CompleteImageSize == texture_info["width"] * texture_info["height"] * 4
            assert not texture.m_StreamData.path and texture.m_StreamData.size == 0
            assert texture.image.getchannel("A").getextrema() == tuple(texture_info["alpha_extrema"])
            if texture_info["background_fill"] == "opaque_white_under_portrait":
                pixels = list(texture.image.convert("RGBA").getdata())
                alpha = texture.image.getchannel("A")
                assert alpha.getpixel((0, 0)) == 0 and alpha.getpixel((texture_info["width"] - 1, 0)) == 0
                assert alpha.getpixel((0, texture_info["height"] - 1)) == 0
                assert alpha.getpixel((texture_info["width"] // 2, texture_info["height"] // 2)) == 255
                assert sum(1 for r, g, b, a in pixels if (r, g, b) == (255, 255, 255) and a == 255) >= 1000
            result["Texture2D"] = texture.m_Name
        elif obj.type.name == "Sprite":
            sprite = obj.read()
            assert sprite.m_Name == target and sprite.m_RD.m_VertexData.m_VertexCount == 4
            assert len(sprite.m_RD.m_IndexBuffer) == 12
            assert sprite.m_RD.texture.m_PathID != 0
            pointed_texture = textures.get(sprite.m_RD.texture.m_PathID)
            assert pointed_texture is not None and pointed_texture.read().m_Name == target
            assert sprite.m_RD.textureRect.width == texture_info["width"]
            assert sprite.m_RD.textureRect.height == texture_info["height"]
            result["Sprite"] = {"name": sprite.m_Name, "rect": [sprite.m_Rect.width, sprite.m_Rect.height], "texture_path_id": sprite.m_RD.texture.m_PathID}
        elif obj.type.name == "AssetBundle":
            bundle = obj.read()
            assert bundle.m_Name == logical_name
            assert all(target in path for path, _ in bundle.m_Container)
            result["AssetBundle"] = {"name": bundle.m_Name, "containers": [path for path, _ in bundle.m_Container]}
    assert set(result) == {"Texture2D", "Sprite", "AssetBundle"}, result
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", choices=sorted(SKINS), help="Build selected kicker/costume ids only.")
    parser.add_argument("--png-dir", type=Path, help="Override source PNG folder for isolated validation.")
    parser.add_argument("--output-dir", type=Path, help="Override output folder; selected subsets default to .local.")
    parser.add_argument("--integrate-title-minimum", action="store_true", help="After a full 11-skin build, add all 44 entries and advance revision to 32.")
    parser.add_argument("--dry-run", action="store_true", help="Build and verify in memory without writing bundles or catalogs.")
    args = parser.parse_args()
    keys = sorted(args.only or SKINS)
    png_dir = args.png_dir.resolve() if args.png_dir else PNG_DIR
    missing = [key for key in keys if not (png_dir / f"thumbnail_pc_{key}.png").is_file()]
    if missing:
        raise SystemExit("Missing final PNG(s): " + ", ".join(f"thumbnail_pc_{key}.png" for key in missing))
    auto_integrate = not args.only and not args.png_dir
    integrate = args.integrate_title_minimum or auto_integrate
    if integrate and set(keys) != set(SKINS):
        raise SystemExit("--integrate-title-minimum requires all 11 configured final PNGs")
    output_dir = args.output_dir or (LOCAL_DIR if args.only else FINAL_DIR)
    output_dir = output_dir if output_dir.is_absolute() else ROOT / output_dir
    output_entries = []
    records = []
    title_minimum = json.loads(TITLE_MINIMUM.read_text(encoding="utf-8-sig")) if integrate else None
    current_entries = title_minimum["entries"] if title_minimum else []
    by_id = {entry["id"]: entry for entry in current_entries}
    by_name = {name: entry for entry in current_entries for name in entry.get("names", [])}
    used_ids = {int(entry["octoId"]) for entry in current_entries}
    thumb_prefix = "kicker-skin-thumb-"
    used_object_names = {
        entry["objectName"] for entry in current_entries
        if not entry.get("id", "").startswith(thumb_prefix)
    }
    next_octo_id = max(used_ids, default=0) + 1
    # IDs are assigned deterministically by sorted skin key and canonical style order.
    style_order = list(STYLES)
    for skin_index, key in enumerate(sorted(keys)):
        source_path = png_dir / f"thumbnail_pc_{key}.png"
        source_image = Image.open(source_path)
        if "A" not in source_image.getbands():
            raise SystemExit(f"{source_path} must preserve an alpha channel")
        source = source_image.convert("RGBA")
        if source.size != (200, 162):
            raise SystemExit(f"{source_path} must be 200x162 RGBA; found {source.size}")
        for style_index, style in enumerate(style_order):
            bundle, detail = make_bundle(style, key, source)
            row = SKINS[key]
            entry_id = f"kicker-skin-thumb-{row['kicker_id']:03d}-{row['costume_id']:03d}-{style}"
            old_entry = by_id.get(entry_id) or by_name.get(detail["logical_name"])
            old_object_name = old_entry.get("objectName", "") if old_entry else ""
            if old_entry:
                octo_id = int(old_entry["octoId"])
            else:
                while next_octo_id in used_ids:
                    next_octo_id += 1
                octo_id = next_octo_id
                next_octo_id += 1
            if len(old_object_name) == 6 and old_object_name.isascii() and old_object_name.isalnum():
                object_name = old_object_name
                if object_name in used_object_names:
                    raise SystemExit(f"Duplicate six-character Octo objectName: {object_name}")
                used_object_names.add(object_name)
            else:
                object_name = weapon_aliases._base62_digest(detail["logical_name"], used_object_names)
            if len(object_name) != 6 or not object_name.isascii() or not object_name.isalnum():
                raise SystemExit(f"Octo objectName must be six ASCII alphanumeric characters: {object_name!r}")
            used_ids.add(octo_id)
            object_prefix = ("A" + object_name).encode("ascii").hex().upper()
            filename = f"{object_prefix}_{hashlib.md5(bundle).hexdigest()}.bundle"
            bundle_path = output_dir / filename
            rel_path = bundle_path.relative_to(ROOT).as_posix()
            source_label = source_path.relative_to(ROOT).as_posix() if source_path.is_relative_to(ROOT) else str(source_path)
            detail.update({"skin_key": key, "style": style, "octo_id": octo_id, "object_name": object_name,
                           "source_png": source_label, "bundle_path": rel_path,
                           "source_png_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                           "bundle_sha256": hashlib.sha256(bundle).hexdigest(), "bundle_bytes": len(bundle)})
            records.append(detail)
            output_entries.append({
                "id": entry_id,
                "kind": "assetBundle", "octoId": octo_id, "names": [detail["logical_name"]],
                "objectName": object_name, "sourcePath": rel_path,
                "logicalName": f"Unity AssetBundle {detail['logical_name']}",
                "description": f"Generated skin-selection thumbnail for {row['kicker']} costume {row['costume_id']} ({style}) from durable RGBA PNG source.",
            })
            if not args.dry_run:
                write_if_changed(bundle_path, bundle)

    if integrate:
        assert title_minimum is not None
        additions = []
        for entry in output_entries:
            old_by_id = by_id.get(entry["id"])
            old_by_name = by_name.get(entry["names"][0])
            if old_by_id or old_by_name:
                old = old_by_id or old_by_name
                if old_by_id is None or old_by_name is None or old["id"] != entry["id"]:
                    raise SystemExit(f"Existing title-minimum entry conflicts with generated thumbnail {entry['names'][0]}")
                if old != entry:
                    prior_object = old.get("objectName", "")
                    same_identity = all(old.get(key) == entry.get(key) for key in ("id", "kind", "octoId", "names", "objectName"))
                    valid_object_name = len(prior_object) == 6 and prior_object.isascii() and prior_object.isalnum()
                    if same_identity and (not valid_object_name or old.get("sourcePath") != entry.get("sourcePath")):
                        old.clear()
                        old.update(entry)
                    else:
                        raise SystemExit(f"Existing title-minimum entry conflicts with generated thumbnail {entry['names'][0]}")
                continue
            additions.append(entry)
        title_minimum["entries"].extend(additions)
        target_revision = max(int(title_minimum["revision"]), MIN_REVISION)
        title_minimum["revision"] = target_revision
        if target_revision not in title_minimum["fromRevisions"]:
            title_minimum["fromRevisions"].append(target_revision)
        if not args.dry_run:
            text = json.dumps(title_minimum, ensure_ascii=False, indent=2) + "\n"
            write_if_changed(TITLE_MINIMUM, text.replace("\n", "\r\n").encode("utf-8"))

    report = {"skins": keys, "bundle_count": len(records), "integrated_title_minimum": integrate,
              "resource_catalog_regenerated": False,
              "output_dir": str(output_dir), "bundles": records, "title_minimum_entries_preview": output_entries}
    if not args.dry_run:
        report_dir = output_dir if args.output_dir or not args.only else LOCAL_DIR
        report_dir.mkdir(parents=True, exist_ok=True)
        manifest_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        write_if_changed(report_dir / "bundle-manifest.json", manifest_text.encode("utf-8"))
    print(json.dumps({"skins": keys, "bundle_count": len(records), "integrated_title_minimum": integrate,
                      "output_dir": str(output_dir), "dry_run": args.dry_run}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
