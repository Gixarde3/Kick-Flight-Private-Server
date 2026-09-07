#!/usr/bin/env python3
import json, os, re

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
manifest_path = os.path.join(repo_root, "../Kick-Flight-Assets/PIPELINE_OUTPUT_V3/manifests/unity_objects.jsonl")
octo_bundles_dir = "../Kick-Flight-Assets/octo_sorted/3_unity_bundles"
octo_unknown_dir = "../Kick-Flight-Assets/octo_sorted/5_unknown"

bundle_by_name = {}
with open(manifest_path) as f:
    for line in f:
        if "\"type\": \"AssetBundle\"" in line:
            obj = json.loads(line)
            name = obj.get("name")
            bname = obj.get("bundle")
            hex_part = bname.split("_")[0]
            obj_name = bytes.fromhex(hex_part).decode("ascii")[1:]
            bundle_by_name[name] = {
                "objectName": obj_name,
                "sourcePath": f"{octo_bundles_dir}/{bname}",
                "bundle": bname
            }

kicker_names = {
    1: "Tsubame", 2: "Ruriha", 3: "Coco", 4: "Kite", 5: "Owlbert",
    6: "Pitophy", 7: "Grenhawk", 8: "Anna", 9: "Jay", 10: "Yuyan",
    11: "Diatrius", 12: "Buzzy Big", 13: "Hitagi", 14: "Sid"
}

voice_files = {
    1: "526349626A7155_b6eccbdecdd68fd2b2dd4be36cd26b72.bin",
    2: "52677553735138_27668d73a9405a8ef5de979d90618ae5.bin",
    3: "5254786C494870_1935cd2683729fda28a035595c4e3fc6.bin",
    4: "52787230537A4D_6fe4dd4f1d4f2fcb693dc35bf3ede2d3.bin",
    5: "52513976635849_ff8a56fa6fa6bec7a70b8e37ad7e185e.bin",
    6: "524A5244363737_6d5b06bfed683c187470f1fda0191d0c.bin",
    7: "526C474E634B6B_db6ca262841a69275dcb45ff83ba2b1a.bin",
    8: "526B784D4D6D4B_af37071de722109a0a59fdd5e95e0889.bin",
    9: "52424D74616578_ba471dbc54f74583cfeaa2f0042660d2.bin",
    10: "52727242396F34_94454ca8320147a31b10d28660ed2184.bin",
    11: "52594D67524371_5c82eb52703a77ad5656bbb321dff71d.bin",
    12: "5245754D4D5435_d347d4dcb6263cbb791f2fca4ce963b2.bin",
    13: "523236794B6F78_e9702802f6263eed7374f9fbab373988.bin",
    14: "525A7642757945_5a55d984b031f95f052c6813345c0bef.bin",
}

# Read original title-minimum.json to get base entries
title_min_path = os.path.join(repo_root, "config/resources/title-minimum.json")

# Base core entries (1 to 21) from original catalog
# Let's define the base core entries
core_entries = [
    {
      "id": "title-logo-bundle",
      "kind": "assetBundle",
      "octoId": 1,
      "names": [
        "ui/localize/en/title/title_logo.unity3d",
        "ui/localize/es/title/title_logo.unity3d"
      ],
      "objectName": "7pXtSo",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/3_unity_bundles/4137705874536F_481a6362d5d91b173473f67f5620461b.bundle",
      "logicalName": "Logo de inicio de Kick-Flight",
      "description": "AssetBundle Unity localizado que contiene Texture2D y Sprite title_logo."
    },
    {
      "id": "master-effect-bundle",
      "kind": "assetBundle",
      "octoId": 2,
      "names": ["master/effect_master.unity3d"],
      "objectName": "kOJzo3",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/3_unity_bundles/416B4F4A7A6F33_153f73215e0544419beead0f7d5bcaa8.bundle",
      "logicalName": "Effect master",
      "description": "Master asset requerido por LoadManager al salir del título."
    },
    {
      "id": "master-aed-bundle",
      "kind": "assetBundle",
      "octoId": 3,
      "names": ["actioneditor/aed_master.unity3d"],
      "objectName": "sv73XX",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/3_unity_bundles/41737637335858_8a6594ef32b5c5a47e05c0be7e107d23.bundle",
      "logicalName": "AED master",
      "description": "Master asset global recuperado del catálogo de producción."
    },
    {
      "id": "master-kicker-skill-bundle",
      "kind": "assetBundle",
      "octoId": 4,
      "names": ["master/kickerskillmaster/kicker_skill_master.unity3d"],
      "objectName": "VsckeT",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/3_unity_bundles/415673626B6554_6f22a18598a5d097c50f7b822a73a874.bundle",
      "logicalName": "Kicker skill master",
      "description": "Parámetros de habilidades de kickers usados por Home."
    },
    {
      "id": "master-result-score-bundle",
      "kind": "assetBundle",
      "octoId": 5,
      "names": ["master/result_score_master.unity3d"],
      "objectName": "dQH3Jz",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/3_unity_bundles/41645148334A7A_203466fefa1229eddfa37d84d92bbe11.bundle",
      "logicalName": "Result score master",
      "description": "Master asset global recuperado del catálogo de producción."
    },
    {
      "id": "master-kicker-special-skill-bundle",
      "kind": "assetBundle",
      "octoId": 6,
      "names": ["master/kickerspecialskillmaster/kicker_special_skill_master.unity3d"],
      "objectName": "o75vfb",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/3_unity_bundles/416F3735776662_45a3fa6c82a894862d350234eed27921.bundle",
      "logicalName": "Kicker special skill master",
      "description": "Parámetros de habilidad especial de kickers usados por Home."
    },
    {
      "id": "master-kicker-ability-parameter-bundle",
      "kind": "assetBundle",
      "octoId": 7,
      "names": ["master/kickerabilityparametermaster/kicker_ability_parameter_master.unity3d"],
      "objectName": "PHOmFb",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/3_unity_bundles/4150484F6D4662_e735bdc873e83863451e0713df9d1e3a.bundle",
      "logicalName": "Kicker ability parameter master",
      "description": "Parámetros de habilidades pasivas de kickers usados por Home."
    },
    {
      "id": "master-wind-bundle",
      "kind": "assetBundle",
      "octoId": 8,
      "names": ["master/wind_master.unity3d"],
      "objectName": "hxxfTE",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/3_unity_bundles/41687878665445_e49854d7323fdc1b9d190501b4a62c3d.bundle",
      "logicalName": "Wind master",
      "description": "Master asset global recuperado del catálogo de producción."
    },
    {
      "id": "title-common-se-acb",
      "kind": "resource",
      "octoId": 9,
      "names": ["common_se.acb"],
      "objectName": "Og1RF0",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/5_unknown/524F6731524630_54124c8f043e358e5618ed0a6d074432.bin",
      "logicalName": "Efectos de sonido comunes del título (ACB)",
      "description": "Banco de efectos de sonido comunes usado por la secuencia inicial del juego."
    },
    {
      "id": "title-common-se-awb",
      "kind": "resource",
      "octoId": 10,
      "names": ["common_se.awb"],
      "objectName": "Ei4139",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/5_unknown/524F6731524630_54124c8f043e358e5618ed0a6d074432.bin",
      "logicalName": "Efectos de sonido comunes del título (AWB)",
      "description": "Stream de audio asociado al banco de sonido común del título."
    },
    {
      "id": "title-common-voice-acb",
      "kind": "resource",
      "octoId": 11,
      "names": ["common_voice.acb"],
      "objectName": "tq7f77",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/5_unknown/527639706B7148_41c2d14a98f2e813999d86c442441e9c.bin",
      "logicalName": "Voces comunes del juego (ACB)",
      "description": "Banco de voces compartidas precargado por el flujo de inicio."
    },
    {
      "id": "title-common-voice-awb",
      "kind": "resource",
      "octoId": 12,
      "names": ["common_voice.awb"],
      "objectName": "p0y1hG",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/5_unknown/527639706B7148_41c2d14a98f2e813999d86c442441e9c.bin",
      "logicalName": "Voces comunes del juego (AWB)",
      "description": "Stream de voces compartidas requerido por el cliente al arrancar."
    },
    {
      "id": "title-bgm-title-acb",
      "kind": "resource",
      "octoId": 13,
      "names": ["bgm_title.acb"],
      "objectName": "ujPPwv",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/5_unknown/52756A50507776_d81ea6668a513695a380c18a807822d8.bin",
      "logicalName": "Música del título (ACB)",
      "description": "Cue sheet CRI para la música de la pantalla de inicio."
    },
    {
      "id": "title-bgm-title-awb",
      "kind": "resource",
      "octoId": 14,
      "names": ["bgm_title.awb"],
      "objectName": "qFk7lX",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/5_unknown/52756A50507776_d81ea6668a513695a380c18a807822d8.bin",
      "logicalName": "Música del título (AWB)",
      "description": "Stream de audio para la música de la pantalla de inicio."
    },
    {
      "id": "title-bgm-home-acb",
      "kind": "resource",
      "octoId": 15,
      "names": ["bgm_home.acb"],
      "objectName": "4KecUI",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/5_unknown/52344B65635549_8bd71a486c9da4b97c776256c8260b5b.bin",
      "logicalName": "Música de Home (ACB)",
      "description": "Cue sheet CRI para el tema musical de la pantalla principal (bgm_menu00)."
    },
    {
      "id": "title-bgm-home-awb",
      "kind": "resource",
      "octoId": 16,
      "names": ["bgm_home.awb"],
      "objectName": "qFk7lX",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/5_unknown/52344B65635549_8bd71a486c9da4b97c776256c8260b5b.bin",
      "logicalName": "Música de Home (AWB)",
      "description": "Stream de audio para la música de la pantalla principal."
    },
    {
      "id": "home-system-voice-acb",
      "kind": "resource",
      "octoId": 17,
      "names": ["voice_system_001.acb"],
      "objectName": "E8mY3s",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/5_unknown/527639706B7148_41c2d14a98f2e813999d86c442441e9c.bin",
      "logicalName": "Voz de sistema en Home (ACB)",
      "description": "Banco de voz de anunciador y sistema para la interfaz principal."
    },
    {
      "id": "home-system-voice-awb",
      "kind": "resource",
      "octoId": 18,
      "names": ["voice_system_001.awb"],
      "objectName": "p0y1hG",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/5_unknown/527639706B7148_41c2d14a98f2e813999d86c442441e9c.bin",
      "logicalName": "Voz de sistema en Home (AWB)",
      "description": "Stream de voz de anunciador y sistema para la interfaz principal."
    },
    {
      "id": "home-effect-ui-009",
      "kind": "assetBundle",
      "octoId": 19,
      "names": ["effect/ui/ef_ui_009/ef_ui_009.unity3d"],
      "objectName": "RzbbLs",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/3_unity_bundles/41527A62624C73_a69c771a94b942ff35373c93b968593b.bundle",
      "logicalName": "Home UI effect 009",
      "description": "Efecto de interfaz precargado por HomeScene."
    },
    {
      "id": "home-effect-ui-010",
      "kind": "assetBundle",
      "octoId": 20,
      "names": ["effect/ui/ef_ui_010/ef_ui_010.unity3d"],
      "objectName": "WsVyn1",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/3_unity_bundles/41577356796E31_08a931f87e694b0012766edff770c005.bundle",
      "logicalName": "Home UI effect 010",
      "description": "Efecto de interfaz precargado por HomeScene."
    },
    {
      "id": "home-effect-wp-010-001",
      "kind": "assetBundle",
      "octoId": 21,
      "names": ["effect/wp/ef_wp_010_001/ef_wp_010_001.unity3d"],
      "objectName": "zhpyFL",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/3_unity_bundles/417A687079464C_9ccd0c3bf0af2570f9cbeefdf5fc983e.bundle",
      "logicalName": "Home weapon effect 010 001",
      "description": "Efecto de arma precargado por HomeScene."
    },
    {
      "id": "home-field-scene-bundle",
      "kind": "assetBundle",
      "octoId": 22,
      "names": ["field/fld99999.unity3d"],
      "objectName": "sSdS55",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/3_unity_bundles/41735364533535_54566f0dee5ee791e1c0873ce0cd37d9.bundle",
      "logicalName": "Home field scene FLD99999",
      "description": "Escena de fondo requerida por HomeScene.PreBeginAsync."
    },
    {
      "id": "home-effect-fd-001",
      "kind": "assetBundle",
      "octoId": 23,
      "names": ["effect/fd/ef_fd_001/ef_fd_001.unity3d"],
      "objectName": "CQsr7i",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/3_unity_bundles/41435173723769_5ae751b6f3723396ca93c7a954b5c639.bundle",
      "logicalName": "Home field effect 001",
      "description": "Efecto de ambiente precargado por HomeScene."
    },
    {
      "id": "home-effect-fd-003",
      "kind": "assetBundle",
      "octoId": 24,
      "names": ["effect/fd/ef_fd_003/ef_fd_003.unity3d"],
      "objectName": "1DRjtB",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/3_unity_bundles/413144526A7442_33c07361a66b4c4108b5922ca32b2526.bundle",
      "logicalName": "Home field effect 003",
      "description": "Efecto de ambiente precargado por HomeScene."
    },
    {
      "id": "home-effect-ui-001",
      "kind": "assetBundle",
      "octoId": 25,
      "names": ["effect/ui/ef_ui_001/ef_ui_001.unity3d"],
      "objectName": "AfCXxU",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/3_unity_bundles/41416643577855_904d8d5b1f5662ef9da5956021f7d221.bundle",
      "logicalName": "Home UI effect 001",
      "description": "Efecto de interfaz precargado por HomeScene."
    },
    {
      "id": "home-effect-ui-004",
      "kind": "assetBundle",
      "octoId": 26,
      "names": ["effect/ui/ef_ui_004/ef_ui_004.unity3d"],
      "objectName": "DJrn2x",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/3_unity_bundles/41444A726E3278_970209597e7c818d87a1d0eb63d7ebb9.bundle",
      "logicalName": "Home UI effect 004",
      "description": "Efecto de interfaz precargado por HomeScene."
    },
    {
      "id": "home-effect-ui-005",
      "kind": "assetBundle",
      "octoId": 27,
      "names": ["effect/ui/ef_ui_005/ef_ui_005.unity3d"],
      "objectName": "U7m2AS",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/3_unity_bundles/4155376D324153_d6a635a053c50175e5daa7c67469b6a5.bundle",
      "logicalName": "Home UI effect 005",
      "description": "Efecto de interfaz precargado por HomeScene."
    },
    {
      "id": "home-effect-ui-007",
      "kind": "assetBundle",
      "octoId": 28,
      "names": ["effect/ui/ef_ui_007/ef_ui_007.unity3d"],
      "objectName": "fFPTCE",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/3_unity_bundles/41664650544345_ebc5c0ae054ac650383ed692cec93b5f.bundle",
      "logicalName": "Home UI effect 007",
      "description": "Efecto de interfaz precargado por HomeScene."
    }
]

# Track seen object names and registered paths to avoid duplicates
entries_by_obj = {}
for e in core_entries:
    entries_by_obj[e["objectName"]] = e

next_octo_id = 29

# Localized Atlas bundles
atlas_map = {
    "out_game_00": "ui/localize/zh/atlas/out_game_00.unity3d",
    "in_game_00": "ui/localize/zh/atlas/in_game_00.unity3d",
    "in_game_01": "ui/localize/zh/atlas/in_game_01.unity3d",
    "in_game_02": "ui/localize/zh/atlas/in_game_02.unity3d",
    "in_game_03": "ui/localize/zh/atlas/in_game_03.unity3d"
}
for base_name, zh_path in atlas_map.items():
    if zh_path in bundle_by_name:
        binfo = bundle_by_name[zh_path]
        obj = binfo["objectName"]
        names = [
            f"ui/localize/zh/atlas/{base_name}.unity3d",
            f"ui/localize/es/atlas/{base_name}.unity3d",
            f"ui/localize/en/atlas/{base_name}.unity3d"
        ]
        if obj in entries_by_obj:
            for n in names:
                if n not in entries_by_obj[obj]["names"]:
                    entries_by_obj[obj]["names"].append(n)
        else:
            e = {
                "id": f"localize-atlas-{base_name}",
                "kind": "assetBundle",
                "octoId": next_octo_id,
                "names": names,
                "objectName": obj,
                "sourcePath": binfo["sourcePath"],
                "logicalName": f"Localized Atlas {base_name}",
                "description": f"Atlas de UI localizado ({base_name}) con soporte espanol/ingles/chino."
            }
            next_octo_id += 1
            entries_by_obj[obj] = e

# Add voice CRI for each kicker
for k in range(1, 15):
    k_name = kicker_names[k]
    v_bin = voice_files[k]
    v_hex = v_bin.split("_")[0]
    v_obj = bytes.fromhex(v_hex).decode("ascii")[1:]
    v_names = [f"voice_pc_{k:03d}.acb", f"voice_pc_{k:03d}.awb"]
    if v_obj in entries_by_obj:
        for n in v_names:
            if n not in entries_by_obj[v_obj]["names"]:
                entries_by_obj[v_obj]["names"].append(n)
    else:
        e = {
            "id": f"kicker-pc-{k:03d}-voice",
            "kind": "resource",
            "octoId": next_octo_id,
            "names": v_names,
            "objectName": v_obj,
            "sourcePath": f"{octo_unknown_dir}/{v_bin}",
            "logicalName": f"Voz de {k_name} (ACB/AWB)",
            "description": f"Banco de audio de voz de {k_name}."
        }
        next_octo_id += 1
        entries_by_obj[v_obj] = e

# Add camera for each kicker
for k in range(1, 15):
    k_name = kicker_names[k]
    cam_name = f"player/pc_{k:03d}/camera/bg_rc_{k:03d}.unity3d"
    if cam_name in bundle_by_name:
        binfo = bundle_by_name[cam_name]
        obj = binfo["objectName"]
        if obj in entries_by_obj:
            if cam_name not in entries_by_obj[obj]["names"]:
                entries_by_obj[obj]["names"].append(cam_name)
        else:
            e = {
                "id": f"kicker-pc-{k:03d}-camera",
                "kind": "assetBundle",
                "octoId": next_octo_id,
                "names": [cam_name],
                "objectName": obj,
                "sourcePath": binfo["sourcePath"],
                "logicalName": f"{k_name} Camera bg_rc_{k:03d}",
                "description": f"Animacion de camara para {k_name}."
            }
            next_octo_id += 1
            entries_by_obj[obj] = e

# Add all kicker bundles
for k in range(1, 15):
    k_name = kicker_names[k]
    k_bundles = sorted([n for n in bundle_by_name if f"pc_{k:03d}" in n or f"wp_{k:03d}" in n])
    for bpath in k_bundles:
        binfo = bundle_by_name[bpath]
        obj = binfo["objectName"]
        if obj in entries_by_obj:
            if bpath not in entries_by_obj[obj]["names"]:
                entries_by_obj[obj]["names"].append(bpath)
        else:
            safe_id = re.sub(r"[^a-zA-Z0-9]+", "-", bpath.replace(".unity3d", ""))
            e = {
                "id": safe_id,
                "kind": "assetBundle",
                "octoId": next_octo_id,
                "names": [bpath],
                "objectName": obj,
                "sourcePath": binfo["sourcePath"],
                "logicalName": f"{k_name} bundle {os.path.basename(bpath)}",
                "description": f"Recurso de {k_name}: {bpath}"
            }
            next_octo_id += 1
            entries_by_obj[obj] = e

# Add global shaders
shaders = [
    {
      "id": "global-original-shader-bundle",
      "kind": "assetBundle",
      "names": ["originalshader.unity3d"],
      "objectName": "ObS3Vr",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/3_unity_bundles/414F6253335672_fb3779323e5fd41eb272a85869bd958f.bundle",
      "logicalName": "Original game shaders",
      "description": "Shaders globales de Kick-Flight requeridos por los materiales del escenario y de los personajes."
    },
    {
      "id": "preload-game-shader-variants-bundle",
      "kind": "assetBundle",
      "names": ["shader/preloadgameshadervariants.unity3d"],
      "objectName": "aBVuhl",
      "sourcePath": "../Kick-Flight-Assets/octo_sorted/3_unity_bundles/4161425675686C_c1148b13a0ef2b9bfbe0fbc16c64e80c.bundle",
      "logicalName": "Preloaded game shader variants",
      "description": "Coleccion de variantes que GameManager carga y precalienta antes de renderizar escenas 3D."
    }
]

for s in shaders:
    obj = s["objectName"]
    if obj not in entries_by_obj:
        s_copy = dict(s)
        s_copy["octoId"] = next_octo_id
        next_octo_id += 1
        entries_by_obj[obj] = s_copy

# Add battle rule, league, and badge UI thumbnail bundles
ui_thumbnails = sorted([n for n in bundle_by_name if n.startswith("ui/battlerule/") or n.startswith("ui/league/") or n.startswith("ui/badge/")])
for bpath in ui_thumbnails:
    binfo = bundle_by_name[bpath]
    obj = binfo["objectName"]
    if obj in entries_by_obj:
        if bpath not in entries_by_obj[obj]["names"]:
            entries_by_obj[obj]["names"].append(bpath)
    else:
        safe_id = re.sub(r"[^a-zA-Z0-9]+", "-", bpath.replace(".unity3d", ""))
        e = {
            "id": safe_id,
            "kind": "assetBundle",
            "octoId": next_octo_id,
            "names": [bpath],
            "objectName": obj,
            "sourcePath": binfo["sourcePath"],
            "logicalName": f"UI Thumbnail {os.path.basename(bpath)}",
            "description": f"Thumbnail UI resource: {bpath}"
        }
        next_octo_id += 1
        entries_by_obj[obj] = e

# Final list of entries ordered by octoId
final_entries = sorted(entries_by_obj.values(), key=lambda x: x["octoId"])

new_definition = {
    "schemaVersion": 1,
    "assetVersion": 12345,
    "revision": 15,
    "fromRevisions": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    "urlPathFormat": "/cdn/{o}",
    "entries": final_entries
}

with open(title_min_path, "w", encoding="utf-8") as f:
    json.dump(new_definition, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(f"Generated {len(final_entries)} unique object entries in {title_min_path} (Revision 14)")
