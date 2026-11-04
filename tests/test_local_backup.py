"""Local backup retention and daily scheduling must not discard the last good copy."""
import importlib
import json
import sys
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/docker"))
local = importlib.import_module("local_backup")
OWNER = "a" * 32
IMAGE = "sha256:" + "b" * 64


def make_archive(directory, index, *, owner=OWNER):
    name = f"familyfin-202611{index:02d}T030000Z-{'c' * 32}.tar"
    archive = directory / name
    archive.write_bytes(f"verified archive {index}".encode())
    receipt = {"format": 1, "owner": owner, "archive": name,
               "sha256": local.portable.digest(archive), "image": IMAGE,
               "status": "PASS", "last_success_at": datetime.now(UTC).isoformat()}
    local.portable.save_json(directory / (name + ".receipt.json"), receipt)
    return archive, receipt


@pytest.fixture
def configured(tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir()
    config = {"format": 1, "project": "familyfin-m1-synthetic", "image": IMAGE,
              "container_image": IMAGE, "media_token": OWNER, "directory": str(directory)}
    (directory / ".familyfin-local.json").write_text(json.dumps({"format": 1, "owner": OWNER}))
    config_path = tmp_path / "config.json"
    local.portable.save_json(config_path, config)
    return config_path, config, directory


def test_retention_keeps_seven_newest_and_preserves_unrelated_files(tmp_path):
    archives = [make_archive(tmp_path, i)[0] for i in range(1, 10)]
    unrelated, _ = make_archive(tmp_path, 10, owner="d" * 32)
    canary = tmp_path / "family-notes.txt"
    canary.write_text("preserve")
    partial = tmp_path / "unfinished.tar.partial"
    partial.write_text("preserve")
    assert len(local.prune(tmp_path, OWNER)) == 2
    assert [p.exists() for p in archives] == [False, False] + [True] * 7
    assert unrelated.exists() and canary.read_text() == partial.read_text() == "preserve"


def test_tampered_archive_and_malformed_receipt_are_never_pruned(tmp_path):
    archive, _ = make_archive(tmp_path, 1)
    archive.write_bytes(b"changed outside the backup tool")
    malformed = tmp_path / ("familyfin-20261101T030000Z-" + "e" * 32 + ".tar.receipt.json")
    malformed.write_text("[]")
    for index in range(2, 10):
        make_archive(tmp_path, index)
    local.prune(tmp_path, OWNER)
    assert archive.read_bytes() == b"changed outside the backup tool"
    assert malformed.read_text() == "[]"


def test_ownership_marker_mismatch_is_rejected(configured):
    path, _, directory = configured
    (directory / ".familyfin-local.json").write_text(json.dumps({"format": 1, "owner": "other"}))
    with pytest.raises(ValueError, match="ownership"):
        local.read_config(path)


def test_receipt_path_cannot_escape_backup_directory(tmp_path):
    path = tmp_path / ("familyfin-20261101T030000Z-" + "c" * 32 + ".tar.receipt.json")
    path.write_text(json.dumps({"format": 1, "owner": OWNER, "archive": "../outside"}))
    with pytest.raises(ValueError):
        local.checked_receipt(tmp_path, path, OWNER)


def test_same_day_valid_backup_skips_without_docker_or_new_snapshot(configured, monkeypatch, capsys):
    path, _, directory = configured
    _, receipt = make_archive(directory, 1)
    local.portable.save_json(path.parent / "local-last-run.json", receipt)
    monkeypatch.setattr(local.portable, "lock", lambda _: nullcontext())
    monkeypatch.setattr(local, "create_backup", lambda _: pytest.fail("must not create another snapshot"))
    monkeypatch.setattr(local.backup_readiness, "wait_ready", lambda _: pytest.fail("must not wait"))
    assert local.main(["run", "--config", str(path), "--if-due", "--wait-ready"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "SKIPPED"


@pytest.mark.parametrize("change", ["missing", "tampered"])
def test_same_day_missing_or_changed_copy_creates_backup(configured, monkeypatch, change):
    path, _, directory = configured
    archive, receipt = make_archive(directory, 1)
    local.portable.save_json(path.parent / "local-last-run.json", receipt)
    if change == "missing":
        archive.unlink()
    else:
        archive.write_bytes(b"tampered")
    calls = []
    monkeypatch.setattr(local.portable, "lock", lambda _: nullcontext())
    monkeypatch.setattr(local, "create_backup", lambda config: calls.append(config) or receipt)
    assert local.main(["run", "--config", str(path), "--if-due"]) == 0
    assert len(calls) == 1


def test_failed_backup_keeps_all_existing_archives_and_success_timestamp(configured, monkeypatch):
    path, _, directory = configured
    archives = [make_archive(directory, i)[0] for i in range(1, 9)]
    _, receipt = make_archive(directory, 9)
    local.portable.save_json(path.parent / "local-last-run.json", receipt)
    monkeypatch.setattr(local.portable, "lock", lambda _: nullcontext())

    def fail(_):
        raise RuntimeError("disposable failure")

    monkeypatch.setattr(local, "create_backup", fail)
    assert local.main(["run", "--config", str(path)]) == 1
    state = json.loads((path.parent / "local-last-run.json").read_text())
    assert state["status"] == "FAIL"
    assert state["last_success_at"] == receipt["last_success_at"]
    assert all(p.exists() for p in archives)


def test_daily_state_is_reloaded_after_process_lock(configured, monkeypatch, capsys):
    path, _, directory = configured
    _, receipt = make_archive(directory, 1)

    @contextmanager
    def locked(_):
        local.portable.save_json(path.parent / "local-last-run.json", receipt)
        yield

    monkeypatch.setattr(local.portable, "lock", locked)
    monkeypatch.setattr(local, "create_backup", lambda _: pytest.fail("newer state must suppress duplicate"))
    assert local.main(["run", "--config", str(path), "--if-due"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "SKIPPED"


def test_export_failure_never_publishes_or_prunes(configured, monkeypatch):
    _, config, directory = configured
    archives = [make_archive(directory, i)[0] for i in range(1, 9)]
    monkeypatch.setattr(local, "source", lambda _: None)
    monkeypatch.setattr(local, "scratch", lambda _: nullcontext("scratch"))
    monkeypatch.setattr(local.portable, "call", lambda _: ("familyfin-" + "f" * 32).encode())
    monkeypatch.setattr(local, "stream", lambda *a, **kw: ["export"])
    monkeypatch.setattr(local.subprocess, "run", lambda *a, **kw: type("Failed", (), {"returncode": 1})())
    monkeypatch.setattr(local, "prune", lambda *a: pytest.fail("must preserve retention on failure"))
    with pytest.raises(RuntimeError, match="export"):
        local.create_backup(config)
    assert all(p.exists() for p in archives)
    assert len(list(directory.glob("*.tar"))) == 8
    assert not list(directory.glob("*.partial"))


def test_changed_source_image_is_rejected_before_volume_use(configured, monkeypatch):
    _, config, _ = configured
    monkeypatch.setattr(local.manage, "engine", lambda: None)
    api = {"Image": "sha256:" + "e" * 64, "Config": {"Labels": {}}, "State": {}}
    monkeypatch.setattr(local.portable, "call", lambda _: json.dumps([api]).encode())
    with pytest.raises(ValueError, match="release"):
        local.source(config)


def test_scratch_cleanup_refuses_a_foreign_volume(configured, monkeypatch):
    _, config, _ = configured
    calls = []

    def call(command):
        calls.append(command)
        return json.dumps([{"Labels": {"familyfin.local.owner": "foreign"}}]).encode()

    monkeypatch.setattr(local.portable, "call", call)
    with pytest.raises(ValueError, match="unrelated"):
        local.remove_volume(config, "familyfin-local-stage-" + "f" * 32)
    assert len(calls) == 1
