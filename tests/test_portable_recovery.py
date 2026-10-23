"""Real snapshots/age round trips and current recovery-readiness regressions."""
import hashlib
import importlib
import io
import json
import os
import subprocess
import sys
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from family_finance.audit import AuditService
from family_finance.automation import AutomationService
from family_finance.backup import BackupService
from family_finance.config import Settings
from family_finance.persistence.db import Database
from family_finance.persistence.models import AutomationFileOutcomeRow, TransactionRow
from family_finance.services import ImportService

from .conftest import make_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/docker"))
stream = importlib.import_module("portable_stream")
host = importlib.import_module("portable_backup")
operations = importlib.import_module("operations")
IMAGE = "sha256:" + "a" * 64
SNAPSHOT = "familyfin-" + "b" * 32
ARCHIVE = "20261023T120000Z-" + SNAPSHOT + ".tar.age"


@pytest.fixture
def recovery_status(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    archive = media / ARCHIVE
    archive.write_bytes(b"disposable ciphertext fixture")
    receipt = {"status": "PASS", "last_success_at": datetime.now(UTC).isoformat(),
               "archive": ARCHIVE, "archive_sha256": host.digest(archive)}
    host.save_json(tmp_path / "last-run.json", receipt)
    config = {"directory": str(media)}
    monkeypatch.setattr(host, "read_config", lambda _: config)
    monkeypatch.setattr(host, "media", lambda *_, **__: {"FreeBytes": 0})
    monkeypatch.setattr(host, "identity", lambda _: tmp_path / "disposable-key")
    return tmp_path, config, receipt, archive


def status(root, *extra):
    with patch("sys.argv", ["backup", "status", "--config", str(root / "config.json"), *extra]), \
            patch("sys.stdout", new_callable=io.StringIO) as output:
        code = host.main()
    return code, json.loads(output.getvalue())


def test_current_status_checks_availability_without_requiring_export_free_space(recovery_status):
    root, _, receipt, _ = recovery_status
    code, result = status(root)
    assert code == 0 and result["status"] == "PASS"
    assert result["last_backup_successful"] and result["last_backup_recent"]
    assert result["recovery_media_available"] and result["recovery_key_available"]
    assert result["archive_integrity_verified"] is None
    assert not result["integrity_check_requested"]
    assert result["last_run"] == receipt


@pytest.mark.parametrize("failure", ["absent-media", "wrong-media", "missing-archive", "missing-key"])
def test_recent_success_does_not_hide_unavailable_recovery(recovery_status, monkeypatch, failure):
    root, _, receipt, archive = recovery_status
    if failure.endswith("media"):
        def unavailable(*_, **__):
            raise ValueError("private media details must not escape")
        monkeypatch.setattr(host, "media", unavailable)
    elif failure == "missing-archive":
        archive.unlink()
    else:
        def unavailable(_):
            raise FileNotFoundError("private key details must not escape")
        monkeypatch.setattr(host, "identity", unavailable)
    code, result = status(root)
    assert code == 1 and result["status"] == "RECOVERY_UNAVAILABLE"
    assert result["last_backup_successful"] and result["last_backup_recent"]
    assert not result["backup_healthy"] and not result["recovery_ready"]
    assert "private" not in json.dumps(result)
    assert json.loads((root / "last-run.json").read_text()) == receipt
    assert not (root / "backup-alert.json").exists()  # Read-only status.


@pytest.mark.parametrize("name", ["../outside.tar.age", "/outside", "C:\\outside", "wrong.tar.age", ARCHIVE + ".partial"])
def test_status_rejects_unsafe_or_unfinalized_receipt_archive(recovery_status, name):
    root, _, receipt, _ = recovery_status
    host.save_json(root / "last-run.json", receipt | {"archive": name})
    code, result = status(root)
    assert code == 1 and not result["archive_available"]


def test_integrity_is_explicit_and_detects_tampering_without_rewriting_success(recovery_status):
    root, _, receipt, archive = recovery_status
    code, result = status(root, "--verify-integrity")
    assert code == 0 and result["archive_integrity_verified"] is True
    archive.write_bytes(b"changed ciphertext")
    assert status(root)[0] == 0  # Presence check never claims a hash verification.
    code, result = status(root, "--verify-integrity")
    assert code == 1 and result["archive_integrity_verified"] is False
    assert result["archive_available"] and not result["recovery_ready"]
    assert json.loads((root / "last-run.json").read_text()) == receipt


def test_stale_backup_remains_unhealthy_with_available_recovery(recovery_status):
    root, _, receipt, _ = recovery_status
    host.save_json(root / "last-run.json", receipt | {
        "last_success_at": (datetime.now(UTC) - timedelta(hours=27)).isoformat()})
    code, result = status(root)
    assert code == 1 and result["status"] == "FAIL_OR_STALE"
    assert result["recovery_ready"] and not result["last_backup_recent"]


@pytest.mark.parametrize("name", ["a" * 100 + ".xlsx", "א" * 55 + ".xlsx"])
def test_real_long_name_snapshot_pack_round_trip(tmp_path, monkeypatch, name):
    snapshot, payload = make_snapshot(tmp_path, name)
    monkeypatch.setenv("FAMILY_FINANCE_DATA_ROOT", str(tmp_path / "unused-settings"))
    packed = io.BytesIO()
    stream.pack(snapshot.parent, snapshot.name, IMAGE, packed)
    assert_headers(packed.getvalue(), name)
    stage = tmp_path / "stage"
    stage.mkdir()
    stream.unpack(stage, IMAGE, "token", io.BytesIO(packed.getvalue()))
    stream.finalize(stage, IMAGE, "token")
    verify_and_restore(tmp_path, stage, name, payload, monkeypatch)


@pytest.mark.parametrize("name", ["a" * 100 + ".xlsx", "א" * 55 + ".xlsx"])
def test_age_encrypted_long_name_snapshot_clean_restore(tmp_path, monkeypatch, name):
    directory = os.environ.get("FAMILYFIN_TEST_AGE_DIR")
    if not directory:
        pytest.skip("Set FAMILYFIN_TEST_AGE_DIR to reviewed age/age-keygen tools; CI requires this drill")
    suffix = ".exe" if sys.platform == "win32" else ""
    age = str(Path(directory) / ("age" + suffix))
    keygen = str(Path(directory) / ("age-keygen" + suffix))
    key = tmp_path / "disposable-identity"
    subprocess.run([keygen, "-o", str(key)], check=True, capture_output=True)
    recipient = subprocess.run([keygen, "-y", str(key)], check=True, capture_output=True).stdout.decode().strip()
    snapshot, payload = make_snapshot(tmp_path, name)
    monkeypatch.setenv("FAMILY_FINANCE_DATA_ROOT", str(tmp_path / "unused-settings"))
    plaintext = io.BytesIO()
    stream.pack(snapshot.parent, snapshot.name, IMAGE, plaintext)
    # Plaintext transport stays in RAM, exactly as in the production pipeline.
    encrypted = subprocess.run([age, "-r", recipient], input=plaintext.getvalue(), check=True, capture_output=True).stdout
    ciphertext = tmp_path / "snapshot.tar.age"
    ciphertext.write_bytes(encrypted)
    assert payload not in encrypted
    decrypted = subprocess.run([age, "-d", "-i", str(key), str(ciphertext)], check=True, capture_output=True).stdout
    stage = tmp_path / "stage"
    stage.mkdir()
    stream.unpack(stage, IMAGE, "token", io.BytesIO(decrypted))
    stream.finalize(stage, IMAGE, "token")
    verify_and_restore(tmp_path, stage, name, payload, monkeypatch)


def make_snapshot(tmp_path, name):
    settings = Settings(data_root=tmp_path / "source", automation_backup_root=tmp_path / "pre-import")
    app = ImportService(settings)
    payload = make_workbook([["19/09/2026", -17.4, "synthetic", "19/09/2026",
                              "purchase", "food", "ILS", "ILS", -17.4]])
    source = settings.automation_inbox_root / name
    source.write_bytes(payload)
    # The scanner requires an old enough mtime before processing new uploads.
    os.utime(source, (1, 1))
    result = AutomationService(settings=settings, database=app.database, import_service=app).run()
    assert result.files[0].status == "committed"
    assert next(settings.automation_processed_root.rglob(name)).read_bytes() == payload
    assert len(name.encode("utf-8")) > 100
    snapshot = tmp_path / "snapshots" / SNAPSHOT
    service = BackupService(app.database, settings)
    service.create(snapshot)
    assert service.verify(snapshot).passed
    app.database.engine.dispose()
    return snapshot, payload


def assert_headers(payload, name):
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        members = archive.getmembers()
        assert any(member.name.endswith("/" + name) and "path" in member.pax_headers for member in members)
        for member in members:
            assert member.uid == member.gid == member.mtime == 0
            assert member.uname == member.gname == ""
            assert member.mode == 0o600
            assert set(member.pax_headers) <= {"path", "size"}


def verify_and_restore(tmp_path, stage, name, payload, monkeypatch):
    restored = tmp_path / "clean-restore"
    restored.mkdir()
    settings = Settings(data_root=restored)
    # Use the actual guarded application restore; substitute only filesystem
    # mount discovery so this regression runs without Docker/root in CI.
    monkeypatch.setattr(operations.Settings, "from_environment", lambda: settings)
    monkeypatch.setattr(operations.os.path, "ismount", lambda _: True)
    monkeypatch.setattr(operations, "Path", lambda value: stage if value == "/backups" else Path(value))
    operations.main(["restore", SNAPSHOT])
    assert AuditService(settings=settings).run().passed
    assert next(settings.automation_processed_root.rglob(name)).read_bytes() == payload
    database = Database(settings.database_path)
    with database.session() as session:
        assert session.query(TransactionRow).count() == 1
        outcome = session.query(AutomationFileOutcomeRow).one()
        assert Path(outcome.managed_path).name == name
        assert outcome.sha256 == hashlib.sha256(payload).hexdigest()
    verification = BackupService(database, settings)
    manifest = verification.create(tmp_path / "post-restore-backup")
    assert manifest.schema_revision and verification.verify(tmp_path / "post-restore-backup").passed
    database.engine.dispose()
