#!/usr/bin/env python3
"""Focused tests for password hashes, manual user storage, and server-side sessions."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth import (AuthStore, LoginRateLimiter, hash_password, load_jwt_secret, normalize_username,
                  verify_password)


class AuthTests(unittest.TestCase):
    def test_password_hash_is_salted_and_verifies(self):
        first = hash_password("correct horse battery staple")
        second = hash_password("correct horse battery staple")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("correct horse battery staple", first))
        self.assertFalse(verify_password("wrong password", first))
        self.assertFalse(verify_password("correct horse battery staple", "plain-text"))

    def test_password_minimum(self):
        with self.assertRaises(ValueError):
            hash_password("short")

    def test_manual_user_auth_and_hashed_session_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private" / "auth.sqlite3"
            path.parent.mkdir(mode=0o700)
            secret_path = path.parent / "jwt-secret"
            secret_path.write_bytes(os.urandom(32))
            os.chmod(secret_path, 0o600)
            secret = load_jwt_secret(secret_path)
            store = AuthStore(path, jwt_secret=secret, session_ttl=60)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "INSERT INTO users(username,password_hash,created_at) VALUES(?,?,?)",
                    ("balance-user", hash_password("correct horse battery staple"), 1),
                )
            self.assertEqual(store.authenticate(" BALANCE-USER ", "correct horse battery staple"),
                             "balance-user")
            self.assertIsNone(store.authenticate("missing", "correct horse battery staple"))
            now = int(time.time())
            token, expiry = store.create_session("balance-user", now=now)
            self.assertEqual(len(token.split(".")), 3)
            self.assertEqual(expiry, now + 60)
            self.assertEqual(store.resolve_session(token, now=now + 59), "balance-user")
            self.assertIsNone(store.resolve_session(token, now=now + 60))
            self.assertIsNone(store.resolve_session(token[:-1] + ("A" if token[-1] != "A" else "B"),
                                                    now=now + 1))
            with sqlite3.connect(path) as connection:
                stored = connection.execute("SELECT token_hash FROM sessions").fetchall()
            self.assertEqual(len(stored), 1)  # expired JWT is denied; the next issuance prunes its row
            token, _ = store.create_session("balance-user", now=now + 61)
            import base64
            claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
            expected = hashlib.sha256(claims["jti"].encode("ascii")).hexdigest()
            with sqlite3.connect(path) as connection:
                stored = connection.execute("SELECT token_hash FROM sessions").fetchone()[0]
            self.assertEqual(stored, expected)
            self.assertNotEqual(stored, token)
            store.revoke_session(token, now=now + 62)
            self.assertIsNone(store.resolve_session(token, now=now + 62))

    def test_jwt_requires_private_256_bit_secret_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jwt-secret"
            path.write_bytes(os.urandom(31))
            os.chmod(path, 0o600)
            with self.assertRaisesRegex(ValueError, "at least 32 bytes"):
                load_jwt_secret(path)
            path.write_bytes(os.urandom(32))
            os.chmod(path, 0o644)
            with self.assertRaisesRegex(PermissionError, "mode 0600"):
                load_jwt_secret(path)

    def test_insecure_existing_database_parent_is_rejected_without_chmod(self):
        with tempfile.TemporaryDirectory() as directory:
            shared = Path(directory) / "shared"
            shared.mkdir(mode=0o755)
            os.chmod(shared, 0o755)
            database = shared / "auth.sqlite3"
            with self.assertRaisesRegex(PermissionError, "mode 0700"):
                AuthStore(database, jwt_secret=os.urandom(32))
            self.assertEqual(shared.stat().st_mode & 0o777, 0o755)
            self.assertFalse(database.exists())

    def test_rate_limiter_blocks_then_expires(self):
        limiter = LoginRateLimiter(window_seconds=10, max_failures=2)
        limiter.record_failure("127.0.0.1", "user", now=100)
        self.assertEqual(limiter.blocked_for("127.0.0.1", "user", now=101), 0)
        limiter.record_failure("127.0.0.1", "user", now=102)
        self.assertGreater(limiter.blocked_for("127.0.0.1", "user", now=103), 0)
        self.assertEqual(limiter.blocked_for("127.0.0.1", "user", now=111), 0)

    def test_account_throttle_does_not_lock_out_other_source_ip(self):
        limiter = LoginRateLimiter(window_seconds=10, max_failures=2)
        limiter.record_failure("198.51.100.10", "known-owner", now=100)
        limiter.record_failure("198.51.100.10", "known-owner", now=101)
        self.assertGreater(limiter.blocked_for("198.51.100.10", "known-owner", now=102), 0)
        self.assertEqual(limiter.blocked_for("198.51.100.11", "known-owner", now=102), 0)

    def test_account_throttle_caps_distributed_guessing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private" / "auth.sqlite3"
            store = AuthStore(path, jwt_secret=os.urandom(32))
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "INSERT INTO users(username,password_hash,created_at) VALUES(?,?,?)",
                    ("known-owner", hash_password("correct horse battery staple"), 1),
                )
            ip_limiter = LoginRateLimiter(window_seconds=900)
            for index in range(8):
                ip = f"198.51.100.{10 + index}"
                self.assertEqual(store.account_retry_after("Known-Owner", now=100 + index), 0)
                self.assertEqual(ip_limiter.blocked_for(ip, "known-owner", now=100 + index), 0)
                ip_limiter.record_failure(ip, "known-owner", now=100 + index)
                store.record_account_failure("Known-Owner", now=100 + index)
            self.assertGreater(store.account_retry_after("known-owner", now=108), 0)
            self.assertEqual(store.account_retry_after("another-user", now=108), 0)
            blocked_row_count = 8
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM login_failures").fetchone()[0],
                                 blocked_row_count)
            ip_limiter.clear("198.51.100.10", "known-owner")
            self.assertGreater(store.account_retry_after("known-owner", now=108), 0)

            # Reopening the existing panel DB and churning process-local IP buckets cannot erase
            # the cross-IP account history; only rows older than the rolling window expire.
            restarted = AuthStore(path, jwt_secret=os.urandom(32))
            self.assertGreater(restarted.account_retry_after("KNOWN-OWNER", now=108), 0)
            self.assertEqual(restarted.account_retry_after("known-owner", now=107 + 900), 0)
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM login_failures").fetchone()[0], 0)

            for index in range(100):
                restarted.record_account_failure(f"unknown-user-{index}", now=2000 + index)
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM login_failures").fetchone()[0], 0)

    def test_username_normalization(self):
        self.assertEqual(normalize_username("  Ａlice "), "alice")


if __name__ == "__main__":
    unittest.main()
