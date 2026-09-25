import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_runtime_services_and_proxy_bind_only_to_loopback() -> None:
    api_service = _read("deploy/systemd/familyfin-api.service")
    web_service = _read("deploy/systemd/familyfin-web.service")
    caddy = _read("deploy/caddy/familyfin.Caddyfile")
    package = _read("frontend/package.json")
    api_cli = _read("src/family_finance/api/cli.py")

    assert "family-finance-api" in api_service
    assert "127.0.0.1:8000" in api_service or "FAMILY_FINANCE_API_PORT=8000" in api_service
    assert 'host="127.0.0.1"' in api_cli
    assert "workers=1" in api_cli
    assert "proxy_headers=False" in api_cli
    assert "access_log=False" in api_cli
    assert '"start": "NEXT_TELEMETRY_DISABLED=1 next start --hostname 127.0.0.1"' in package
    assert "PORT=3000" in web_service
    assert "bind 127.0.0.1" in caddy
    assert "reverse_proxy 127.0.0.1:8000" in caddy
    assert "reverse_proxy 127.0.0.1:3000" in caddy
    assert "access_log" not in api_service.casefold()
    assert "log {" not in caddy


def test_backup_job_requires_a_separate_mount_and_verifies_the_snapshot() -> None:
    backup = _read("deploy/bin/familyfin-backup")
    service = _read("deploy/systemd/familyfin-backup.service")
    timer = _read("deploy/systemd/familyfin-backup.timer")

    assert "umask 077" in backup
    assert "mountpoint -q" in backup
    assert "Backup destination must be outside the active data root" in backup
    assert "family-finance backup" in backup
    assert "family-finance verify-backup" in backup
    assert "ReadWritePaths=/var/lib/familyfin/data /mnt/familyfin-backup" in service
    assert "OnCalendar=*-*-* 02:15:00 UTC" in timer
    assert "rm " not in backup

    subprocess.run(["bash", "-n", str(ROOT / "deploy/bin/familyfin-backup")], check=True)


def test_deployment_docs_require_tailnet_only_access_and_no_funnel() -> None:
    deployment = _read("docs/pwa/deployment.md")

    assert "tailscale serve --bg --https=443 http://127.0.0.1:8080" in deployment
    assert "tailscale funnel status" in deployment
    assert "Funnel status must show no active endpoint" in deployment
    assert "non-tailnet device" in deployment
    assert "Cache-Control: private, no-store" in deployment
