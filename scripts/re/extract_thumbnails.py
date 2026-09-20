"""Extract kicker and disc thumbnails from the Octo bundles to PNG for the balance WebUI.

    python scripts/re/extract_thumbnails.py   -> tools/balance/icons/kicker_<id>.png, disc_<id>.png
"""
import json, os, re, sys
import UnityPy
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "..", "Kick-Flight-Assets"))
from reconstruct_unity_bundles import repair_bundle_bytes  # noqa: E402
cat = json.load(open(os.path.join(ROOT, "config/resources/catalog.json"), encoding="utf-8"))["resources"]
out = os.path.join(ROOT, "tools", "balance", "icons"); os.makedirs(out, exist_ok=True)
n = 0
for r in cat:
    ln = r.get("logicalName", "")
    m = re.search(r"ui/kicker/thumbnail_pc_(\d{3})_001\.unity3d$", ln) or re.search(r"ui/disc/thumbnail_(\d+)\.unity3d$", ln)
    if not m: continue
    name = ("kicker_%d" % int(m.group(1))) if "kicker" in ln else ("disc_%s" % m.group(1))
    env = UnityPy.load(repair_bundle_bytes(open(os.path.join(ROOT, r["sourcePath"]), "rb").read()).data)
    for o in env.objects:
        if o.type.name in ("Texture2D", "Sprite"):
            img = o.read().image
            if img.width < 32: continue
            img.save(os.path.join(out, name + ".png")); n += 1; break
print("extracted", n)
