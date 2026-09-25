from __future__ import annotations

import asyncio
import hashlib
import stat
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from family_finance.api.app import create_app
from family_finance.api.auth import (
    SESSION_COOKIE_NAME,
    AuthenticationSetupError,
    AuthService,
    BootstrapAccount,
)
from family_finance.config import Settings
from family_finance.persistence.db import Database
from family_finance.persistence.models import ActorAuditEventRow, ApiSessionRow, ApiUserRow


class ApiTestClient:
    """Synchronous test facade over HTTPX's supported ASGI transport."""

    def __init__(self, app, *, base_url: str) -> None:
        self.app = app
        self.base_url = base_url

    def __enter__(self):
        self.loop = asyncio.new_event_loop()
        self.lifespan = self.app.router.lifespan_context(self.app)
        self.loop.run_until_complete(self.lifespan.__aenter__())
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url=self.base_url
        )
        self.loop.run_until_complete(self.client.__aenter__())
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.loop.run_until_complete(self.client.__aexit__(exc_type, exc_value, traceback))
        self.loop.run_until_complete(self.lifespan.__aexit__(exc_type, exc_value, traceback))
        self.loop.close()

    def _request(self, method: str, url: str, **kwargs: Any):
        return self.loop.run_until_complete(getattr(self.client, method)(url, **kwargs))

    def get(self, url: str, **kwargs: Any):
        return self._request("get", url, **kwargs)

    def post(self, url: str, **kwargs: Any):
        return self._request("post", url, **kwargs)

    def delete(self, url: str, **kwargs: Any):
        return self._request("delete", url, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self.client, name)


def make_api(tmp_path, *, maximum_bytes=1024):
    settings = Settings(
        data_root=tmp_path,
        api_session_hours=1,
        api_max_request_bytes=maximum_bytes,
        api_public_origin="https://testserver",
        api_trusted_hosts=("testserver",),
    )
    database = Database(settings.database_path)
    auth = AuthService(database, settings)
    auth.bootstrap_accounts(
        [
            BootstrapAccount("sam", "Sam Household", "Long-test-password-One!"),
            BootstrapAccount("lee", "Lee Household", "Long-test-password-Two!"),
        ]
    )
    assert stat.S_IMODE((tmp_path / "api-secret.key").stat().st_mode) == 0o600
    return settings, database, auth, create_app(settings=settings, database=database)


def test_two_account_bootstrap_login_csrf_revocation_and_safe_headers(tmp_path):
    _, database, auth, app = make_api(tmp_path)
    with pytest.raises(AuthenticationSetupError, match="already bootstrapped"):
        auth.bootstrap_accounts(
            [
                BootstrapAccount("extra-one", "Extra One", "Another-long-password-One!"),
                BootstrapAccount("extra-two", "Extra Two", "Another-long-password-Two!"),
            ]
        )
    with ApiTestClient(app, base_url="https://testserver") as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["data"] == {"status": "ok"}
        assert health.headers["cache-control"] == "private, no-store"
        assert health.headers["x-request-id"]

        missing_session = client.get("/api/v1/auth/session")
        assert missing_session.status_code == 401
        assert missing_session.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
        assert client.get("/api/v1/planning/scenarios").status_code == 401
        assert client.get("/api/v1/automation/runs").status_code == 401

        wrong_origin = client.post(
            "/api/v1/auth/session",
            json={"username": "sam", "password": "Long-test-password-One!"},
            headers={"Origin": "https://attacker.example"},
        )
        assert wrong_origin.status_code == 403
        assert wrong_origin.json()["error"]["code"] == "ORIGIN_REJECTED"

        invalid = client.post(
            "/api/v1/auth/session",
            json={"username": "sam", "password": "wrong"},
            headers={"Origin": "https://testserver"},
        )
        assert invalid.status_code == 401
        assert "wrong" not in invalid.text
        assert invalid.headers["x-request-id"] == invalid.json()["error"]["request_id"]
        assert invalid.headers["cache-control"] == "private, no-store"

        signed_in = client.post(
            "/api/v1/auth/session",
            json={"username": "sam", "password": "Long-test-password-One!"},
            headers={"Origin": "https://testserver"},
        )
        assert signed_in.status_code == 200
        data = signed_in.json()["data"]
        csrf_token = data["csrf_token"]
        assert data["user"]["username"] == "sam"
        cookie_header = signed_in.headers["set-cookie"].lower()
        assert "secure" in cookie_header
        assert "httponly" in cookie_header
        assert "samesite=strict" in cookie_header
        assert "path=/api/v1" in cookie_header
        assert SESSION_COOKIE_NAME in cookie_header
        assert client.cookies.get(SESSION_COOKIE_NAME)

        bootstrapped = client.get("/api/v1/auth/session")
        assert bootstrapped.status_code == 200
        assert bootstrapped.json()["data"]["csrf_token"] == csrf_token

        csrf_missing = client.delete(
            "/api/v1/auth/session", headers={"Origin": "https://testserver"}
        )
        assert csrf_missing.status_code == 403
        assert csrf_missing.json()["error"]["code"] == "CSRF_REJECTED"
        assert client.get("/api/v1/auth/session").status_code == 200

        signed_out = client.delete(
            "/api/v1/auth/session",
            headers={"Origin": "https://testserver", "X-CSRF-Token": csrf_token},
        )
        assert signed_out.status_code == 204
        assert client.get("/api/v1/auth/session").status_code == 401

    with database.session() as session:
        users = session.execute(select(ApiUserRow)).scalars().all()
        assert len(users) == 2
        assert {user.username for user in users} == {"sam", "lee"}
        assert all(user.enabled for user in users)
        events = session.execute(select(ActorAuditEventRow)).scalars().all()
        assert {event.event_type for event in events} >= {
            "auth.bootstrap",
            "auth.sign_in",
            "auth.sign_out",
        }
        assert all(not hasattr(event, "username") for event in events)
        assert session.execute(text("SELECT COUNT(*) FROM api_sessions WHERE revoked_at IS NULL")).scalar_one() == 0

    with pytest.raises(IntegrityError), database.write_session() as session:
        session.execute(text("UPDATE actor_audit_events SET outcome='tampered'"))


def test_login_throttle_host_rejection_request_limit_and_host_password_recovery(tmp_path):
    _, database, auth, app = make_api(tmp_path, maximum_bytes=1024)
    with ApiTestClient(app, base_url="https://testserver") as client:
        bad_host = client.get("/api/v1/health", headers={"Host": "evil.example"})
        assert bad_host.status_code == 400
        assert bad_host.json()["error"]["code"] == "HOST_NOT_ALLOWED"

        too_large = client.post(
            "/api/v1/auth/session",
            content=b"x" * 2048,
            headers={"Origin": "https://testserver", "Content-Type": "application/json"},
        )
        assert too_large.status_code == 413
        assert too_large.json()["error"]["code"] == "REQUEST_TOO_LARGE"

        for _ in range(5):
            response = client.post(
                "/api/v1/auth/session",
                json={"username": "sam", "password": "incorrect-password"},
                headers={"Origin": "https://testserver"},
            )
            assert response.status_code == 401
        throttled = client.post(
            "/api/v1/auth/session",
            json={"username": "sam", "password": "Long-test-password-One!"},
            headers={"Origin": "https://testserver"},
        )
        assert throttled.status_code == 429
        assert throttled.headers["retry-after"] == "900"

        # A different client key is not blocked and creates a revocable session.
        credentials = auth.login(
            username="sam",
            password="Long-test-password-One!",
            client_key="recovery-test-client",
            request_id="test-request",
        )
        assert auth.authenticate(credentials.token) is not None
        auth.reset_password(username="sam", password="Replacement-password-One!")
        assert auth.authenticate(credentials.token) is None
        replacement = auth.login(
            username="sam",
            password="Replacement-password-One!",
            client_key="recovery-test-client",
            request_id="test-request-2",
        )
        assert auth.authenticate(replacement.token) is not None
        with database.write_session() as session:
            session.execute(
                update(ApiSessionRow)
                .where(
                    ApiSessionRow.token_hash
                    == hashlib.sha256(replacement.token.encode("ascii")).hexdigest()
                )
                .values(expires_at="2000-01-01T00:00:00+00:00")
            )
        assert auth.authenticate(replacement.token) is None
