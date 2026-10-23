"""Maintenance guards: failures must precede any restore write."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

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
