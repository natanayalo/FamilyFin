from __future__ import annotations

import asyncio
import hashlib
import stat
from typing import Annotated, Any

import httpx
import pytest
from fastapi import FastAPI, File, Form, UploadFile
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from family_finance.api.app import (
    MULTIPART_OVERHEAD_BYTES,
    RequestSizeLimitMiddleware,
    create_app,
    request_body_limit,
)
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

    def put(self, url: str, **kwargs: Any):
        return self._request("put", url, **kwargs)

    def delete(self, url: str, **kwargs: Any):
        return self._request("delete", url, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self.client, name)


def make_api(tmp_path, *, maximum_bytes=1024, maximum_compressed_bytes=25 * 1024 * 1024):
    settings = Settings(
        data_root=tmp_path,
        max_compressed_bytes=maximum_compressed_bytes,
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
    _, database, auth, app = make_api(
        tmp_path, maximum_bytes=1024, maximum_compressed_bytes=1024
    )
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

        # The FamilyBiz route gets its parser limit plus bounded multipart
        # overhead; the identical path still has a small limit for JSON.
        familybiz_with_overhead = client.post(
            "/api/v1/imports/familybiz/previews",
            content=b"x" * (1024 + MULTIPART_OVERHEAD_BYTES),
            headers={
                "Origin": "https://testserver",
                "Content-Type": "multipart/form-data; boundary=test",
            },
        )
        assert familybiz_with_overhead.status_code == 401
        familybiz_over_limit = client.post(
            "/api/v1/imports/familybiz/previews",
            content=b"x" * (1025 + MULTIPART_OVERHEAD_BYTES),
            headers={
                "Origin": "https://testserver",
                "Content-Type": "multipart/form-data; boundary=test",
            },
        )
        assert familybiz_over_limit.status_code == 413

        familybiz_json = client.post(
            "/api/v1/imports/familybiz/previews",
            content=b"x" * 1025,
            headers={"Origin": "https://testserver", "Content-Type": "application/json"},
        )
        assert familybiz_json.status_code == 413

        for index in range(5):
            response = client.post(
                "/api/v1/auth/session",
                json={"username": "sam", "password": "incorrect-password"},
                headers={
                    "Origin": "https://testserver",
                    "X-Forwarded-For": f"198.51.100.{index + 1}",
                },
            )
            assert response.status_code == 401
        throttled = client.post(
            "/api/v1/auth/session",
            json={"username": "sam", "password": "Long-test-password-One!"},
            headers={
                "Origin": "https://testserver",
                "X-Forwarded-For": "203.0.113.99",
            },
        )
        assert throttled.status_code == 429
        assert throttled.headers["retry-after"] == "900"

        # This test client has one direct peer identity for both accounts;
        # X-Forwarded-For does not create a new rate-limit bucket.
        other_account = client.post(
            "/api/v1/auth/session",
            json={"username": "lee", "password": "Long-test-password-Two!"},
            headers={"Origin": "https://testserver", "X-Forwarded-For": "192.0.2.88"},
        )
        assert other_account.status_code == 200

        # Exercise host-side password recovery and session revocation through
        # the service boundary, independently of the proxy's shared peer key.
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


def test_upload_limit_tracks_parser_limits_and_keeps_json_limit_small(tmp_path):
    settings = Settings(data_root=tmp_path, max_compressed_bytes=25 * 1024 * 1024)
    familybiz = request_body_limit(
        "POST",
        "/api/v1/imports/familybiz/previews",
        "multipart/form-data; boundary=body",
        settings,
    )
    assert familybiz == 25 * 1024 * 1024 + MULTIPART_OVERHEAD_BYTES
    assert request_body_limit(
        "POST",
        "/api/v1/imports/familybiz/commits",
        "multipart/form-data",
        settings,
    ) == familybiz
    assert request_body_limit(
        "POST", "/api/v1/imports/familybiz/previews", "application/json", settings
    ) == 1024 * 1024
    assert request_body_limit(
        "POST", "/api/v1/unknown/upload", "multipart/form-data", settings
    ) == 1024 * 1024
    assert request_body_limit(
        "POST", "/api/v1/planning/seeds/csv/previews", "multipart/form-data", settings
    ) == settings.planning_csv_max_bytes + MULTIPART_OVERHEAD_BYTES


def test_route_aware_body_limit_catches_chunked_upload_overflow(tmp_path):
    settings = Settings(data_root=tmp_path, max_compressed_bytes=1024)
    body_chunks = [b"x" * (1024 * 1024), b"x" * 1025]
    response_starts = []
    reached_endpoint = False

    async def receive():
        body = body_chunks.pop(0)
        return {
            "type": "http.request",
            "body": body,
            "more_body": bool(body_chunks),
        }

    async def send(message):
        if message["type"] == "http.response.start":
            response_starts.append(message)

    async def endpoint(_scope, _receive, _send):
        nonlocal reached_endpoint
        reached_endpoint = True

    middleware = RequestSizeLimitMiddleware(endpoint, settings=settings)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/imports/familybiz/previews",
        "headers": [(b"content-type", b"multipart/form-data; boundary=test")],
        "state": {"request_id": "test-request-id"},
    }
    asyncio.run(middleware(scope, receive, send))
    assert response_starts[0]["status"] == 413
    assert reached_endpoint is False


def test_fastapi_parses_bounded_synthetic_multipart_request(tmp_path):
    settings = Settings(
        data_root=tmp_path,
        max_compressed_bytes=2048,
        api_max_request_bytes=1024,
    )
    app = FastAPI()
    app.add_middleware(RequestSizeLimitMiddleware, settings=settings)
    reached_endpoint = []

    @app.post("/api/v1/imports/familybiz/previews")
    async def synthetic_preview(
        file: Annotated[UploadFile, File()],
        note: Annotated[str, Form()],
    ):
        content = await file.read()
        reached_endpoint.append(True)
        return {"filename": file.filename, "note": note, "size": len(content)}

    with ApiTestClient(app, base_url="http://testserver") as client:
        accepted = client.post(
            "/api/v1/imports/familybiz/previews",
            files={"file": ("sample.csv", b"a" * 2048, "text/csv")},
            data={"note": "synthetic"},
        )
        assert accepted.status_code == 200
        assert accepted.json() == {
            "filename": "sample.csv",
            "note": "synthetic",
            "size": 2048,
        }

        oversized = client.post(
            "/api/v1/imports/familybiz/previews",
            files={
                "file": (
                    "large.csv",
                    b"a" * (settings.max_compressed_bytes + 1_048_577),
                    "text/csv",
                )
            },
            data={"note": "synthetic"},
        )
        assert oversized.status_code == 413
        assert len(reached_endpoint) == 1
