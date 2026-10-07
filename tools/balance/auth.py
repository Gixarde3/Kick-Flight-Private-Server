"""SQLite-backed login and server-side sessions for the balance WebUI.

No account is created automatically. Operators insert accounts manually after generating a
PBKDF2 password hash with ``password_hash.py``.
"""

from __future__ import annotations

import hashlib
import base64
import hmac
import json
import os
import re
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
ACCOUNT_LOGIN_MAX_FAILURES = 8
LOGIN_BUCKET_LIMIT = 4096
JWT_HEADER = b'{"alg":"HS256","typ":"JWT"}'
JWT_MAX_BYTES = 2048


def load_jwt_secret(path: str | Path) -> bytes:
    """Read an operator-generated signing secret without ever logging its contents."""
    secret_path = Path(path).expanduser().resolve()
    info = secret_path.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise PermissionError(
            f"JWT secret {secret_path} must be a regular file owned by the service user with mode 0600"
        )
    secret = secret_path.read_bytes()
    if len(secret) < 32:
        raise ValueError(f"JWT secret {secret_path} must contain at least 32 bytes")
    return secret


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64url(value: str) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("invalid base64url")
    decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if _b64url(decoded) != value:
        raise ValueError("non-canonical base64url")
    return decoded


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
    """Bounded per-IP and per-IP/account throttling for one service process."""

    def __init__(self, *, window_seconds: int = LOGIN_WINDOW_SECONDS, max_failures: int = LOGIN_MAX_FAILURES,
                 bucket_limit: int = LOGIN_BUCKET_LIMIT):
        self.window_seconds = window_seconds
        self.max_failures = max_failures
        self.bucket_limit = bucket_limit
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _keys(self, ip_address: str, username: str) -> tuple[str, str]:
        # Persistent cross-IP account throttling is stored by AuthStore; these bounded buckets
        # constrain one source without letting it spray many usernames.
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
            # Successful login clears only this IP/account pair. Keep the account-wide rolling
            # history so guesses from other sources cannot be erased by a concurrent real login.
            self._failures.pop("pair:" + ip_address + "\0" + username, None)


class AuthStore:
    """Users and revocable JWT sessions in a local SQLite database."""

    def __init__(self, path: str | Path, *, jwt_secret: bytes, session_ttl: int = SESSION_TTL_SECONDS):
        self.path = Path(path).expanduser().resolve()
        if not isinstance(jwt_secret, bytes) or len(jwt_secret) < 32:
            raise ValueError("JWT signing secret must contain at least 32 bytes")
        self.jwt_secret = jwt_secret
        self.session_ttl = session_ttl
        parent_created = False
        try:
            self.path.parent.mkdir(parents=True, mode=0o700)
            parent_created = True
        except FileExistsError:
            pass
        if parent_created:
            # It is safe to tighten permissions on a directory this service just created.
            os.chmod(self.path.parent, 0o700)
        parent_stat = self.path.parent.stat()
        if (not stat.S_ISDIR(parent_stat.st_mode) or parent_stat.st_uid != os.geteuid()
                or stat.S_IMODE(parent_stat.st_mode) != 0o700):
            raise PermissionError(
                f"authentication database directory {self.path.parent} must be owned by the service user "
                "and have mode 0700; choose a dedicated private directory"
            )
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
                    CREATE TABLE IF NOT EXISTS login_failures (
                        attempt_id TEXT PRIMARY KEY,
                        account_hash TEXT NOT NULL,
                        failed_at INTEGER NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS login_failures_account_time
                        ON login_failures(account_hash, failed_at);
                """)
        os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)

    @staticmethod
    def _account_hash(username: str) -> str:
        normalized = normalize_username(username)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def account_retry_after(self, username: str, *, now: int | None = None,
                            window_seconds: int = LOGIN_WINDOW_SECONDS,
                            max_failures: int = 8) -> int:
        """Return a rolling account cooldown shared across IPs and service restarts."""
        now = int(time.time()) if now is None else int(now)
        account_hash = self._account_hash(username)
        cutoff = now - window_seconds
        with closing(self._connect()) as connection:
            with connection:
                exists = connection.execute(
                    "SELECT 1 FROM users WHERE username = ?", (normalize_username(username),)
                ).fetchone()
                if exists is None:
                    return 0
                # Only expired rows are removed; active failures survive login success/restarts.
                connection.execute(
                    "DELETE FROM login_failures WHERE account_hash = ? AND failed_at <= ?",
                    (account_hash, cutoff),
                )
                row = connection.execute(
                    "SELECT COUNT(*) AS failures, MIN(failed_at) AS oldest "
                    "FROM login_failures WHERE account_hash = ? AND failed_at > ?",
                    (account_hash, cutoff),
                ).fetchone()
        if row["failures"] < max_failures:
            return 0
        return max(1, window_seconds - (now - row["oldest"]))

    def record_account_failure(self, username: str, *, now: int | None = None,
                               window_seconds: int = LOGIN_WINDOW_SECONDS,
                               max_failures: int = ACCOUNT_LOGIN_MAX_FAILURES) -> None:
        """Persist a failed attempt using a normalized-account hash, never the username/password."""
        now = int(time.time()) if now is None else int(now)
        account_hash = self._account_hash(username)
        cutoff = now - window_seconds
        with closing(self._connect()) as connection:
            with connection:
                exists = connection.execute(
                    "SELECT 1 FROM users WHERE username = ?", (normalize_username(username),)
                ).fetchone()
                if exists is None:
                    return
                connection.execute("DELETE FROM login_failures WHERE failed_at <= ?", (cutoff,))
                row = connection.execute(
                    "SELECT COUNT(*) AS failures FROM login_failures "
                    "WHERE account_hash = ? AND failed_at > ?",
                    (account_hash, cutoff),
                ).fetchone()
                if row["failures"] >= max_failures:
                    return
                connection.execute(
                    "INSERT INTO login_failures(attempt_id, account_hash, failed_at) VALUES (?, ?, ?)",
                    (secrets.token_hex(16), account_hash, now),
                )

    def authenticate(self, username: str, password: str) -> str | None:
        normalized = normalize_username(username)
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT username, password_hash FROM users WHERE username = ?", (normalized,)
            ).fetchone()
        if row is None:
            # Keep unknown-account failures comparable to wrong-password failures without accepting a dummy hash.
            self.dummy_authenticate(password)
            return None
        return row["username"] if verify_password(password, row["password_hash"]) else None

    @staticmethod
    def dummy_authenticate(password: str) -> None:
        """Spend one normal PBKDF2 verification without revealing or checking an account."""
        dummy = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), b"\x00" * 16,
                                    PASSWORD_ITERATIONS, dklen=32)
        hmac.compare_digest(dummy, b"\xff" * 32)

    def create_session(self, username: str, *, now: int | None = None) -> tuple[str, int]:
        now = int(time.time()) if now is None else now
        jti = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        expires_at = now + self.session_ttl
        header = _b64url(JWT_HEADER)
        payload = _b64url(json.dumps({
            "iss": "kickflight-balance",
            "aud": "kickflight-balance",
            "sub": normalize_username(username),
            "iat": now,
            "exp": expires_at,
            "jti": jti,
        }, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        signing_input = f"{header}.{payload}".encode("ascii")
        signature = _b64url(hmac.new(self.jwt_secret, signing_input, hashlib.sha256).digest())
        token = f"{header}.{payload}.{signature}"
        token_hash = hashlib.sha256(jti.encode("ascii")).hexdigest()
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
                connection.execute(
                    "INSERT INTO sessions(token_hash, username, created_at, expires_at) VALUES (?, ?, ?, ?)",
                    (token_hash, normalize_username(username), now, expires_at),
                )
        return token, expires_at

    def resolve_session(self, token: str | None, *, now: int | None = None) -> str | None:
        claims = self._verified_claims(token, now=now)
        if claims is None:
            return None
        now = int(time.time()) if now is None else now
        token_hash = hashlib.sha256(claims["jti"].encode("ascii")).hexdigest()
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT username, expires_at FROM sessions WHERE token_hash = ?", (token_hash,)
            ).fetchone()
            if row is None:
                return None
            if (row["expires_at"] <= now or row["expires_at"] != claims["exp"]
                    or row["username"] != claims["sub"]):
                with connection:
                    connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                return None
            return row["username"]

    def revoke_session(self, token: str | None, *, now: int | None = None) -> None:
        claims = self._verified_claims(token, now=now)
        if claims is None:
            return
        token_hash = hashlib.sha256(claims["jti"].encode("ascii")).hexdigest()
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def _verified_claims(self, token: str | None, *, now: int | None = None) -> dict | None:
        if not isinstance(token, str) or not token or len(token) > JWT_MAX_BYTES:
            return None
        try:
            header_text, payload_text, signature_text = token.split(".")
            header = json.loads(_unb64url(header_text))
            claims = json.loads(_unb64url(payload_text))
            signature = _unb64url(signature_text)
            signing_input = f"{header_text}.{payload_text}".encode("ascii")
            expected = hmac.new(self.jwt_secret, signing_input, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                return None
            if header != {"alg": "HS256", "typ": "JWT"} or not isinstance(claims, dict):
                return None
            if (claims.get("iss") != "kickflight-balance" or claims.get("aud") != "kickflight-balance"
                    or not isinstance(claims.get("sub"), str)
                    or not isinstance(claims.get("jti"), str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", claims["jti"])):
                return None
            issued, expires = claims.get("iat"), claims.get("exp")
            if type(issued) is not int or type(expires) is not int or expires - issued != self.session_ttl:
                return None
            now = int(time.time()) if now is None else now
            if issued > now + 60 or expires <= now:
                return None
            return claims
        except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            return None
