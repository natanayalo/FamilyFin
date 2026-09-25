"""Loopback-only API server entry point."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

import uvicorn

from family_finance.config import Settings


def main() -> None:
    settings = Settings.from_environment()
    if not settings.api_public_origin:
        raise SystemExit("FAMILY_FINANCE_API_PUBLIC_ORIGIN must name the private HTTPS origin")
    origin = urlsplit(settings.api_public_origin)
    if origin.scheme != "https" or not origin.hostname or origin.path not in {"", "/"}:
        raise SystemExit("FAMILY_FINANCE_API_PUBLIC_ORIGIN must be an HTTPS origin without a path")
    host = origin.hostname.casefold()
    if not any(
        allowed == "*"
        or host == allowed.casefold()
        or (allowed.startswith("*") and host.endswith(allowed[1:].casefold()))
        for allowed in settings.api_trusted_hosts
    ):
        raise SystemExit("FAMILY_FINANCE_API_PUBLIC_ORIGIN host must also be in API_TRUSTED_HOSTS")
    port = int(os.environ.get("FAMILY_FINANCE_API_PORT", "8000"))
    if not 1 <= port <= 65535:
        raise SystemExit("FAMILY_FINANCE_API_PORT must be between 1 and 65535")
    uvicorn.run(
        "family_finance.api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        workers=1,
        access_log=False,
        proxy_headers=False,
    )
