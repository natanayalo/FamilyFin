"""Container-only entry point. Preserve the Linux API CLI's loopback default."""
import os
import sys
from urllib.parse import urlsplit
from urllib.request import urlopen

os.umask(0o077)

if sys.argv[1] == "health":
    with urlopen("http://127.0.0.1:8000/api/v1/health", timeout=3) as response:
        assert response.status == 200
        assert response.headers["Cache-Control"] == "private, no-store"
        assert b'"ok"' in response.read()
elif sys.argv[1] == "operations":
    from operations import main
    main(sys.argv[2:])
elif sys.argv[1] == "serve":
    import uvicorn

    from family_finance.config import Settings
    settings = Settings.from_environment()
    if settings.api_local_dev or not settings.api_public_origin:
        raise SystemExit("Production HTTPS origin required; local development mode forbidden")
    host = urlsplit(settings.api_public_origin).hostname
    if host not in settings.api_trusted_hosts or any("*" in h for h in settings.api_trusted_hosts):
        raise SystemExit("Exact origin host must be trusted; wildcard hosts forbidden")
    uvicorn.run("family_finance.api.app:create_app", factory=True, host="0.0.0.0",
                port=8000, workers=1, access_log=False, proxy_headers=False,
                server_header=False)
else:
    # Preserve console-only interactive account bootstrap and recovery.
    if sys.argv[1] == "family-finance":
        from family_finance.cli import main
        sys.argv = sys.argv[1:]
        main()
    else:
        os.execvp(sys.argv[1], sys.argv[1:])
