#!/usr/bin/env python3
"""Print a PBKDF2 hash for manual insertion into the balance users table."""

from __future__ import annotations

import getpass

from auth import hash_password


def main() -> int:
    first = getpass.getpass("New balance password (12+ UTF-8 bytes): ")
    second = getpass.getpass("Repeat password: ")
    if first != second:
        print("Passwords do not match.")
        return 1
    try:
        encoded = hash_password(first)
    except (TypeError, ValueError) as error:
        print(error)
        return 1
    print("Password hash (store this hash, never the password):")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
