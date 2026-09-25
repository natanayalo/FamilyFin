"""Local household authentication with server-side, revocable sessions."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import stat
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select, update

from family_finance.config import Settings
from family_finance.persistence.db import Database, utc_now
from family_finance.persistence.models import (
    ActorAuditEventRow,
    ApiLoginThrottleRow,
    ApiSessionRow,
    ApiUserRow,
)

SESSION_COOKIE_NAME = "familyfin_session"
LOGIN_FAILURE_LIMIT = 5
LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_BLOCK = timedelta(minutes=15)
PASSWORD_MIN_LENGTH = 14
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,63}$")
_SESSION_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{40,64}$")
_CSRF_TOKEN_RE = re.compile(r"^[a-f0-9]{64}$")
_DUMMY_SALT = bytes.fromhex("a87a498f1a0a750396c7800fcf6a61dd")
_DUMMY_HASH = hashlib.scrypt(
    b"not-a-real-password", salt=_DUMMY_SALT, n=2**15, r=8, p=1, maxmem=64 * 1024 * 1024
)


class AuthenticationError(ValueError):
    """Generic invalid-credentials/session error safe for HTTP mapping."""


class LoginRateLimitedError(ValueError):
    """Login attempts are temporarily blocked for this account and client."""


class AuthenticationSetupError(RuntimeError):
    """The local credential bootstrap state is invalid or incomplete."""


@dataclass(frozen=True)
class BootstrapAccount:
    username: str
    display_name: str
    password: str


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    username: str
    display_name: str


@dataclass(frozen=True)
class SessionCredentials:
    token: str
    csrf_token: str
    expires_at: str
    user: AuthenticatedUser


def _now() -> datetime:
    return datetime.now(UTC)


def _password_hash(password: str, salt: bytes | None = None) -> tuple[str, str]:
    _validate_password(password)
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**15, r=8, p=1, maxmem=64 * 1024 * 1024
    )
    return salt.hex(), digest.hex()


def _validate_password(password: str) -> None:
    if not isinstance(password, str) or not PASSWORD_MIN_LENGTH <= len(password) <= 1024:
        raise ValueError(f"Password must contain {PASSWORD_MIN_LENGTH} to 1024 characters")
    if "\x00" in password:
        raise ValueError("Password contains an unsupported character")


def _matches_password(password: str, salt_hex: str, expected_hex: str) -> bool:
    try:
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=2**15,
            r=8,
            p=1,
            maxmem=64 * 1024 * 1024,
        ).hex()
    except (ValueError, UnicodeEncodeError):
        candidate = "0" * len(expected_hex)
    return hmac.compare_digest(candidate, expected_hex)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class AuthService:
    """Authentication service; passwords and raw bearer tokens never reach logs."""

    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings
        self._throttle_secret = self._load_or_create_secret(settings.data_root / "api-secret.key")

    @staticmethod
    def _load_or_create_secret(path: Path) -> bytes:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            descriptor = None
        if descriptor is not None:
            try:
                secret = secrets.token_bytes(32)
                os.write(descriptor, secret)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode) or stat.S_IMODE(file_stat.st_mode) & 0o077:
                raise AuthenticationSetupError("API secret file must be a private regular file (mode 0600)")
            secret = os.read(descriptor, 128)
        finally:
            os.close(descriptor)
        if len(secret) != 32:
            raise AuthenticationSetupError("API secret file has an invalid length")
        return secret

    def _throttle_key(self, username: str, client_key: str) -> str:
        value = f"{username.casefold()}\0{client_key}".encode()
        return hmac.new(self._throttle_secret, value, hashlib.sha256).hexdigest()

    @staticmethod
    def _audit(
        session,
        *,
        actor_id: str | None,
        event_type: str,
        request_id: str,
        target_type: str | None,
        outcome: str,
    ) -> None:
        session.add(
            ActorAuditEventRow(
                id=str(uuid.uuid4()),
                actor_id=actor_id,
                event_type=event_type,
                request_id=request_id,
                target_type=target_type,
                outcome=outcome,
                created_at=utc_now(),
            )
        )

    def bootstrap_accounts(self, accounts: Sequence[BootstrapAccount]) -> None:
        """Create the required two accounts once, from a local host command."""

        if len(accounts) != 2:
            raise ValueError("Exactly two household accounts must be configured")
        normalized = []
        for account in accounts:
            username = account.username.strip().casefold()
            display_name = account.display_name.strip()
            if not _USERNAME_RE.fullmatch(username) or not display_name or len(display_name) > 100:
                raise ValueError("Each account needs a valid username and display name")
            salt, digest = _password_hash(account.password)
            normalized.append((username, display_name, salt, digest))
        if len({item[0] for item in normalized}) != 2:
            raise ValueError("Household usernames must be different")

        with self.database.write_session() as session:
            if session.execute(select(ApiUserRow.user_id).limit(1)).first() is not None:
                raise AuthenticationSetupError("Accounts are already bootstrapped")
            now = utc_now()
            for username, display_name, salt, digest in normalized:
                session.add(
                    ApiUserRow(
                        user_id=str(uuid.uuid4()),
                        username=username,
                        display_name=display_name,
                        password_salt=salt,
                        password_hash=digest,
                        enabled=True,
                        created_at=now,
                        updated_at=now,
                    )
                )
            self._audit(
                session,
                actor_id=None,
                event_type="auth.bootstrap",
                request_id="local-bootstrap",
                target_type="household_accounts",
                outcome="success",
            )

    def account_count(self) -> int:
        with self.database.session() as session:
            return len(session.execute(select(ApiUserRow.user_id)).all())

    def login(
        self,
        *,
        username: str,
        password: str,
        client_key: str,
        request_id: str,
    ) -> SessionCredentials:
        normalized_username = username.strip().casefold()
        throttle_key = self._throttle_key(normalized_username, client_key)
        now = _now()
        now_text = now.isoformat()
        token = secrets.token_urlsafe(32)
        csrf_token = self._csrf_for_token(token)
        failure: Exception | None = None
        credentials: SessionCredentials | None = None

        with self.database.write_session() as session:
            throttle_retention = (now - timedelta(days=1)).isoformat()
            session.execute(
                delete(ApiLoginThrottleRow).where(ApiLoginThrottleRow.updated_at < throttle_retention)
            )
            throttle = session.get(ApiLoginThrottleRow, throttle_key)
            if throttle and throttle.blocked_until and throttle.blocked_until > now_text:
                self._audit(
                    session,
                    actor_id=None,
                    event_type="auth.sign_in",
                    request_id=request_id,
                    target_type=None,
                    outcome="throttled",
                )
                failure = LoginRateLimitedError("Sign-in temporarily unavailable")
            else:
                user = session.execute(
                    select(ApiUserRow).where(ApiUserRow.username == normalized_username)
                ).scalar_one_or_none()
                valid = False
                if user is not None and user.enabled:
                    valid = _matches_password(password, user.password_salt, user.password_hash)
                else:
                    _matches_password(password, _DUMMY_SALT.hex(), _DUMMY_HASH.hex())

                if not valid:
                    if throttle is None:
                        throttle = ApiLoginThrottleRow(
                            throttle_key_hash=throttle_key,
                            failure_count=0,
                            window_started_at=now_text,
                            blocked_until=None,
                            updated_at=now_text,
                        )
                        session.add(throttle)
                    elif now - datetime.fromisoformat(throttle.window_started_at) > LOGIN_WINDOW:
                        throttle.failure_count = 0
                        throttle.window_started_at = now_text
                        throttle.blocked_until = None
                    throttle.failure_count += 1
                    if throttle.failure_count >= LOGIN_FAILURE_LIMIT:
                        throttle.blocked_until = (now + LOGIN_BLOCK).isoformat()
                    throttle.updated_at = now_text
                    self._audit(
                        session,
                        actor_id=None,
                        event_type="auth.sign_in",
                        request_id=request_id,
                        target_type=None,
                        outcome="failure",
                    )
                    failure = AuthenticationError("Invalid username or password")

            if failure is None:
                assert user is not None
                if throttle is not None:
                    session.delete(throttle)
                expires_at = (now + timedelta(hours=self.settings.api_session_hours)).isoformat()
                session.add(
                    ApiSessionRow(
                        token_hash=_token_hash(token),
                        user_id=user.user_id,
                        csrf_hash=_token_hash(csrf_token),
                        created_at=now_text,
                        expires_at=expires_at,
                        revoked_at=None,
                    )
                )
                self._audit(
                    session,
                    actor_id=user.user_id,
                    event_type="auth.sign_in",
                    request_id=request_id,
                    target_type=None,
                    outcome="success",
                )
                auth_user = AuthenticatedUser(user.user_id, user.username, user.display_name)
                credentials = SessionCredentials(token, csrf_token, expires_at, auth_user)
        if failure is not None:
            raise failure
        assert credentials is not None
        return credentials

    def authenticate(self, token: str | None) -> tuple[AuthenticatedUser, str] | None:
        if not token or not _SESSION_TOKEN_RE.fullmatch(token):
            return None
        with self.database.session() as session:
            row = session.execute(
                select(ApiSessionRow, ApiUserRow)
                .join(ApiUserRow, ApiUserRow.user_id == ApiSessionRow.user_id)
                .where(ApiSessionRow.token_hash == _token_hash(token))
            ).first()
            if row is None:
                return None
            api_session, user = row
            if api_session.revoked_at is not None or api_session.expires_at <= _now().isoformat() or not user.enabled:
                return None
            csrf_token = self._csrf_for_token(token)
            if not hmac.compare_digest(api_session.csrf_hash, _token_hash(csrf_token)):
                return None
            return (
                AuthenticatedUser(user.user_id, user.username, user.display_name),
                csrf_token,
            )

    def _csrf_for_token(self, token: str) -> str:
        return hmac.new(
            self._throttle_secret, f"csrf\0{token}".encode("ascii"), hashlib.sha256
        ).hexdigest()

    @staticmethod
    def verify_csrf(expected_token: str, token: str | None) -> bool:
        if not token or not _CSRF_TOKEN_RE.fullmatch(token):
            return False
        return hmac.compare_digest(expected_token, token)

    def logout(self, *, token: str, actor_id: str, request_id: str) -> None:
        token_hash = _token_hash(token)
        now = utc_now()
        with self.database.write_session() as session:
            session.execute(
                update(ApiSessionRow)
                .where(ApiSessionRow.token_hash == token_hash, ApiSessionRow.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            self._audit(
                session,
                actor_id=actor_id,
                event_type="auth.sign_out",
                request_id=request_id,
                target_type=None,
                outcome="success",
            )

    def reset_password(self, *, username: str, password: str) -> None:
        """Host-operator recovery path; rotating a password revokes all sessions."""

        salt, digest = _password_hash(password)
        with self.database.write_session() as session:
            user = session.execute(
                select(ApiUserRow).where(ApiUserRow.username == username.strip().casefold())
            ).scalar_one_or_none()
            if user is None:
                raise ValueError("Household account was not found")
            now = utc_now()
            user.password_salt = salt
            user.password_hash = digest
            user.updated_at = now
            session.execute(
                update(ApiSessionRow)
                .where(ApiSessionRow.user_id == user.user_id, ApiSessionRow.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            self._audit(
                session,
                actor_id=None,
                event_type="auth.credential_recovered",
                request_id=str(uuid.uuid4()),
                target_type="credential",
                outcome="success",
            )
