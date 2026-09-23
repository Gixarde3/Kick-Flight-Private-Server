#!/usr/bin/env python3
"""Build the directory nginx serves /cdn/ from.

The client downloads every asset from ``{scheme}://{host}/cdn/{o}`` (see ``OctoDatabaseUrl`` in
``Program.cs``) and ``config/resources/catalog.json`` addresses each bundle as ``/cdn/<key>``. nginx is
pointed at ``<assets-root>/cdn`` (``deploy/nginx.conf``), so this script lays that directory out as one
entry per object key, named after the key.

Entries are hardlinks, not symlinks: a symlink stores an absolute path, which would force nginx to mount
every directory a bundle lives in at the exact path the link was authored with. A hardlink is the same
inode under a second name, so the farm is self-contained - nginx mounts the assets dataset and nothing
else. Nearly everything resolves inside the assets tree, but 13 UI bundles are addressed as
``content/resources/...`` and live in the repository; those come from another dataset, where a hardlink is
impossible, so they are copied (a few MB in total).

The farm is deleted and rebuilt on every run. Rebuilding is a few seconds for 2600 entries and removes all
staleness bookkeeping, so a re-run after regenerating the catalog is always correct.

Run it where the assets tree lives - on the NAS, after uploading ``octo_sorted``:

    python3 scripts/build-cdn-tree.py \\
        --assets-root /mnt/Tanuki_1/kickflight/assets \\
        --repo-root /mnt/Tanuki_1/kickflight/app
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

CDN_PREFIX = "/cdn/"
ASSETS_TREE = "octo_sorted"


def load_catalog(catalog_path: Path) -> list[dict]:
    with catalog_path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    schema = document.get("schemaVersion", 1)
    if schema != 1:
        sys.exit(f"unsupported catalog schema {schema} in {catalog_path}")
    return document.get("resources", [])


def resolve_source(source_path: str, assets_root: Path, repo_root: Path) -> Path:
    """Map a catalog sourcePath onto the file it names.

    Paths are written relative to the repository root, so they are resolved the same way the server
    resolves them (``RepositoryPaths.Resolve``): most point into the sibling assets tree, a few into the
    repository's own content/.
    """
    normalized = source_path.replace("\\", "/")
    while normalized.startswith("../"):
        normalized = normalized[3:]
    normalized = normalized.lstrip("/")
    if normalized.startswith("Kick-Flight-Assets/"):
        return assets_root / normalized[len("Kick-Flight-Assets/"):]
    return repo_root / normalized


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catalog", default="config/resources/catalog.json",
                        help="resource catalog (default: %(default)s)")
    parser.add_argument("--assets-root", required=True,
                        help="directory holding octo_sorted/, e.g. /mnt/Tanuki_1/kickflight/assets")
    parser.add_argument("--repo-root", default=".",
                        help="repository root the catalog's relative paths resolve against (default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true", help="report what would happen, write nothing")
    args = parser.parse_args()

    assets_root = Path(args.assets_root).resolve()
    repo_root = Path(args.repo_root).resolve()
    if not assets_root.is_dir():
        sys.exit(f"assets root does not exist: {assets_root}")

    catalog_path = repo_root / args.catalog if not Path(args.catalog).is_absolute() else Path(args.catalog)
    if not catalog_path.is_file():
        sys.exit(f"catalog not found: {catalog_path}")

    resources = load_catalog(catalog_path)

    wanted: dict[str, Path] = {}
    skipped_disabled = skipped_not_cdn = 0
    for resource in resources:
        request_path = resource.get("requestPath", "")
        if not resource.get("enabled", True):
            skipped_disabled += 1
            continue
        if not request_path.startswith(CDN_PREFIX):
            skipped_not_cdn += 1
            continue
        key = request_path[len(CDN_PREFIX):]
        if not key or "/" in key:
            sys.exit(f"unexpected CDN key {request_path!r}; the farm is a flat directory")
        wanted[key] = resolve_source(resource["sourcePath"], assets_root, repo_root)

    missing = {key: source for key, source in wanted.items() if not source.is_file()}
    if missing:
        sample = "\n".join(f"  {key} -> {source}" for key, source in list(missing.items())[:10])
        sys.exit(f"{len(missing)} of {len(wanted)} catalog entries point at files that are not present:\n"
                 f"{sample}\nUpload the asset tree first, or pass the right --assets-root/--repo-root.")

    cdn_dir = assets_root / "cdn"
    in_tree = sum(1 for source in wanted.values() if assets_root in source.parents)

    if args.dry_run:
        print(f"dry run: would rebuild {cdn_dir} with {len(wanted)} keys")
        print(f"  {in_tree} hardlinked from {ASSETS_TREE}/, {len(wanted) - in_tree} copied from the repository")
        print(f"  {skipped_not_cdn} non-CDN resources, {skipped_disabled} disabled")
        return 0

    # Rebuild from scratch so a key that left the catalog cannot linger and keep serving stale content.
    if cdn_dir.exists():
        shutil.rmtree(cdn_dir)
    cdn_dir.mkdir(parents=True)

    linked = copied = 0
    copied_bytes = 0
    for key, source in sorted(wanted.items()):
        link = cdn_dir / key
        try:
            os.link(source, link)
            linked += 1
        except OSError:
            # Different dataset (or filesystem): fall back to a copy.
            shutil.copy2(source, link)
            copied += 1
            copied_bytes += source.stat().st_size

    print(f"{cdn_dir}: {len(wanted)} keys ({linked} hardlinked, {copied} copied, {copied_bytes / 1e6:.1f} MB)")
    print(f"  {skipped_not_cdn} non-CDN resources, {skipped_disabled} disabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
