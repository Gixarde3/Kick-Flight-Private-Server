#!/usr/bin/env python3
"""Focused tests for password hashes, manual user storage, and server-side sessions."""

from __future__ import annotations

import hashlib
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth import AuthStore, LoginRateLimiter, hash_password, normalize_username, verify_password


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
            store = AuthStore(path, session_ttl=60)
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
            token, expiry = store.create_session("balance-user", now=100)
            self.assertEqual(expiry, 160)
            self.assertEqual(store.resolve_session(token, now=159), "balance-user")
            self.assertIsNone(store.resolve_session(token, now=160))
            with sqlite3.connect(path) as connection:
                stored = connection.execute("SELECT token_hash FROM sessions").fetchall()
            self.assertEqual(stored, [])
            token, _ = store.create_session("balance-user", now=200)
            expected = hashlib.sha256(token.encode("ascii")).hexdigest()
            with sqlite3.connect(path) as connection:
                stored = connection.execute("SELECT token_hash FROM sessions").fetchone()[0]
            self.assertEqual(stored, expected)
            self.assertNotEqual(stored, token)
            store.revoke_session(token)
            self.assertIsNone(store.resolve_session(token, now=201))

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

    def test_username_normalization(self):
        self.assertEqual(normalize_username("  Ａlice "), "alice")


if __name__ == "__main__":
    unittest.main()
