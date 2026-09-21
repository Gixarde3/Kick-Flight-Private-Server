"""Print the GameObject hierarchy (name, local position / euler rotation / scale) of every prefab in a
Kick-Flight asset bundle, resolved through config/resources/catalog.json by logical name.

    python scripts/re/bundle_tree.py player/pc_005/pc_005_001 [--filter Prop] [--all]

Without --all only nodes whose name matches --filter (default: Prop|wp_|Grip|Hips|Bag|Spine|Hand|Root) and their
ancestors are printed. Used to pick `Weapon` master bone names (PlayerModelControllerBase.GetBone is a
Transform.FindRecursive on the body prefab).
"""
import argparse
import json
import math
import os
import re
import sys

import UnityPy

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def find_bundle(logical: str) -> str:
    cat = json.load(open(os.path.join(ROOT, "config/resources/catalog.json"), encoding="utf-8"))
    for r in cat["resources"]:
        ln = r.get("logicalName", "")
        if ln.endswith(logical + ".unity3d") or ln.endswith(logical):
            return os.path.normpath(os.path.join(ROOT, r["sourcePath"]))
    raise SystemExit(f"not in catalog: {logical}")


def quat_to_euler(q):
    x, y, z, w = q.x, q.y, q.z, q.w
    t0 = 2 * (w * x + y * z); t1 = 1 - 2 * (x * x + y * y)
    roll = math.degrees(math.atan2(t0, t1))
    t2 = max(-1.0, min(1.0, 2 * (w * y - z * x)))
    pitch = math.degrees(math.asin(t2))
    t3 = 2 * (w * z + x * y); t4 = 1 - 2 * (y * y + z * z)
    yaw = math.degrees(math.atan2(t3, t4))
    return roll, pitch, yaw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logical")
    ap.add_argument("--filter", default=r"Prop|wp_|Grip|Hips|Bag|Spine|Hand|Root|Arm|Wrist|Shoulder|Neck|Head")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    path = find_bundle(a.logical)
    # Octo files carry an XOR-obfuscated UnityFS header; the assets repo's repair tool rebuilds a standard bundle.
    sys.path.insert(0, os.path.join(ROOT, "..", "Kick-Flight-Assets"))
    from reconstruct_unity_bundles import repair_bundle_bytes  # noqa: E402
    env = UnityPy.load(repair_bundle_bytes(open(path, "rb").read()).data)
    pat = re.compile(a.filter, re.I)
    for obj in env.objects:
        if obj.type.name != "Transform":
            continue
        t = obj.read()
        if t.m_Father.path_id != 0:
            continue  # only roots
        printed = set()

        def walk(tr, depth, chain):
            go = tr.m_GameObject.read()
            name = go.m_Name
            chain = chain + [(tr, depth, name)]
            kids = [c.read() for c in tr.m_Children]
            hit = a.all or pat.search(name)
            if hit:
                for (ct, cd, cn) in chain:
                    if id(ct) in printed:
                        continue
                    printed.add(id(ct))
                    p = ct.m_LocalPosition; r = quat_to_euler(ct.m_LocalRotation); s = ct.m_LocalScale
                    print(f"{'  ' * cd}{cn}  pos=({p.x:.3f},{p.y:.3f},{p.z:.3f}) rot=({r[0]:.0f},{r[1]:.0f},{r[2]:.0f}) scale=({s.x:.2f},{s.y:.2f},{s.z:.2f})")
            for k in kids:
                walk(k, depth + 1, chain)

        walk(t, 0, [])


if __name__ == "__main__":
    main()
