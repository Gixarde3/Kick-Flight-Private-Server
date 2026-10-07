#!/usr/bin/env python3
"""Create a private random HS256 signing secret without displaying it."""

from __future__ import annotations

import argparse
import os
import secrets
import stat
from pathlib import Path


def main() -> int:
    default = Path(__file__).resolve().parents[2] / ".local" / "balance-auth" / "jwt-secret"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=default,
                        help="destination file (default: .local/balance-auth/jwt-secret)")
    args = parser.parse_args()
    path = args.path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = path.parent.stat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid()
            or stat.S_IMODE(parent.st_mode) != 0o700):
        parser.error("destination directory must be owned by this user and have mode 0700")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        parser.error("secret already exists; refusing to replace it")
    with os.fdopen(fd, "wb") as stream:
        stream.write(secrets.token_bytes(32))
        stream.flush()
        os.fsync(stream.fileno())
    print(f"Created 256-bit JWT secret at {path} with mode 0600; contents were not displayed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
