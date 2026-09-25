"""FastAPI lifecycle, same-origin security policy, and household session routes."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from http.cookies import CookieError, SimpleCookie
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from family_finance.api.auth import (
    SESSION_COOKIE_NAME,
    AuthenticatedUser,
    AuthenticationError,
    AuthService,
    LoginRateLimitedError,
)
from family_finance.api.idempotency import IdempotencyKeyReusedError
from family_finance.config import Settings
from family_finance.persistence.db import Database
from family_finance.services import ImportService

MULTIPART_OVERHEAD_BYTES = 1 * 1024 * 1024
MULTIPART_UPLOAD_ROUTE_LIMITS = {
    ("POST", "/api/v1/imports/familybiz/previews"): "max_compressed_bytes",
    ("POST", "/api/v1/imports/familybiz/commits"): "max_compressed_bytes",
    ("POST", "/api/v1/planning/seeds/csv/previews"): "planning_csv_max_bytes",
    ("POST", "/api/v1/planning/seeds/csv/commits"): "planning_csv_max_bytes",
    ("POST", "/api/v1/net-worth/csv/previews"): "net_worth_csv_max_bytes",
    ("POST", "/api/v1/net-worth/csv/commits"): "net_worth_csv_max_bytes",
}


def request_body_limit(
    method: str,
    path: str,
    content_type: str | None,
    settings: Settings,
) -> int:
    """Return a parser-aligned multipart cap or the small JSON cap.

    Only explicitly enumerated upload routes receive file-size allowance.
    Every multipart body is bounded by parser file bytes plus 1 MiB for the
    multipart boundary, filename, token, and bounded form fields.
    """

    media_type = (content_type or "").split(";", 1)[0].strip().casefold()
    route = (method.upper(), path.rstrip("/") or "/")
    parser_limit_name = MULTIPART_UPLOAD_ROUTE_LIMITS.get(route)
    if parser_limit_name and media_type == "multipart/form-data":
        return int(getattr(settings, parser_limit_name)) + MULTIPART_OVERHEAD_BYTES
    return settings.api_max_request_bytes


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=1, max_length=1024, repr=False)


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        fields: dict[str, list[str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.fields = fields
        self.headers = headers or {}


def _envelope(data: Any, request_id: str) -> dict[str, Any]:
    return {"data": data, "meta": {"request_id": request_id}}


def _error_envelope(
    request_id: str,
    code: str,
    message: str,
    fields: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message, "request_id": request_id}
    if fields:
        error["fields"] = fields
    return {"error": error}


class RequestContextMiddleware:
    """Assign a server request ID and enforce same-origin mutations/no-store."""

    def __init__(
        self,
        app,
        *,
        public_origin: str | None,
        trusted_hosts: tuple[str, ...],
    ) -> None:
        self.app = app
        self.public_origin = public_origin.rstrip("/") if public_origin else None
        self.trusted_hosts = trusted_hosts

    def _host_is_trusted(self, host_header: str) -> bool:
        hostname = urlsplit(f"//{host_header}").hostname
        if not hostname:
            return False
        hostname = hostname.casefold().rstrip(".")
        for allowed in self.trusted_hosts:
            candidate = allowed.casefold().rstrip(".")
            if candidate == "*" or hostname == candidate:
                return True
            if candidate.startswith("*") and hostname.endswith(candidate[1:]):
                return True
        return False

    @staticmethod
    async def _reject(scope, receive, send, request_id, status_code, code, message):
        response = JSONResponse(
            _error_envelope(request_id, code, message),
            status_code=status_code,
            headers={
                "X-Request-ID": request_id,
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
            },
        )
        await response(scope, receive, send)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid.uuid4())
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        method = scope.get("method", "GET").upper()
        path = scope.get("path", "")
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        host = headers.get(b"host", b"").decode("latin-1")
        if path.startswith("/api/") and not self._host_is_trusted(host):
            await self._reject(
                scope,
                receive,
                send,
                request_id,
                400,
                "HOST_NOT_ALLOWED",
                "Request host is not allowed",
            )
            return
        if path.startswith("/api/") and method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin_bytes = headers.get(b"origin")
            origin = origin_bytes.decode("latin-1").rstrip("/") if origin_bytes else ""
            expected = self.public_origin or f"{scope.get('scheme', 'http')}://{host}"
            if origin != expected:
                await self._reject(
                    scope,
                    receive,
                    send,
                    request_id,
                    403,
                    "ORIGIN_REJECTED",
                    "Request origin is not allowed",
                )
                return

        is_api_v1 = path == "/api/v1" or path.startswith("/api/v1/")
        is_public_health = path == "/api/v1/health" and method in {"GET", "HEAD"}
        is_sign_in = path == "/api/v1/auth/session" and method == "POST"
        if is_api_v1 and not is_public_health and not is_sign_in:
            cookie_header = headers.get(b"cookie", b"").decode("latin-1")
            cookies = SimpleCookie()
            try:
                cookies.load(cookie_header)
            except CookieError:
                cookies = SimpleCookie()
            morsel = cookies.get(SESSION_COOKIE_NAME)
            token = morsel.value if morsel else None
            app = scope.get("app")
            try:
                authenticated = (
                    await run_in_threadpool(app.state.auth_service.authenticate, token)
                    if app
                    else None
                )
            except OperationalError as exc:
                message = str(getattr(exc, "orig", "")).casefold()
                if "locked" in message or "busy" in message:
                    response = JSONResponse(
                        _error_envelope(
                            request_id,
                            "DATABASE_BUSY",
                            "The database is temporarily busy",
                        ),
                        status_code=503,
                        headers={
                            "X-Request-ID": request_id,
                            "Cache-Control": "private, no-store",
                            "Retry-After": "1",
                        },
                    )
                    await response(scope, receive, send)
                    return
                authenticated = None
            except SQLAlchemyError:
                response = JSONResponse(
                    _error_envelope(
                        request_id,
                        "INTERNAL_ERROR",
                        "The request could not be completed",
                    ),
                    status_code=500,
                    headers={"X-Request-ID": request_id, "Cache-Control": "private, no-store"},
                )
                await response(scope, receive, send)
                return
            if authenticated is None:
                await self._reject(
                    scope,
                    receive,
                    send,
                    request_id,
                    401,
                    "AUTHENTICATION_REQUIRED",
                    "Sign in to continue",
                )
                return
            user, csrf_token = authenticated
            state["authenticated_user"] = user
            state["csrf_token"] = csrf_token
            if method in {"POST", "PUT", "PATCH", "DELETE"}:
                csrf_header = headers.get(b"x-csrf-token", b"").decode("latin-1")
                if not app.state.auth_service.verify_csrf(csrf_token, csrf_header):
                    await self._reject(
                        scope,
                        receive,
                        send,
                        request_id,
                        403,
                        "CSRF_REJECTED",
                        "Request verification failed",
                    )
                    return

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                raw_headers = list(message.get("headers", []))
                raw_headers.extend(
                    [
                        (b"x-request-id", request_id.encode("ascii")),
                        (b"cache-control", b"private, no-store"),
                        (b"pragma", b"no-cache"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"x-frame-options", b"DENY"),
                    ]
                )
                message["headers"] = raw_headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RequestSizeLimitMiddleware:
    """Enforce small JSON and parser-aligned multipart limits, including chunked bodies."""

    def __init__(self, app, *, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        method = scope.get("method", "GET")
        path = scope.get("path", "")
        content_type = headers.get(b"content-type", b"").decode("latin-1")
        limit = request_body_limit(method, path, content_type, self.settings)
        try:
            content_length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            content_length = 0
        if content_length > limit:
            await self._reject_too_large(scope, receive, send)
            return

        chunks = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            chunks.extend(message.get("body", b""))
            if len(chunks) > limit:
                await self._reject_too_large(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        body = bytes(chunks)
        delivered = False

        async def replay_receive():
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _reject_too_large(scope, receive, send) -> None:
        request_id = scope.get("state", {}).get("request_id", str(uuid.uuid4()))
        response = JSONResponse(
            _error_envelope(request_id, "REQUEST_TOO_LARGE", "Request body exceeds the configured limit"),
            status_code=413,
            headers={
                "X-Request-ID": request_id,
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
            },
        )
        await response(scope, receive, send)


def current_user(request: Request) -> AuthenticatedUser:
    user = getattr(request.state, "authenticated_user", None)
    csrf_token = getattr(request.state, "csrf_token", None)
    if user is not None and csrf_token is not None:
        return user
    token = request.cookies.get(SESSION_COOKIE_NAME)
    authenticated = request.app.state.auth_service.authenticate(token)
    if authenticated is None:
        raise ApiError(401, "AUTHENTICATION_REQUIRED", "Sign in to continue")
    user, csrf_token = authenticated
    request.state.authenticated_user = user
    request.state.csrf_token = csrf_token
    return user


def require_csrf(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
) -> None:
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    token = request.headers.get("X-CSRF-Token")
    if not request.app.state.auth_service.verify_csrf(request.state.csrf_token, token):
        raise ApiError(403, "CSRF_REJECTED", "Request verification failed")


def authenticated_router(*, prefix: str = "") -> APIRouter:
    """Create a feature router with authentication and CSRF checks on all writes."""

    return APIRouter(
        prefix=f"/api/v1{prefix}",
        dependencies=[Depends(current_user), Depends(require_csrf)],
    )


def create_app(
    *,
    settings: Settings | None = None,
    database: Database | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_environment()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved_settings.ensure_directories()
        owns_database = database is None
        app.state.database = database or Database(resolved_settings.database_path)
        # Construct the existing service graph once per process. This keeps all
        # HTTP routes on the same data root and avoids per-request initialization.
        app.state.services = ImportService(settings=resolved_settings, database=app.state.database)
        app.state.auth_service = AuthService(app.state.database, resolved_settings)
        yield
        if owns_database:
            app.state.database.engine.dispose()

    app = FastAPI(
        title="FamilyFin API",
        version="1",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(
        RequestContextMiddleware,
        public_origin=resolved_settings.api_public_origin,
        trusted_hosts=resolved_settings.api_trusted_hosts,
    )
    app.add_middleware(
        RequestSizeLimitMiddleware,
        settings=resolved_settings,
    )

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return JSONResponse(
            _error_envelope(request.state.request_id, exc.code, exc.message, exc.fields),
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        fields: dict[str, list[str]] = {}
        for item in exc.errors():
            key = ".".join(str(part) for part in item.get("loc", ()) if part != "body") or "request"
            fields.setdefault(key, []).append("Invalid or missing value")
        return JSONResponse(
            _error_envelope(request.state.request_id, "VALIDATION_ERROR", "Request validation failed", fields),
            status_code=422,
        )

    @app.exception_handler(IdempotencyKeyReusedError)
    async def idempotency_conflict_handler(request: Request, _exc: IdempotencyKeyReusedError):
        return JSONResponse(
            _error_envelope(
                request.state.request_id,
                "IDEMPOTENCY_KEY_REUSED",
                "Idempotency key was already used for a different request",
            ),
            status_code=409,
        )

    @app.exception_handler(OperationalError)
    async def database_error_handler(request: Request, exc: OperationalError):
        message = str(getattr(exc, "orig", "")).casefold()
        if "locked" in message or "busy" in message:
            return JSONResponse(
                _error_envelope(
                    request.state.request_id,
                    "DATABASE_BUSY",
                    "The database is temporarily busy",
                ),
                status_code=503,
                headers={"Retry-After": "1"},
            )
        return JSONResponse(
            _error_envelope(
                request.state.request_id,
                "INTERNAL_ERROR",
                "The request could not be completed",
            ),
            status_code=500,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, _exc: Exception):
        return JSONResponse(
            _error_envelope(
                getattr(request.state, "request_id", "unknown"),
                "INTERNAL_ERROR",
                "The request could not be completed",
            ),
            status_code=500,
        )

    public_router = APIRouter(prefix="/api/v1")

    @public_router.get("/health")
    def health(request: Request):
        # This endpoint reveals availability only, never household values.
        with request.app.state.database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return _envelope({"status": "ok"}, request.state.request_id)

    auth_router = APIRouter(prefix="/api/v1/auth")

    @auth_router.post("/session")
    def sign_in(body: LoginBody, request: Request, response: Response):
        try:
            # The server entry point disables proxy-header trust. Behind the
            # single loopback proxy this intentionally forms one throttle
            # bucket per account; never split it using client-supplied XFF.
            credentials = request.app.state.auth_service.login(
                username=body.username,
                password=body.password,
                client_key=request.client.host if request.client else "unknown",
                request_id=request.state.request_id,
            )
        except LoginRateLimitedError:
            raise ApiError(
                429,
                "LOGIN_THROTTLED",
                "Sign-in temporarily unavailable",
                headers={"Retry-After": "900"},
            ) from None
        except AuthenticationError:
            raise ApiError(401, "INVALID_CREDENTIALS", "Username or password is incorrect") from None
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=credentials.token,
            max_age=resolved_settings.api_session_hours * 60 * 60,
            path="/api/v1",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return _envelope(
            {
                "user": {
                    "id": credentials.user.user_id,
                    "username": credentials.user.username,
                    "display_name": credentials.user.display_name,
                },
                "csrf_token": credentials.csrf_token,
                "expires_at": credentials.expires_at,
            },
            request.state.request_id,
        )

    @auth_router.get("/session")
    def session_info(request: Request, user: Annotated[AuthenticatedUser, Depends(current_user)]):
        return _envelope(
            {
                "user": {
                    "id": user.user_id,
                    "username": user.username,
                    "display_name": user.display_name,
                },
                "csrf_token": request.state.csrf_token,
            },
            request.state.request_id,
        )

    @auth_router.delete("/session")
    def sign_out(
        request: Request,
        user: Annotated[AuthenticatedUser, Depends(current_user)],
        _csrf: Annotated[None, Depends(require_csrf)],
    ):
        token = request.cookies.get(SESSION_COOKIE_NAME, "")
        request.app.state.auth_service.logout(
            token=token,
            actor_id=user.user_id,
            request_id=request.state.request_id,
        )
        response = Response(status_code=204)
        response.delete_cookie(
            SESSION_COOKIE_NAME,
            path="/api/v1",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return response

    app.include_router(public_router)
    app.include_router(auth_router)
    # Keep each financial adapter feature-owned. The import is local to avoid
    # coupling the transport foundation to feature schema modules at import time.
    from family_finance.api.routers.net_worth import router as net_worth_router

    app.include_router(net_worth_router)
    return app
