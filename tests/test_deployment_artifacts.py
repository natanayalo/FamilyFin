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


def test_restore_activation_uses_the_canonical_writable_data_root() -> None:
    api_service = _read("deploy/systemd/familyfin-api.service")
    api_env = _read("deploy/systemd/api.env.example")
    backup_service = _read("deploy/systemd/familyfin-backup.service")
    deployment = _read("docs/pwa/deployment.md")
    restore = deployment.split("### Restore practice and incident recovery", 1)[1].split(
        "## Authentication and privacy operations", 1
    )[0]

    assert "ProtectSystem=strict" in api_service
    assert "ReadWritePaths=/var/lib/familyfin/data" in api_service
    assert "EnvironmentFile=/etc/familyfin/api.env" in api_service
    assert "FAMILY_FINANCE_DATA_ROOT=/var/lib/familyfin/data" in api_env
    assert "ReadWritePaths=/var/lib/familyfin/data /mnt/familyfin-backup" in backup_service
    assert "EnvironmentFile=/etc/familyfin/api.env" in backup_service
    assert "familyfin-backup.timer familyfin-backup.service" in restore
    assert "familyfin-web.service familyfin-api.service caddy.service" in restore
    assert "FAMILY_FINANCE_DATABASE_URL=sqlite:////var/lib/familyfin/recovery-staging-" in restore
    assert "FAMILY_FINANCE_DATA_ROOT=/var/lib/familyfin/recovery-staging-" in restore
    assert 'sudo mv -- "$STAGING_ROOT" "$CANONICAL_ROOT"' in restore
    assert 'sudo mv -- "$CANONICAL_ROOT" "$PRESERVED_ROOT"' in restore
    assert "sudo systemctl start familyfin-api.service familyfin-web.service caddy.service" in restore
    assert "sudo systemctl start familyfin-backup.timer" in restore
    assert "Do not repoint the API environment file to the staging directory" in restore
    assert "Point `/etc/familyfin/api.env` at the staging root" not in restore
    assert "familyfin-backup.timer" in restore
    assert "Recovery is accepted only after" in restore
