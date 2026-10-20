"""Loopback-only API server entry point."""

from __future__ import annotations

import argparse
import os
from urllib.parse import urlsplit

import uvicorn

from family_finance.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Loopback-only FamilyFin API")
    parser.add_argument("--reload", action="store_true", help="Reload Python code in local mode")
    args = parser.parse_args()
    try:
        settings = Settings.from_environment()
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    if not settings.api_public_origin:
        raise SystemExit("FAMILY_FINANCE_API_PUBLIC_ORIGIN must name the application origin")
    origin = urlsplit(settings.api_public_origin)
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
    if args.reload and not settings.api_local_dev:
        raise SystemExit("--reload requires FAMILY_FINANCE_LOCAL_DEV=1")
    uvicorn.run(
        "family_finance.api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        workers=1,
        access_log=False,
        proxy_headers=False,
        reload=args.reload,
        reload_dirs=[str(settings.project_root / "src")] if args.reload else None,
    )


if __name__ == "__main__":
    main()
