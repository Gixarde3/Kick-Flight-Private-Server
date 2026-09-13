#!/usr/bin/env python3
"""
match_disc_cards.py - identify the disc on an in-game disc-detail screenshot.

Template-matches the card art of every screenshot against the 126 disc thumbnails shipped in the APK
(ui/disc/thumbnail_3010NNN, decoded by the assets pipeline into
Kick-Flight-Assets/PIPELINE_OUTPUT_V3/2_converted_unity_assets/images/Sprite/...). Only the fully
opaque middle of the arch-shaped thumbnail is used as the template (the rarity badge covers its
bottom on the card), at four scales, over the bottom half of tall screenshots (3D render on top).
A genuine match scores >= 0.9 (TM_CCOEFF_NORMED); the runner-up is always < 0.6.

    pip install opencv-python-headless
    python scripts/match_disc_cards.py ../Disc_data [--out docs/disc_cards_matches.json]

Result of the 2026-09-13 run (82 cards + transcribed text) lives in docs/disc_cards.json.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT.parent / "Kick-Flight-Assets"
CATALOG = ASSETS / "KickFlight-Reconstructed" / "Assets" / "StreamingAssets" / "kf" / "catalog.json"
SPRITES = ASSETS / "PIPELINE_OUTPUT_V3" / "2_converted_unity_assets" / "images" / "Sprite"


def load_thumbnails() -> dict[str, np.ndarray]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    thumbs = {}
    for asset in catalog["assets"]:
        if not asset["name"].startswith("ui/disc/thumbnail_"):
            continue
        disc_id = asset["name"].split("_")[1].split(".")[0]
        pngs = glob.glob(str(SPRITES / asset["file"][:-7] / "*" / "*.png"))
        if not pngs:
            continue
        t = cv2.imread(pngs[0], cv2.IMREAD_UNCHANGED)
        alpha = t[:, :, 3:4].astype(np.float32) / 255
        thumbs[disc_id] = (t[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return thumbs


def match(image_path: str, thumbs: dict[str, np.ndarray], scales=(100, 106, 112, 118)) -> list[tuple[float, str]]:
    im = cv2.imread(image_path)
    if im.shape[0] > im.shape[1] * 0.7:
        im = im[im.shape[0] // 2:]
    scores = []
    for disc_id, t in thumbs.items():
        best = -1.0
        for w in scales:
            h = int(t.shape[0] * w / t.shape[1])
            tt = cv2.resize(t, (w, h), interpolation=cv2.INTER_AREA)[int(h * 0.2):int(h * 0.62), int(w * 0.1):int(w * 0.9)]
            best = max(best, float(cv2.matchTemplate(im, tt, cv2.TM_CCOEFF_NORMED).max()))
        scores.append((best, disc_id))
    scores.sort(reverse=True)
    return scores[:3]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("screenshots", help="folder with the card PNGs")
    ap.add_argument("--out", help="write {screenshot: [[score, discId], ...]} JSON here")
    args = ap.parse_args()
    thumbs = load_thumbnails()
    if not thumbs:
        sys.exit(f"no thumbnails found under {SPRITES}")
    result = {}
    for f in sorted(glob.glob(os.path.join(args.screenshots, "*.png"))):
        top = match(f, thumbs)
        result[os.path.basename(f)] = top
        verdict = top[0][1] if top[0][0] >= 0.9 else "?? (no thumbnail captured for this disc, or not a card)"
        print(f"{os.path.basename(f)}: {verdict}   top3={[(d, round(s, 3)) for s, d in top]}")
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
