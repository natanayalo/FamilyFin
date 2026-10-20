from __future__ import annotations

import hashlib
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import func, select

from alembic import command
from family_finance import localdev
from family_finance.api.app import create_app
from family_finance.api.auth import AuthService, BootstrapAccount
from family_finance.audit import AuditService
from family_finance.config import Settings
from family_finance.localdev import MARKER, ROOT, initialize_data, local_environment
from family_finance.models import AuditCheck, AuditReport
from family_finance.persistence.db import Database
from family_finance.persistence.models import ApiLoginThrottleRow, ApiSessionRow, SourceFileRow
from family_finance.services import ImportService

from .test_api_auth import ApiTestClient


@pytest.fixture
def stop_checkout():
    # macOS Unix socket paths must fit into its short sockaddr_un limit.
    with tempfile.TemporaryDirectory(prefix="ff-stop-", dir="/tmp") as directory:
        yield Path(directory)


def test_stop_without_a_server_needs_no_node_or_development_data(stop_checkout, monkeypatch, capsys):
    monkeypatch.setattr(localdev, "FRONTEND", stop_checkout)
    monkeypatch.setattr(sys, "argv", ["dev", "stop"])
    monkeypatch.setattr(
        localdev, "require_dependencies", lambda: pytest.fail("Stop must not check dependencies")
    )
    localdev.main()
    assert "No local FamilyFin server is running" in capsys.readouterr().out


def test_stop_ignores_a_stale_socket(stop_checkout, monkeypatch, capsys):
    monkeypatch.setattr(localdev, "FRONTEND", stop_checkout)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(localdev.control_socket_path()))
    localdev.stop()
    assert "No local FamilyFin server is running" in capsys.readouterr().out


@pytest.mark.parametrize("phase", ["serving", "build"])
def test_stop_waits_for_supervisor_and_all_children_to_exit(
    stop_checkout, monkeypatch, capsys, phase
):
    tmp_path = stop_checkout
    monkeypatch.setattr(localdev, "FRONTEND", tmp_path)
    # Exercise the real cross-process control protocol and process-group cleanup.
    supervisor_code = """
import os, signal, sys, time
from pathlib import Path
from family_finance import localdev
localdev.FRONTEND = Path(sys.argv[1])
def interrupted(*_):
    raise KeyboardInterrupt
signal.signal(signal.SIGTERM, interrupted)
try:
    with localdev.workspace_lock(), localdev.stop_listener(), localdev.Processes(os.environ.copy()) as processes:
        if sys.argv[2] == 'build':
            localdev.run([
                sys.executable, '-c',
                'import os, sys, time; from pathlib import Path; Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)',
                str(localdev.FRONTEND / 'children'),
            ], os.environ.copy())
        else:
            for name in ('API', 'PWA'):
                processes.start(name, [sys.executable, '-c', 'import time; time.sleep(60)'])
            (localdev.FRONTEND / 'children').write_text(' '.join(str(p.pid) for _, p in processes.children))
        while True:
            time.sleep(0.1)
except KeyboardInterrupt:
    pass
"""
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    supervisor = subprocess.Popen(
        [sys.executable, "-c", supervisor_code, str(tmp_path), phase], env=env
    )
    try:
        deadline = time.monotonic() + 10
        while not (tmp_path / "children").exists():
            assert supervisor.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert stat.S_IMODE(localdev.control_socket_path().stat().st_mode) == 0o600
        child_pids = [int(pid) for pid in (tmp_path / "children").read_text().split()]
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.connect(str(localdev.control_socket_path()))
            connection.sendall(b"invalid\n")
            assert connection.recv(32) == b"invalid\n"
        other_checkout = tmp_path / "other"
        other_checkout.mkdir()
        monkeypatch.setattr(localdev, "FRONTEND", other_checkout)
        localdev.stop()
        assert supervisor.poll() is None
        monkeypatch.setattr(localdev, "FRONTEND", tmp_path)
        localdev.stop()
        supervisor.wait(timeout=5)
        assert supervisor.returncode == 0
        assert not localdev.control_socket_path().exists()
        for pid in child_pids:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
        localdev.stop()
        output = capsys.readouterr().out
        assert "Stopped local FamilyFin services" in output
        assert "No local FamilyFin server is running" in output
    finally:
        if supervisor.poll() is None:
            supervisor.terminate()
            supervisor.wait(timeout=10)


def test_launcher_imports_standard_logging_before_initializing_data(tmp_path):
    # A separate checkout avoids the workspace lock held by ./dev check.
    checkout = tmp_path / "checkout"
    shutil.copytree(ROOT / "src", checkout / "src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "dev", checkout / "dev")
    shutil.copy(ROOT / ".nvmrc", checkout / ".nvmrc")
    (checkout / ".venv").symlink_to(ROOT / ".venv", target_is_directory=True)
    next_binary = checkout / "frontend/node_modules/.bin/next"
    next_binary.parent.mkdir(parents=True)
    next_binary.touch()
    # Supply the pinned version without requiring Node for this Python regression.
    binaries = tmp_path / "bin"
    binaries.mkdir()
    node = binaries / "node"
    node.write_text(f"#!/bin/sh\necho v{(ROOT / '.nvmrc').read_text().strip()}\n")
    node.chmod(0o755)
    npm = binaries / "npm"
    npm.write_text("#!/bin/sh\nexit 0\n")
    npm.chmod(0o755)
    result = subprocess.run(
        [
            str(checkout / "dev"),
            "init-data",
            "--source",
            str(tmp_path / "missing"),
            "--source-stopped",
        ],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{binaries}:{os.environ.get('PATH', '')}"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Source database is missing" in result.stderr
    assert "Traceback" not in result.stderr


def accounts():
    return [
        BootstrapAccount("dev-one", "Dev One", "Local-test-password-One!"),
        BootstrapAccount("dev-two", "Dev Two", "Local-test-password-Two!"),
    ]


def file_hashes(root: Path):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and not path.name.endswith(("-wal", "-shm"))
    }


def source_data(root, payload, *, old_schema=False):
    settings = Settings(data_root=root)
    service = ImportService(settings)
    preview = service.preview_import(payload, "source.xlsx")
    service.commit_import(payload, preview.preview_token, "source.xlsx")
    service.database.engine.dispose()
    if old_schema:
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["family_finance_database_url"] = f"sqlite:///{settings.database_path}"
        command.downgrade(config, "0010_automation_and_insights")
    return settings


def test_old_data_copy_migrates_only_snapshot_relocates_archives_and_audits(
    tmp_path, familybiz_workbook_bytes, monkeypatch
):
    source = source_data(tmp_path / "source", familybiz_workbook_bytes, old_schema=True)
    original = file_hashes(source.data_root)
    # An inherited migration URL must never update the source or an unrelated database.
    monkeypatch.setenv("FAMILY_FINANCE_DATABASE_URL", f"sqlite:///{source.database_path}")
    destination = tmp_path / "development"
    initialize_data(source.data_root, destination, accounts_factory=accounts)
    assert file_hashes(source.data_root) == original
    settings = Settings(data_root=destination)
    database = Database(settings.database_path, read_only=True)
    try:
        assert AuditService(database, settings).run().passed
        assert database.count("transactions") == 1
        auth = AuthService(database, settings)
        assert auth.account_count() == 2
        with database.session() as session:
            source_file = session.scalar(select(SourceFileRow))
            assert not Path(source_file.archived_path).is_absolute()
            assert (
                destination / source_file.archived_path
            ).read_bytes() == familybiz_workbook_bytes
        assert (destination / MARKER).is_file()
        assert stat.S_IMODE((destination / "api-secret.key").stat().st_mode) == 0o600
    finally:
        database.engine.dispose()


def test_existing_accounts_are_preserved_with_new_secret_and_no_sessions(
    tmp_path, familybiz_workbook_bytes
):
    source = source_data(tmp_path / "source", familybiz_workbook_bytes)
    database = Database(source.database_path)
    auth = AuthService(database, source)
    auth.bootstrap_accounts(accounts())
    auth.login(
        username="dev-one",
        password=accounts()[0].password,
        client_key="127.0.0.1",
        request_id="test",
    )
    database.engine.dispose()
    source_secret = (source.data_root / "api-secret.key").read_bytes()
    original = file_hashes(source.data_root)
    destination = tmp_path / "development"

    def unexpected_bootstrap():
        pytest.fail("Existing accounts must not be re-bootstrapped")

    initialize_data(source.data_root, destination, accounts_factory=unexpected_bootstrap)
    assert file_hashes(source.data_root) == original
    assert (destination / "api-secret.key").read_bytes() != source_secret
    settings = Settings(data_root=destination)
    database = Database(settings.database_path)
    try:
        auth = AuthService(database, settings)
        assert auth.account_count() == 2
        with database.session() as session:
            assert session.scalar(select(func.count()).select_from(ApiSessionRow)) == 0
            assert session.scalar(select(func.count()).select_from(ApiLoginThrottleRow)) == 0
        assert (
            auth.login(
                username="dev-one",
                password=accounts()[0].password,
                client_key="local",
                request_id="test",
            ).user.username
            == "dev-one"
        )
    finally:
        database.engine.dispose()


def test_initialization_refuses_overwrite_missing_archives_and_failed_audit(
    tmp_path, familybiz_workbook_bytes, monkeypatch
):
    source = source_data(tmp_path / "source", familybiz_workbook_bytes)
    destination = tmp_path / "development"
    destination.mkdir()
    sentinel = destination / "keep"
    sentinel.write_text("preserved")
    with pytest.raises(FileExistsError):
        initialize_data(source.data_root, destination, accounts_factory=accounts)
    assert sentinel.read_text() == "preserved"
    with pytest.raises(ValueError, match="outside"):
        initialize_data(source.data_root, source.data_root / "nested", accounts_factory=accounts)
    monkeypatch.setattr(
        AuditService,
        "run",
        lambda _: AuditReport(
            passed=False,
            checks=[AuditCheck(name="test", passed=False, issue_codes=["TEST_FAILURE"])],
        ),
    )
    original = file_hashes(source.data_root)
    with pytest.raises(RuntimeError, match="TEST_FAILURE"):
        initialize_data(source.data_root, tmp_path / "failed-audit", accounts_factory=accounts)
    assert not (tmp_path / "failed-audit").exists()
    assert file_hashes(source.data_root) == original
    next(source.archive_root.iterdir()).unlink()
    with pytest.raises(FileNotFoundError, match="archive"):
        initialize_data(source.data_root, tmp_path / "missing-archive", accounts_factory=accounts)
    assert not (tmp_path / "missing-archive").exists()
    assert not list(tmp_path.glob(".dev-local-*"))


def test_database_constructor_path_wins_over_inherited_migration_url(tmp_path, monkeypatch):
    unrelated = tmp_path / "unrelated.sqlite3"
    monkeypatch.setenv("FAMILY_FINANCE_DATABASE_URL", f"sqlite:///{unrelated}")
    database = Database(tmp_path / "owned.sqlite3")
    assert database.count("transactions") == 0
    assert not unrelated.exists()
    database.engine.dispose()


def test_launcher_overrides_inherited_financial_paths_and_origin(tmp_path, monkeypatch):
    for name in (
        "FAMILY_FINANCE_DATA_ROOT",
        "FAMILY_FINANCE_DATABASE_URL",
        "FAMILY_FINANCE_AUTOMATION_BACKUP_ROOT",
        "FAMILY_FINANCE_API_PUBLIC_ORIGIN",
        "FAMILY_FINANCE_API_TRUSTED_HOSTS",
    ):
        monkeypatch.setenv(name, "production-value")
    env = local_environment(tmp_path)
    assert env["FAMILY_FINANCE_DATA_ROOT"] == str(tmp_path)
    assert env["FAMILY_FINANCE_DATABASE_URL"] == f"sqlite:///{tmp_path}/family_finance.sqlite3"
    assert env["FAMILY_FINANCE_API_PUBLIC_ORIGIN"] == "http://127.0.0.1:3000"
    assert env["FAMILY_FINANCE_API_TRUSTED_HOSTS"] == "127.0.0.1,localhost"
    assert env["UV_OFFLINE"] == env["UV_NO_SYNC"] == "1"
    assert os.environ["FAMILY_FINANCE_DATA_ROOT"] == "production-value"


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://[::1]:3000",
    ],
)
def test_http_requires_explicit_local_mode(origin):
    with pytest.raises(ValueError, match="HTTPS"):
        Settings(api_public_origin=origin)
    settings = Settings(
        api_public_origin=origin,
        api_local_dev=True,
        api_trusted_hosts=("localhost", "127.0.0.1", "::1"),
    )
    assert settings.api_secure_cookie is False
    assert Settings(api_public_origin=origin.replace("http:", "https:")).api_secure_cookie


@pytest.mark.parametrize(
    "origin",
    [
        "http://192.168.1.2:3000",
        "http://127.0.0.2:3000",
        "http://localhost.evil:3000",
        "http://user:password@127.0.0.1:3000",
        "http://127.0.0.1:3000/api",
        "http://127.0.0.1:3000?q=1",
        "http://127.0.0.1:3000#fragment",
        "http://127.0.0.1:0",
        "http://127.0.0.1:99999",
    ],
)
def test_local_mode_rejects_nonlocal_or_malformed_origins(origin):
    with pytest.raises(ValueError):
        Settings(api_public_origin=origin, api_local_dev=True)


def test_local_mode_rejects_wildcard_or_external_trusted_hosts():
    with pytest.raises(ValueError, match="exact loopback"):
        Settings(api_local_dev=True, api_trusted_hosts=("*",))
    with pytest.raises(ValueError, match="exact loopback"):
        Settings(api_local_dev=True, api_trusted_hosts=("example.com",))


def test_http_login_session_cookie_origin_csrf_and_logout(tmp_path):
    origin = "http://127.0.0.1:3000"
    settings = Settings(data_root=tmp_path, api_public_origin=origin, api_local_dev=True)
    database = Database(settings.database_path)
    AuthService(database, settings).bootstrap_accounts(accounts())
    try:
        with ApiTestClient(
            create_app(settings=settings, database=database), base_url=origin
        ) as client:
            response = client.post(
                "/api/v1/auth/session",
                json={
                    "username": "dev-one",
                    "password": accounts()[0].password,
                },
                headers={"Origin": origin},
            )
            assert response.status_code == 200
            cookie = response.headers["set-cookie"].casefold()
            assert "secure" not in cookie and "httponly" in cookie and "samesite=strict" in cookie
            assert client.get("/api/v1/auth/session").status_code == 200
            csrf = response.json()["data"]["csrf_token"]
            assert (
                client.delete("/api/v1/auth/session", headers={"Origin": origin}).status_code == 403
            )
            assert (
                client.delete(
                    "/api/v1/auth/session",
                    headers={
                        "Origin": "http://localhost:3000",
                        "X-CSRF-Token": csrf,
                    },
                ).status_code
                == 403
            )
            assert client.get("/api/v1/health", headers={"Host": "evil.example"}).status_code == 400
            assert (
                client.delete(
                    "/api/v1/auth/session",
                    headers={
                        "Origin": origin,
                        "X-CSRF-Token": csrf,
                    },
                ).status_code
                == 204
            )
            assert client.get("/api/v1/auth/session").status_code == 401
    finally:
        database.engine.dispose()
