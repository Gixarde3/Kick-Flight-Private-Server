"""Recover the Weapon-master bone / rootName pair for a kicker from its animation clips.

Unity animation clips bind transforms by CRC32 of the full path under the Animator root. The body prefab gives
every body path; anything left over in the kicker's clips is a weapon node reachable only as
<body bone path>/<rootName>/<weapon prefab path>, where rootName is the name Weapon.Initialize gives the
instantiated weapon model (WeaponMasterData.rootName). Brute-forcing bone x rootName x weapon node against the
unexplained hashes identifies both.

    python scripts/re/anim_paths.py 010 --weapons 001_001,001_201 [--roots extra,names]
"""
import argparse
import json
import os
import sys
import zlib

import UnityPy

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "..", "Kick-Flight-Assets"))
from reconstruct_unity_bundles import repair_bundle_bytes  # noqa: E402

CAT = json.load(open(os.path.join(ROOT, "config/resources/catalog.json"), encoding="utf-8"))["resources"]


def load(logical_suffix):
    for r in CAT:
        if r.get("logicalName", "").endswith(logical_suffix):
            p = os.path.normpath(os.path.join(ROOT, r["sourcePath"]))
            return UnityPy.load(repair_bundle_bytes(open(p, "rb").read()).data)
    raise SystemExit("not in catalog: " + logical_suffix)


def hierarchy_paths(env):
    """All transform paths (relative to the prefab root, root itself = '') of every prefab in the bundle."""
    out = {}
    tf = {o.path_id: o for o in env.objects if o.type.name == "Transform"}
    parent = {}
    name = {}
    for pid, o in tf.items():
        t = o.read()
        parent[pid] = t.m_Father.path_id
        name[pid] = t.m_GameObject.read().m_Name
    for pid in tf:
        chain = []
        cur = pid
        while cur and cur in parent:
            chain.append(name[cur])
            cur = parent[cur]
        chain.reverse()
        out["/".join(chain[1:])] = chain[0]  # path relative to root -> root name
    return out


def crc(s):
    return zlib.crc32(s.encode("utf-8")) & 0xFFFFFFFF


def clip_hashes(env):
    hashes = {}
    for o in env.objects:
        if o.type.name != "AnimationClip":
            continue
        c = o.read()
        tree = c.object_reader.read_typetree() if hasattr(c, "object_reader") else o.read_typetree()
        for b in tree["m_ClipBindingConstant"]["genericBindings"]:
            hashes.setdefault(b["path"], set()).add(tree["m_Name"])
    return hashes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kicker", help="three-digit kicker id, e.g. 010")
    ap.add_argument("--weapons", default="001_001", help="comma list of <model>_<prop> weapon suffixes")
    ap.add_argument("--roots", default="", help="extra rootName candidates")
    ap.add_argument("--animators", default="001,101", help="animator bundle suffixes to scan")
    a = ap.parse_args()
    k = a.kicker

    body = load(f"player/pc_{k}/pc_{k}_001.unity3d")
    body_paths = hierarchy_paths(body)
    known = {crc(p): p for p in body_paths if p}
    hashes = {}
    for suf in a.animators.split(","):
        try:
            env = load(f"player/pc_{k}/animator/pc_{k}_{suf}.unity3d")
        except SystemExit:
            continue
        for h, clips in clip_hashes(env).items():
            hashes.setdefault(h, set()).update(clips)
    unknown = {h: c for h, c in hashes.items() if h not in known and h != 0}
    print(f"body paths: {len(body_paths)}  clip path hashes: {len(hashes)}  unexplained: {len(unknown)}")

    weapon_nodes = {}
    roots = set(filter(None, a.roots.split(",")))
    for w in a.weapons.split(","):
        env = load(f"weapon/wp_{k}/wp_{k}_{w}.unity3d")
        paths = hierarchy_paths(env)
        for p, root in paths.items():
            weapon_nodes[p] = root
            roots.add(root)
    roots |= {f"wp_{k}", "Weapon", "weapon", "Prop", "prop", "wp"}
    bones = [p for p in body_paths if p]
    found = {}
    for h in unknown:
        for bone in bones:
            for r in roots:
                for wn in weapon_nodes:
                    cand = f"{bone}/{r}" + (f"/{wn}" if wn else "")
                    if crc(cand) == h:
                        found[h] = cand
                # also: weapon attached with no rename, directly under the bone
                for wn in weapon_nodes:
                    if wn and crc(f"{bone}/{wn}") == h:
                        found[h] = f"{bone}/{wn}"
    for h, c in sorted(unknown.items(), key=lambda kv: -len(kv[1])):
        print(f"{h:08x}  {found.get(h, '?'):60s}  clips={len(c)}  e.g. {sorted(c)[:3]}")


if __name__ == "__main__":
    main()
