"""Maintenance guards: failures must precede any restore write."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from family_finance.backup import BackupService
from family_finance.config import Settings
from family_finance.services import ImportService

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("docker_operations", ROOT / "deploy/docker/operations.py")
operations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operations)


def setup_ops(monkeypatch, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(operations.Settings, "from_environment", lambda: SimpleNamespace(data_root=data, database_path=data / 'family_finance.sqlite3'))
    monkeypatch.setattr(operations.os.path, "ismount", lambda _: True)
    return data


def test_missing_volume_blocks_backup_before_application_access(monkeypatch, tmp_path):
    setup_ops(monkeypatch, tmp_path)
    monkeypatch.setattr(operations.os.path, "ismount", lambda _: False)
    monkeypatch.setattr(operations, "BackupService", lambda **_: pytest.fail("must not open database"))
    with pytest.raises(SystemExit, match="mounted volumes"):
        operations.main(["backup"])


@pytest.mark.parametrize("name", ["..", "../snapshot", "/snapshot", "nested/snapshot", ""])
def test_snapshot_path_traversal_is_rejected(monkeypatch, tmp_path, name):
    data = setup_ops(monkeypatch, tmp_path)
    with pytest.raises(SystemExit, match="direct child"):
        operations.main(["restore", name])
    assert list(data.iterdir()) == []


def test_invalid_snapshot_does_not_touch_empty_restore_root(monkeypatch, tmp_path):
    data = setup_ops(monkeypatch, tmp_path)
    monkeypatch.setattr(operations.BackupService, "verify", lambda *_: SimpleNamespace(passed=False))
    with pytest.raises(SystemExit, match="verification failed"):
        operations.main(["restore", "bad-snapshot"])
    assert list(data.iterdir()) == []


def test_nonempty_restore_preserves_existing_file(monkeypatch, tmp_path):
    data = setup_ops(monkeypatch, tmp_path)
    (data / "keep").write_text("unchanged")
    monkeypatch.setattr(operations.BackupService, "verify", lambda *_: SimpleNamespace(passed=True))
    with pytest.raises(SystemExit, match="empty"):
        operations.main(["restore", "snapshot"])
    assert (data / "keep").read_text() == "unchanged"


def test_failed_audit_blocks_snapshot_creation(monkeypatch, tmp_path):
    setup_ops(monkeypatch, tmp_path)
    monkeypatch.setattr(operations.AuditService, "run", lambda *_: SimpleNamespace(passed=False))
    monkeypatch.setattr(operations.BackupService, "create", lambda *_: pytest.fail("must not create snapshot"))
    with pytest.raises(SystemExit, match="audit failed"):
        operations.main(["backup"])


@pytest.fixture
def real_snapshot(tmp_path, monkeypatch):
    source_settings = Settings(data_root=tmp_path / "source")
    app = ImportService(source_settings)
    service = BackupService(app.database, source_settings)
    snapshot = tmp_path / "backups/snapshot"
    service.create(snapshot)
    data = tmp_path / "restore"
    data.mkdir()
    settings = Settings(data_root=data)
    monkeypatch.setattr(operations.Settings, "from_environment", lambda: settings)
    monkeypatch.setattr(operations.os.path, "ismount", lambda _: True)
    monkeypatch.setattr(operations, "Path", lambda value: snapshot.parent if value == "/backups" else Path(value))
    yield snapshot, data, service
    app.database.engine.dispose()


@pytest.mark.parametrize("relative", ["api-secret.key", "nested/api-secret.key"])
def test_verified_manifest_cannot_import_a_signing_key(real_snapshot, relative):
    snapshot, data, service = real_snapshot
    key = snapshot / relative
    key.parent.mkdir(exist_ok=True)
    key.write_bytes(b"disposable old signing key")
    path = snapshot / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["files"].append({"relative_path": relative, "size": key.stat().st_size,
                              "sha256": hashlib.sha256(key.read_bytes()).hexdigest()})
    path.write_text(json.dumps(manifest))
    assert service.verify(snapshot).passed  # The application manifest alone isn't this guard.
    with pytest.raises(SystemExit, match="unsafe"):
        operations.main(["restore", snapshot.name])
    assert list(data.iterdir()) == []
    assert key.read_bytes() == b"disposable old signing key"


@pytest.mark.skipif(os.name == "nt", reason="Linux container link semantics")
@pytest.mark.parametrize("kind", ["directory-link", "file-link", "broken-link", "hardlink", "fifo"])
def test_unsafe_snapshot_entries_are_rejected_before_destination_writes(real_snapshot, kind):
    snapshot, data, _ = real_snapshot
    outside = snapshot.parent / "outside"
    outside.mkdir()
    marker = outside / "marker"
    marker.write_text("outside snapshot")
    extra = snapshot / "unsafe"
    if kind == "directory-link":
        extra.symlink_to(outside, target_is_directory=True)
    elif kind == "file-link":
        extra.symlink_to(marker)
    elif kind == "broken-link":
        extra.symlink_to(outside / "absent")
    elif kind == "hardlink":
        os.link(marker, extra)
    else:
        os.mkfifo(extra)
    with pytest.raises(SystemExit, match="unsafe"):
        operations.main(["restore", snapshot.name])
    assert list(data.iterdir()) == []
    assert marker.read_text() == "outside snapshot"


def test_interrupted_restore_is_marked_and_never_reports_success(real_snapshot, monkeypatch):
    snapshot, data, _ = real_snapshot
    def interrupted(*_):
        raise RuntimeError("copy interrupted")
    monkeypatch.setattr(operations, "copy_snapshot", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        operations.main(["restore", snapshot.name])
    assert (data / ".restore-incomplete").is_file()
    assert not (data / "api-secret.key").exists()


@pytest.mark.skipif(os.name == "nt", reason="Linux descriptor-relative copy")
def test_directory_substitution_cannot_be_followed_during_copy(tmp_path):
    source, outside, target = (tmp_path / name for name in ("source", "outside", "target"))
    for root in (source, outside, target):
        root.mkdir()
    (outside / "private-marker").write_text("not a backup")
    (source / "redirect").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="Unsupported"):
        operations.copy_snapshot(source, target)
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("limit", ["count", "bytes", "free"])
def test_snapshot_admission_limits_fail_without_removing_anything(tmp_path, monkeypatch, limit):
    snapshot = tmp_path / "retained"
    snapshot.mkdir()
    (snapshot / "payload").write_bytes(b"preserve")
    if limit == "count":
        monkeypatch.setattr(operations, "MAX_SNAPSHOTS", 1)
    elif limit == "bytes":
        monkeypatch.setattr(operations, "MAX_BACKUP_BYTES", 1)
    else:
        monkeypatch.setattr(operations.shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
    with pytest.raises(SystemExit, match="capacity"):
        operations.check_backup_capacity(tmp_path)
    assert (snapshot / "payload").read_bytes() == b"preserve"


def test_snapshot_inventory_is_read_only_and_counts_partial_entries(tmp_path):
    (tmp_path / "partial").write_bytes(b"partial")
    result = operations.inventory(tmp_path)
    assert result["count"] == 1 and result["total_bytes"] == 7
    assert result["snapshots"] == [{"name": "partial", "bytes": 7}]
    assert (tmp_path / "partial").read_bytes() == b"partial"


def test_capacity_refusal_precedes_snapshot_creation(real_snapshot, monkeypatch):
    snapshot, data, _ = real_snapshot
    manifest = (snapshot / "manifest.json").read_bytes()
    monkeypatch.setattr(operations, "MAX_SNAPSHOTS", 1)
    monkeypatch.setattr(operations.AuditService, "run", lambda _: SimpleNamespace(passed=True))
    monkeypatch.setattr(operations.BackupService, "create", lambda *_: pytest.fail("must not create another snapshot"))
    with pytest.raises(SystemExit, match="capacity"):
        operations.main(["backup"])
    assert (snapshot / "manifest.json").read_bytes() == manifest
    assert list(data.iterdir()) == []
