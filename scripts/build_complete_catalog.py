#!/usr/bin/env python3
"""Build the complete 100% Octo catalog for Kick-Flight from all preserved assets."""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_ROOT = (REPO_ROOT / "../Kick-Flight-Assets").resolve()
OCTO_BUNDLES_DIR = ASSETS_ROOT / "octo_sorted/3_unity_bundles"
OCTO_AFS2_DIR = ASSETS_ROOT / "octo_sorted/1_afs2_archives"
OCTO_CRI_DIR = ASSETS_ROOT / "octo_sorted/2_cri_audio_video"
OCTO_UNKNOWN_DIR = ASSETS_ROOT / "octo_sorted/5_unknown"
MANIFEST_OBJECTS = ASSETS_ROOT / "PIPELINE_OUTPUT_V3/manifests/unity_objects.jsonl"
MANIFEST_MEDIA = ASSETS_ROOT / "PIPELINE_OUTPUT_V3/manifests/media.json"

OUTPUT_TITLE_MINIMUM = REPO_ROOT / "config/resources/title-minimum.json"


def get_cuesheet_name(path: Path) -> str | None:
    data = path.read_bytes()
    if data[:4] != b"@UTF":
        return None
    try:
        table_size, = struct.unpack(">I", data[4:8])
        rows_offset, strings_offset, data_offset = struct.unpack(">III", data[8:20])
        str_data = data[8 + strings_offset : 8 + data_offset]
        strs = [s.decode("utf-8", "ignore") for s in str_data.split(b"\x00") if len(s) > 0]
        return strs[-1] if strs else None
    except Exception:
        return None


def main() -> None:
    entries = []
    octo_id_counter = 1
    seen_names = set()

    # 1. CORE CRI AUDIO CONFIG & CUESHEETS
    print("Indexing CriWare audio metadata (.acb / .acf)...")
    cuesheet_map = {}
    for f in sorted(OCTO_UNKNOWN_DIR.glob("*.bin")):
        cue_name = get_cuesheet_name(f)
        if cue_name:
            hex_prefix = f.name.split("_")[0]
            obj_name = bytes.fromhex(hex_prefix).decode("ascii", "ignore")[1:]
            cuesheet_map[cue_name] = (f, obj_name)

    # Specific well-known audio names
    # colorful.acf
    if "colorful" in cuesheet_map:
        f, obj_name = cuesheet_map["colorful"]
        entries.append({
            "id": "cri-config-acf",
            "kind": "resource",
            "octoId": octo_id_counter,
            "names": ["colorful.acf"],
            "objectName": obj_name,
            "sourcePath": os.path.relpath(f, REPO_ROOT),
            "logicalName": "Configuración maestra CriWare Atom ACF",
            "description": "Master audio bus and category configuration"
        })
        octo_id_counter += 1
        seen_names.add("colorful.acf")

    # Audio cuesheets (.acb)
    for cue_name, (f, obj_name) in sorted(cuesheet_map.items()):
        if cue_name == "colorful":
            continue
        acb_name = f"{cue_name}.acb"
        if acb_name in seen_names:
            continue
        seen_names.add(acb_name)

        # Build alias list
        alias_names = [acb_name]
        if cue_name.startswith("pc_"):
            # Also provide alias e.g. voice_pc_001.acb
            char_id = cue_name.split("_")[1]
            alias_names.append(f"voice_pc_{char_id}.acb")

        entries.append({
            "id": f"audio-acb-{cue_name}",
            "kind": "resource",
            "octoId": octo_id_counter,
            "names": alias_names,
            "objectName": obj_name,
            "sourcePath": os.path.relpath(f, REPO_ROOT),
            "logicalName": f"CriWare CueSheet {acb_name}",
            "description": f"Audio cue sheet for {cue_name}"
        })
        octo_id_counter += 1

    # Ensure common BGMs and voices have corresponding .awb entries in catalog
    # so CriWare never 404s when attempting to open companion AWB
    extra_awb_names = []
    for cue_name in list(cuesheet_map.keys()):
        awb_name = f"{cue_name}.awb"
        if awb_name not in seen_names:
            extra_awb_names.append(awb_name)
            seen_names.add(awb_name)

    # 2. STREAMING AUDIO WAVEFORMS (.awb / AFS2)
    print("Indexing CriWare waveform archives (.awb / AFS2)...")
    afs2_files = sorted(OCTO_AFS2_DIR.glob("*.afs2"))
    
    bgm_awb_map = {
        "o9LHyy": ["bgm_battle01.awb"],
        "VtvVWA": ["bgm_battle01_fes.awb"],
        "qUKhxa": ["bgm_battle02.awb"],
        "DctlF0": ["bgm_battle03.awb"],
        "Il7irs": ["bgm_battle03_fes.awb"],
        "pUu3wD": ["bgm_battle04.awb"],
        "DozCgw": ["bgm_menu00.awb"],
        "eMUsI7": ["bgm_menu01.awb"],
        "2SG6Gm": ["bgm_menu_fes.awb"],
        "qJTA70": ["bgm_result01.awb"],
        "Ei4139": ["bgm_title.awb", "common_se.awb", "in_game_se.awb", "out_game_se.awb"],
        "6HrrEs": ["bgm_training.awb"]
    }

    for f in afs2_files:
        hex_prefix = f.name.split("_")[0]
        obj_name = bytes.fromhex(hex_prefix).decode("ascii", "ignore")[1:]
        names = list(bgm_awb_map.get(obj_name, [f"stream_{obj_name}.awb"]))
        # Also include stream alias
        if f"stream_{obj_name}.awb" not in names:
            names.append(f"stream_{obj_name}.awb")

        for n in names:
            seen_names.add(n)

        entries.append({
            "id": f"audio-awb-{obj_name}",
            "kind": "resource",
            "octoId": octo_id_counter,
            "names": names,
            "objectName": obj_name,
            "sourcePath": os.path.relpath(f, REPO_ROOT),
            "logicalName": f"CriWare Wave Bank {names[0]}",
            "description": f"Streaming audio waveforms for {names[0]}"
        })
        octo_id_counter += 1

    # 3. USM VIDEOS (Disc intros, Tutorials, Scouts)
    print("Indexing CRI USM videos...")
    if MANIFEST_MEDIA.exists():
        media_list = json.loads(MANIFEST_MEDIA.read_text(encoding="utf-8"))
        for item in media_list:
            src_name = item.get("source")
            container_name = item.get("container_filename")
            if not src_name or not container_name:
                continue
            src_path = OCTO_CRI_DIR / src_name
            if not src_path.exists():
                continue
            hex_prefix = src_name.split("_")[0]
            obj_name = bytes.fromhex(hex_prefix).decode("ascii", "ignore")[1:]
            if container_name in seen_names:
                continue
            seen_names.add(container_name)
            entries.append({
                "id": f"cri-usm-{container_name.replace('.', '_')}",
                "kind": "resource",
                "octoId": octo_id_counter,
                "names": [container_name, f"movie/{container_name}"],
                "objectName": obj_name,
                "sourcePath": os.path.relpath(src_path, REPO_ROOT),
                "logicalName": f"CRI USM Video {container_name}",
                "description": f"Movie stream {container_name}"
            })
            octo_id_counter += 1

    # 4. UNITY ASSET BUNDLES (2,374 bundles)
    print("Indexing Unity AssetBundles...")
    bundle_files = {}
    for f in OCTO_BUNDLES_DIR.glob("*.bundle"):
        bundle_files[f.name] = f

    with open(MANIFEST_OBJECTS, "r", encoding="utf-8") as f:
        for line in f:
            if '"type": "AssetBundle"' in line:
                obj = json.loads(line)
                name = obj.get("name")
                bname = obj.get("bundle")
                if not name or not bname or bname not in bundle_files:
                    continue
                if name in seen_names:
                    continue
                seen_names.add(name)

                hex_prefix = bname.split("_")[0]
                obj_name = bytes.fromhex(hex_prefix).decode("ascii", "ignore")[1:]
                source_file = bundle_files[bname]

                # Generate aliases (e.g. localized paths)
                names = [name]
                if name == "ui/localize/zh/title/title_logo.unity3d":
                    names = [
                        "ui/localize/en/title/title_logo.unity3d",
                        "ui/localize/es/title/title_logo.unity3d",
                        "ui/localize/zh/title/title_logo.unity3d",
                        "ui/localize/ja/title/title_logo.unity3d"
                    ]
                elif "localize/zh/" in name:
                    # add es and en aliases
                    names.append(name.replace("localize/zh/", "localize/es/"))
                    names.append(name.replace("localize/zh/", "localize/en/"))

                entries.append({
                    "id": f"unity-bundle-{octo_id_counter}",
                    "kind": "assetBundle",
                    "octoId": octo_id_counter,
                    "names": names,
                    "objectName": obj_name,
                    "sourcePath": os.path.relpath(source_file, REPO_ROOT),
                    "logicalName": f"Unity AssetBundle {name}",
                    "description": f"Preserved Unity bundle for {name}"
                })
                octo_id_counter += 1

    catalog_data = {
        "schemaVersion": 1,
        "assetVersion": 12345,
        "revision": 16,
        "fromRevisions": list(range(17)),
        "urlPathFormat": "/cdn/{o}",
        "entries": entries
    }

    OUTPUT_TITLE_MINIMUM.write_text(json.dumps(catalog_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Successfully generated full catalog: {len(entries)} entries in {OUTPUT_TITLE_MINIMUM}")


if __name__ == "__main__":
    main()
