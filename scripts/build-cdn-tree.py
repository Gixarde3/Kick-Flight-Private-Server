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
import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_resources(resources: list[dict], assets_root: Path, repo_root: Path,
                       all_enabled: bool) -> tuple[dict[str, Path], int, int]:
    """Validate source presence and, when requested, every enabled catalog SHA."""
    wanted: dict[str, Path] = {}
    source_rows: list[tuple[str, Path, str]] = []
    seen_paths: set[str] = set()
    skipped_disabled = skipped_not_cdn = 0

    for resource in resources:
        if not resource.get("enabled", True):
            skipped_disabled += 1
            continue

        request_path = str(resource.get("requestPath", ""))
        source_path = resource.get("sourcePath")
        if not isinstance(source_path, str) or not source_path:
            sys.exit(f"enabled resource {request_path!r} has no sourcePath")
        source = resolve_source(source_path, assets_root, repo_root)
        expected = str(resource.get("sha256", "")).lower()
        source_rows.append((request_path, source, expected))

        if not request_path.startswith(CDN_PREFIX):
            skipped_not_cdn += 1
            if all_enabled and (not request_path.startswith("/") or ".." in request_path.split("/")):
                sys.exit(f"unexpected enabled request path {request_path!r}")
            continue

        key = request_path[len(CDN_PREFIX):]
        if not key or "/" in key:
            sys.exit(f"unexpected CDN key {request_path!r}; the farm is a flat directory")
        if key in wanted:
            sys.exit(f"duplicate enabled CDN key {key!r}")
        wanted[key] = source

    missing = [(request_path, source) for request_path, source, _ in source_rows if not source.is_file()]
    if missing:
        lines = "\n".join(f"  {request_path}: {source}" for request_path, source in missing)
        sys.exit(f"{len(missing)} enabled catalog source(s) are missing:\n{lines}")

    if all_enabled:
        mismatch: list[tuple[str, Path, str, str]] = []
        invalid: list[tuple[str, str]] = []
        digest_cache: dict[tuple[int, int, int, int], str] = {}
        for request_path, source, expected in source_rows:
            if not re.fullmatch(r"[0-9a-f]{64}", expected):
                invalid.append((request_path, expected))
                continue
            stat = source.stat()
            identity = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
            actual = digest_cache.get(identity)
            if actual is None:
                actual = sha256(source)
                digest_cache[identity] = actual
            if actual != expected:
                mismatch.append((request_path, source, expected, actual))
        if invalid or mismatch:
            details = [f"  {path}: invalid sha256 {value!r}" for path, value in invalid]
            details.extend(f"  {path}: expected {expected}, got {actual} ({source})"
                           for path, source, expected, actual in mismatch)
            sys.exit(f"{len(invalid) + len(mismatch)} enabled catalog checksum error(s):\n" + "\n".join(details))

    return wanted, skipped_not_cdn, skipped_disabled


def exchange_directories(first: Path, second: Path) -> None:
    """Atomically exchange two paths on Linux/macOS (same filesystem)."""
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is not None:
        renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        renameat2.restype = ctypes.c_int
        result = renameat2(-100, os.fsencode(first), -100, os.fsencode(second), 2)
    elif sys.platform == "darwin":
        renamex_np = getattr(libc, "renamex_np", None)
        if renamex_np is None:
            raise RuntimeError("atomic CDN replacement requires renamex_np(RENAME_SWAP)")
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        result = renamex_np(os.fsencode(first), os.fsencode(second), 2)
    else:
        raise RuntimeError("atomic CDN replacement requires renameat2(RENAME_EXCHANGE)")
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(second))


def restore_backup(assets_root: Path, backup: Path) -> None:
    current = assets_root / "cdn"
    if not backup.is_dir():
        raise RuntimeError(f"CDN rollback tree is missing: {backup}")
    if os.path.lexists(current):
        exchange_directories(backup, current)
        shutil.rmtree(backup)
    else:
        os.replace(backup, current)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catalog", default="config/resources/catalog.json",
                        help="resource catalog (default: %(default)s)")
    parser.add_argument("--assets-root", required=True,
                        help="directory holding octo_sorted/, e.g. /mnt/Tanuki_1/kickflight/assets")
    parser.add_argument("--repo-root", default=".",
                        help="repository root the catalog's relative paths resolve against (default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true", help="report what would happen, write nothing")
    parser.add_argument("--verify-all-enabled", action="store_true",
                        help="require every enabled catalog source (including non-CDN files) and verify its SHA-256")
    parser.add_argument("--atomic", action="store_true",
                        help="build beside cdn/ and atomically exchange the finished directory on Linux")
    parser.add_argument("--backup-dir", help="keep the previous CDN tree here after an atomic exchange")
    parser.add_argument("--restore-backup", help="restore a tree kept by --backup-dir and exit")
    args = parser.parse_args()

    assets_root = Path(args.assets_root).resolve()
    repo_root = Path(args.repo_root).resolve()
    if not assets_root.is_dir():
        sys.exit(f"assets root does not exist: {assets_root}")

    if args.restore_backup:
        try:
            restore_backup(assets_root, Path(args.restore_backup).resolve())
        except (OSError, RuntimeError) as error:
            sys.exit(f"CDN rollback failed: {error}")
        print(f"restored CDN tree from {args.restore_backup}")
        return 0

    catalog_path = repo_root / args.catalog if not Path(args.catalog).is_absolute() else Path(args.catalog)
    if not catalog_path.is_file():
        sys.exit(f"catalog not found: {catalog_path}")

    resources = load_catalog(catalog_path)

    wanted, skipped_not_cdn, skipped_disabled = validate_resources(
        resources, assets_root, repo_root, args.verify_all_enabled)

    cdn_dir = assets_root / "cdn"
    in_tree = sum(1 for source in wanted.values() if assets_root in source.parents)

    if args.dry_run:
        print(f"dry run: would rebuild {cdn_dir} with {len(wanted)} keys")
        print(f"  {in_tree} hardlinked from {ASSETS_TREE}/, {len(wanted) - in_tree} copied from the repository")
        print(f"  {skipped_not_cdn} non-CDN resources, {skipped_disabled} disabled")
        if args.verify_all_enabled:
            print("  all enabled source paths exist and match their catalog SHA-256")
        return 0

    stage_dir = Path(tempfile.mkdtemp(prefix=".cdn-stage-", dir=assets_root)) if args.atomic else cdn_dir
    if not args.atomic:
        # Preserve legacy local behavior; the deploy workflow uses --atomic.
        if cdn_dir.exists():
            shutil.rmtree(cdn_dir)
        cdn_dir.mkdir(parents=True)

    linked = copied = 0
    copied_bytes = 0
    try:
        for key, source in sorted(wanted.items()):
            link = stage_dir / key
            try:
                os.link(source, link)
                linked += 1
            except OSError:
                # Different dataset (or filesystem): fall back to a copy.
                shutil.copy2(source, link)
                copied += 1
                copied_bytes += source.stat().st_size
    except Exception:
        if args.atomic and stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)
        raise

    if args.atomic:
        backup_dir = Path(args.backup_dir).resolve() if args.backup_dir else None
        if backup_dir and os.path.lexists(backup_dir):
            shutil.rmtree(stage_dir)
            sys.exit(f"rollback directory already exists: {backup_dir}")
        exchanged = False
        try:
            if os.path.lexists(cdn_dir):
                exchange_directories(stage_dir, cdn_dir)
                exchanged = True
                if backup_dir:
                    os.replace(stage_dir, backup_dir)
                else:
                    shutil.rmtree(stage_dir)
            else:
                os.replace(stage_dir, cdn_dir)
        except (OSError, RuntimeError) as error:
            if exchanged and stage_dir.exists() and os.path.lexists(cdn_dir):
                try:
                    # A failed backup rename must put the original tree back before cleaning staging.
                    exchange_directories(stage_dir, cdn_dir)
                except (OSError, RuntimeError) as rollback_error:
                    sys.exit(f"atomic CDN replacement failed ({error}); automatic restore also failed ({rollback_error}); "
                             f"preserved paths: {cdn_dir} and {stage_dir}")
            if stage_dir.exists():
                shutil.rmtree(stage_dir)
            sys.exit(f"atomic CDN replacement failed; existing CDN tree was left in place: {error}")

    print(f"{cdn_dir}: {len(wanted)} keys ({linked} hardlinked, {copied} copied, {copied_bytes / 1e6:.1f} MB)")
    if args.atomic and args.backup_dir and os.path.lexists(args.backup_dir):
        print(f"previous CDN tree retained at {args.backup_dir}")
    print(f"  {skipped_not_cdn} non-CDN resources, {skipped_disabled} disabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
