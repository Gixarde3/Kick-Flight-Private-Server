#!/usr/bin/env python3
"""Resolve the balance service's JWT key path without sourcing its environment file."""

from __future__ import annotations

import argparse
from pathlib import Path


def environment_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in {"KF_BALANCE_AUTH_DB", "KF_BALANCE_JWT_SECRET_FILE"}:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not value:
            raise ValueError(f"{key} must not be empty")
        values[key] = value
    return values


def resolve(app_dir: Path, env_file: Path) -> Path:
    values = environment_values(env_file)
    auth_db = Path(values.get("KF_BALANCE_AUTH_DB", str(app_dir / ".local/balance-auth/auth.sqlite3")))
    secret = Path(values.get("KF_BALANCE_JWT_SECRET_FILE", str(auth_db.parent / "jwt-secret")))
    if not auth_db.is_absolute() or not secret.is_absolute():
        raise ValueError("KF_BALANCE_AUTH_DB and KF_BALANCE_JWT_SECRET_FILE must be absolute paths")
    return secret.resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app_dir", type=Path)
    parser.add_argument("env_file", type=Path)
    args = parser.parse_args()
    try:
        print(resolve(args.app_dir.resolve(), args.env_file))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
