#!/usr/bin/env python3
"""Where every localized UI text sits: docs/localize_layout.json for the balance web UI's Text tab.

Reads the APK's built-in Unity data (assets/bin/Data/data.unity3d of a decoded base.apk - .local/build/decoded after
any .local/build.sh run, or --data <path>) with UnityPy, finds every LocalizeText / LocalizeTextMeshPro component
(MonoBehaviours whose m_Script is MonoScript 268 / 544 in globalgamemanagers.assets), reads its TranslationInfo._key
from the raw bytes (the MonoBehaviour typetree is stripped) and walks its RectTransform chain to compute an approximate
rectangle in its root canvas. Unity's anchor maths is applied (anchorMin/Max, pivot, anchoredPosition, sizeDelta);
roots with a stretched/zero size are assumed to be the 1080x1920 portrait canvas. Layout groups, scroll rects and
runtime instantiation are ignored, so the result is a wireframe, not a screenshot.

Output rows: {key, screen (root GameObject), path, x, y, w, h, font} with y measured from the TOP of the screen.

    python scripts/extract_localize_layout.py [--data <data.unity3d>]
"""
import argparse
import json
import re
import struct
from pathlib import Path

import UnityPy

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / ".local" / "build" / "decoded" / "assets" / "bin" / "Data" / "data.unity3d"
OUT = ROOT / "docs" / "localize_layout.json"
LOCALIZE_SCRIPTS = {268: "LocalizeText", 544: "LocalizeTextMeshPro"}
KEY_RE = re.compile(r"^[a-zA-Z][A-Za-z0-9]*\.[A-Za-z0-9_.]+$")
CANVAS = (1080.0, 1920.0)


def strings_in(raw: bytes):
    i, n = 0, len(raw)
    while i + 4 <= n:
        length = struct.unpack_from("<i", raw, i)[0]
        if 0 < length < 400 and i + 4 + length <= n:
            try:
                text = raw[i + 4:i + 4 + length].decode("utf-8")
                if length >= 2 and all(c >= " " or c == "\n" for c in text):
                    yield text
                    i += 4 + ((length + 3) & ~3)
                    continue
            except UnicodeDecodeError:
                pass
        i += 4


def rect_chain(af, path_id):
    """[(RectTransform object, GameObject name)] from this transform up to the root."""
    chain = []
    seen = set()
    while path_id and path_id not in seen:
        seen.add(path_id)
        obj = af.objects.get(path_id)
        if obj is None or obj.type.name != "RectTransform":
            break
        rt = obj.read()
        try:
            name = af.objects[rt.m_GameObject.path_id].read().m_Name
        except Exception:
            name = "?"
        chain.append((rt, name))
        path_id = rt.m_Father.path_id
    return chain


def layout(chain):
    """Approximate rect of chain[0] in root space: (x, y_from_top, w, h, root_name, path)."""
    parent_w, parent_h = CANVAS
    parent_x, parent_y = 0.0, 0.0  # bottom-left of parent in root space
    for rt, _name in reversed(chain):
        amin, amax, piv = rt.m_AnchorMin, rt.m_AnchorMax, rt.m_Pivot
        ap, sd = rt.m_AnchoredPosition, rt.m_SizeDelta
        ref_min_x, ref_min_y = amin.x * parent_w, amin.y * parent_h
        ref_max_x, ref_max_y = amax.x * parent_w, amax.y * parent_h
        w = (ref_max_x - ref_min_x) + sd.x
        h = (ref_max_y - ref_min_y) + sd.y
        if rt is chain[-1] and (w <= 0 or h <= 0):
            w, h = CANVAS
            ref_min_x = ref_min_y = 0.0
            ref_max_x, ref_max_y = w, h
        pivot_x = ref_min_x + (ref_max_x - ref_min_x) * piv.x + ap.x
        pivot_y = ref_min_y + (ref_max_y - ref_min_y) * piv.y + ap.y
        min_x = parent_x + pivot_x - w * piv.x
        min_y = parent_y + pivot_y - h * piv.y
        parent_x, parent_y, parent_w, parent_h = min_x, min_y, max(w, 0.0), max(h, 0.0)
    root_h = CANVAS[1]
    return parent_x, root_h - (parent_y + parent_h), parent_w, parent_h


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    args = ap.parse_args()
    env = UnityPy.load(args.data)
    rows = []
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        raw = obj.get_raw_data()
        if len(raw) < 28:
            continue
        _fid, script_id = struct.unpack_from("<iq", raw, 16)
        if script_id not in LOCALIZE_SCRIPTS:
            continue
        go_id = struct.unpack_from("<iq", raw, 0)[1]
        texts = list(strings_in(raw))
        keys = [t for t in texts if KEY_RE.match(t)]
        if not keys:
            continue
        af = obj.assets_file
        go = af.objects.get(go_id)
        chain = []
        if go is not None:
            g = go.read()
            for c in g.m_Component:
                comp = getattr(c, "component", c)
                tobj = af.objects.get(comp.path_id)
                if tobj is not None and tobj.type.name == "RectTransform":
                    chain = rect_chain(af, comp.path_id)
                    break
        if not chain:
            continue
        x, y, w, h = layout(chain)
        font = 0
        if LOCALIZE_SCRIPTS[script_id] == "LocalizeText":
            # UnityEngine.UI.Text: m_FontData.m_FontSize is the int right after the font PPtr; too fragile to find
            # in raw bytes, so estimate from the height instead
            font = int(min(max(h * 0.6, 14), 80))
        rows.append({
            "key": keys[0], "component": LOCALIZE_SCRIPTS[script_id],
            "screen": chain[-1][1], "path": "/".join(name for _rt, name in reversed(chain)),
            "x": round(x, 1), "y": round(y, 1), "w": round(w, 1), "h": round(h, 1), "font": font,
        })
    rows.sort(key=lambda r: (r["screen"], r["y"], r["x"]))
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    screens = {r["screen"] for r in rows}
    print(f"{len(rows)} localized texts in {len(screens)} screens -> {OUT.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
