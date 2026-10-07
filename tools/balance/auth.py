"""SQLite-backed login and server-side sessions for the balance WebUI.

No account is created automatically. Operators insert accounts manually after generating a
PBKDF2 password hash with ``password_hash.py``.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import stat
import threading
import time
import unicodedata
from contextlib import closing
from pathlib import Path

PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600_000
PASSWORD_SALT_BYTES = 16
SESSION_TOKEN_BYTES = 32
SESSION_TTL_SECONDS = 8 * 60 * 60
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 5
LOGIN_BUCKET_LIMIT = 4096


def normalize_username(username: str) -> str:
    return unicodedata.normalize("NFKC", username).strip().casefold()


def hash_password(password: str, *, salt: bytes | None = None, iterations: int = PASSWORD_ITERATIONS) -> str:
    if not isinstance(password, str):
        raise TypeError("password must be a string")
    encoded = password.encode("utf-8")
    if len(encoded) < 12:
        raise ValueError("password must contain at least 12 UTF-8 bytes")
    if len(encoded) > 1024:
        raise ValueError("password must not exceed 1024 UTF-8 bytes")
    if iterations != PASSWORD_ITERATIONS:
        raise ValueError("unsupported PBKDF2 iteration count")
    salt = secrets.token_bytes(PASSWORD_SALT_BYTES) if salt is None else salt
    if len(salt) != PASSWORD_SALT_BYTES:
        raise ValueError("salt must be 16 bytes")
    digest = hashlib.pbkdf2_hmac("sha256", encoded, salt, iterations, dklen=32)
    return f"{PASSWORD_SCHEME}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        scheme, rounds_text, salt_hex, digest_hex = encoded_hash.split("$", 3)
        if scheme != PASSWORD_SCHEME:
            return False
        rounds = int(rounds_text)
        if rounds != PASSWORD_ITERATIONS:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        if len(salt) != PASSWORD_SALT_BYTES or len(expected) != 32:
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds, dklen=32)
        return hmac.compare_digest(candidate, expected)
    except (AttributeError, TypeError, ValueError, UnicodeEncodeError):
        return False


class LoginRateLimiter:
    """Bounded in-memory IP and account throttling for a single-process service."""

    def __init__(self, *, window_seconds: int = LOGIN_WINDOW_SECONDS, max_failures: int = LOGIN_MAX_FAILURES,
                 bucket_limit: int = LOGIN_BUCKET_LIMIT):
        self.window_seconds = window_seconds
        self.max_failures = max_failures
        self.bucket_limit = bucket_limit
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _keys(ip_address: str, username: str) -> tuple[str, str]:
        # A shared account bucket lets anyone who knows a username deny service to its owner.
        # Keep the account-specific counter scoped to the source IP and retain a global IP cap.
        return ("ip:" + ip_address, "pair:" + ip_address + "\0" + username)

    def blocked_for(self, ip_address: str, username: str, *, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self._lock:
            retry_after = 0
            for key in self._keys(ip_address, username):
                attempts = [stamp for stamp in self._failures.get(key, []) if now - stamp < self.window_seconds]
                if attempts:
                    self._failures[key] = attempts
                    if len(attempts) >= self.max_failures:
                        retry_after = max(retry_after, int(self.window_seconds - (now - attempts[0])) + 1)
                else:
                    self._failures.pop(key, None)
            return max(0, retry_after)

    def record_failure(self, ip_address: str, username: str, *, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            for key in self._keys(ip_address, username):
                attempts = [stamp for stamp in self._failures.get(key, []) if now - stamp < self.window_seconds]
                attempts.append(now)
                self._failures[key] = attempts
            if len(self._failures) > self.bucket_limit:
                oldest_keys = sorted(self._failures, key=lambda key: self._failures[key][-1])
                for key in oldest_keys[: len(self._failures) - self.bucket_limit]:
                    self._failures.pop(key, None)

    def clear(self, ip_address: str, username: str) -> None:
        with self._lock:
            # Successful login resets this IP/account pair without erasing the IP-wide cap.
            self._failures.pop("pair:" + ip_address + "\0" + username, None)


class AuthStore:
    """Users and hashed opaque session tokens in a local SQLite database."""

    def __init__(self, path: str | Path, *, session_ttl: int = SESSION_TTL_SECONDS):
        self.path = Path(path).expanduser().resolve()
        self.session_ttl = session_ttl
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.executescript("""
                    CREATE TABLE IF NOT EXISTS users (
                        username TEXT PRIMARY KEY,
                        password_hash TEXT NOT NULL,
                        created_at INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS sessions (
                        token_hash TEXT PRIMARY KEY,
                        username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
                        created_at INTEGER NOT NULL,
                        expires_at INTEGER NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
                """)
        os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)

    def authenticate(self, username: str, password: str) -> str | None:
        normalized = normalize_username(username)
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT username, password_hash FROM users WHERE username = ?", (normalized,)
            ).fetchone()
        if row is None:
            # Keep unknown-account failures comparable to wrong-password failures without accepting a dummy hash.
            dummy = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), b"\x00" * 16,
                                        PASSWORD_ITERATIONS, dklen=32)
            hmac.compare_digest(dummy, b"\xff" * 32)
            return None
        return row["username"] if verify_password(password, row["password_hash"]) else None

    def create_session(self, username: str, *, now: int | None = None) -> tuple[str, int]:
        now = int(time.time()) if now is None else now
        token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        expires_at = now + self.session_ttl
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
                connection.execute(
                    "INSERT INTO sessions(token_hash, username, created_at, expires_at) VALUES (?, ?, ?, ?)",
                    (token_hash, normalize_username(username), now, expires_at),
                )
        return token, expires_at

    def resolve_session(self, token: str | None, *, now: int | None = None) -> str | None:
        if not token or len(token) > 128:
            return None
        try:
            token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        except UnicodeEncodeError:
            return None
        now = int(time.time()) if now is None else now
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT username, expires_at FROM sessions WHERE token_hash = ?", (token_hash,)
            ).fetchone()
            if row is None:
                return None
            if row["expires_at"] <= now:
                with connection:
                    connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                return None
            return row["username"]

    def revoke_session(self, token: str | None) -> None:
        if not token or len(token) > 128:
            return
        try:
            token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        except UnicodeEncodeError:
            return
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
