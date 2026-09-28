from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from family_finance.audit import AuditService
from family_finance.automation import AutomationService
from family_finance.backup import BackupService
from family_finance.config import Settings
from family_finance.models import ImportStatus
from family_finance.persistence.models import (
    AutomationFileOutcomeRow,
    AutomationRunRow,
    ImportBatchRow,
    SourceFileRow,
    TransactionRow,
)
from family_finance.services import ImportService


def _attention_database_snapshot(database):
    tables = (
        AutomationRunRow.__table__,
        AutomationFileOutcomeRow.__table__,
        ImportBatchRow.__table__,
        SourceFileRow.__table__,
        TransactionRow.__table__,
    )
    with database.engine.connect() as connection:
        return {
            table.name: tuple(
                tuple(row)
                for row in connection.execute(
                    table.select().order_by(*table.primary_key.columns)
                ).all()
            )
            for table in tables
        }


def _attention_file(settings):
    path = settings.automation_needs_review_root / "pending.xlsx"
    path.write_bytes(b"attention workbook bytes")
    return path


def test_reviewing_attention_file_keeps_future_audits_passing(tmp_path):
    settings = Settings(
        data_root=tmp_path / "local",
        automation_backup_root=tmp_path / "automation-backups",
    )
    app = ImportService(settings)

    class ReviewImportService:
        insights_service = app.insights_service

        @staticmethod
        def preflight_import(_payload, _filename):
            return SimpleNamespace(
                action="needs_review", duplicate_file=False, preview_token="token"
            )

        @staticmethod
        def commit_import(_payload, _token, _filename):
            backups = list(settings.automation_backup_root.iterdir())
            assert len(backups) == 1
            assert BackupService(app.database, settings).verify(backups[0]).passed
            return SimpleNamespace(status=ImportStatus.NEEDS_REVIEW, batch_id=None)

    automation = AutomationService(
        settings=settings,
        database=app.database,
        import_service=ReviewImportService(),
    )
    source = settings.automation_inbox_root / "review.xlsx"
    payload = b"reviewable workbook bytes"
    source.write_bytes(payload)
    automation._insert_run("run-id", datetime.now(UTC), False)
    outcome = automation._move_attention(
        source,
        "AMBIGUOUS_MATCH",
        hashlib.sha256(payload).hexdigest(),
        len(payload),
    )
    automation._finish(
        "run-id",
        datetime.now(UTC),
        "completed_with_warnings",
        False,
        True,
        None,
        [outcome],
        {"needs_review": 1},
        ["AMBIGUOUS_MATCH"],
    )

    attention_path = next(settings.automation_needs_review_root.rglob("review.xlsx"))
    result = automation.commit_attention(attention_path)

    assert result.status == ImportStatus.NEEDS_REVIEW
    assert AuditService(app.database, settings).run().passed
    with app.database.session() as session:
        stored = session.query(AutomationFileOutcomeRow).one()
    assert stored.managed_path == str(
        next(settings.automation_processed_root.rglob("review.xlsx"))
    )


def test_attention_commit_without_backup_configuration_leaves_file_and_database_untouched(tmp_path):
    settings = Settings(data_root=tmp_path / "local")
    app = ImportService(settings)
    attention_path = _attention_file(settings)
    before = _attention_database_snapshot(app.database)
    automation = AutomationService(settings=settings, database=app.database, import_service=app)

    with pytest.raises(RuntimeError, match="no backup destination is configured"):
        automation.commit_attention(attention_path)

    assert attention_path.read_bytes() == b"attention workbook bytes"
    assert _attention_database_snapshot(app.database) == before


def test_attention_commit_audit_failure_leaves_file_and_database_untouched(
    tmp_path, monkeypatch
):
    settings = Settings(
        data_root=tmp_path / "local",
        automation_backup_root=tmp_path / "automation-backups",
    )
    app = ImportService(settings)
    attention_path = _attention_file(settings)
    before = _attention_database_snapshot(app.database)
    monkeypatch.setattr(AuditService, "run", lambda _service: SimpleNamespace(passed=False))
    automation = AutomationService(settings=settings, database=app.database, import_service=app)

    with pytest.raises(RuntimeError, match="database/archive audit failed"):
        automation.commit_attention(attention_path)

    assert attention_path.read_bytes() == b"attention workbook bytes"
    assert not settings.automation_backup_root.exists()
    assert _attention_database_snapshot(app.database) == before


def test_attention_commit_backup_creation_failure_leaves_file_and_database_untouched(
    tmp_path, monkeypatch
):
    settings = Settings(
        data_root=tmp_path / "local",
        automation_backup_root=tmp_path / "automation-backups",
    )
    app = ImportService(settings)
    attention_path = _attention_file(settings)
    before = _attention_database_snapshot(app.database)

    def fail_create(_service, _destination):
        raise OSError("backup disk unavailable")

    monkeypatch.setattr(BackupService, "create", fail_create)
    automation = AutomationService(settings=settings, database=app.database, import_service=app)

    with pytest.raises(RuntimeError, match="fresh pre-commit backup"):
        automation.commit_attention(attention_path)

    assert attention_path.read_bytes() == b"attention workbook bytes"
    assert _attention_database_snapshot(app.database) == before


def test_attention_commit_backup_verification_failure_leaves_file_and_database_untouched(
    tmp_path, monkeypatch
):
    settings = Settings(
        data_root=tmp_path / "local",
        automation_backup_root=tmp_path / "automation-backups",
    )
    app = ImportService(settings)
    attention_path = _attention_file(settings)
    before = _attention_database_snapshot(app.database)
    monkeypatch.setattr(
        BackupService, "verify", lambda _service, _directory: SimpleNamespace(passed=False)
    )
    automation = AutomationService(settings=settings, database=app.database, import_service=app)

    with pytest.raises(RuntimeError, match="fresh pre-commit backup"):
        automation.commit_attention(attention_path)

    assert attention_path.read_bytes() == b"attention workbook bytes"
    assert _attention_database_snapshot(app.database) == before


def test_verified_backup_copies_unstable_managed_files_without_hash(tmp_path):
    settings = Settings(
        data_root=tmp_path / "local",
        automation_backup_root=tmp_path / "automation-backups",
    )
    app = ImportService(settings)
    automation = AutomationService(
        settings=settings, database=app.database, import_service=app
    )
    automation._is_stable = lambda _path: False
    (settings.automation_inbox_root / "unstable.xlsx").write_bytes(b"still copying")

    result = automation.run()

    assert result.files[0].reason_code == "UNSTABLE_FILE"
    backup_root = tmp_path / "verified-backup"
    BackupService(app.database, settings).create(backup_root)
    verification = BackupService(app.database, settings).verify(backup_root)
    assert verification.passed
    assert any(
        path.as_posix().startswith("automation/needs-review/")
        for path in (
            item.relative_to(backup_root)
            for item in backup_root.rglob("*")
            if item.is_file()
        )
    )


def test_reviewable_file_does_not_suppress_insight_refresh(tmp_path, monkeypatch):
    settings = Settings(
        data_root=tmp_path / "local",
        automation_backup_root=tmp_path / "automation-backups",
    )
    app = ImportService(settings)
    refreshed: list[str] = []
    monkeypatch.setattr(
        app.insights_service,
        "reconcile_alerts",
        lambda: refreshed.append("alerts"),
    )
    monkeypatch.setattr(
        app.insights_service,
        "generate_previous_month_summary",
        lambda: refreshed.append("summary"),
    )
    (settings.automation_inbox_root / "invalid.xlsx").write_bytes(b"not a workbook")

    result = AutomationService(
        settings=settings, database=app.database, import_service=app
    ).run()

    assert result.status == "completed_with_warnings"
    assert refreshed == ["alerts", "summary"]


def test_inbox_processing_fails_closed_when_backup_is_not_configured(tmp_path):
    settings = Settings(data_root=tmp_path / "local")
    app = ImportService(settings)
    inbox_file = settings.automation_inbox_root / "invalid.xlsx"
    inbox_file.write_bytes(b"not a workbook")

    result = AutomationService(
        settings=settings, database=app.database, import_service=app
    ).run()

    assert result.status == "blocked_backup"
    assert result.issue_codes == ["AUTOMATION_BACKUP_NOT_CONFIGURED"]
    assert inbox_file.is_file()
    with app.database.session() as session:
        assert session.query(AutomationRunRow).one().status == "blocked_backup"
        assert session.query(AutomationFileOutcomeRow).count() == 0


def test_failed_per_run_backup_blocks_before_financial_or_file_mutation(tmp_path, monkeypatch):
    settings = Settings(
        data_root=tmp_path / "local",
        automation_backup_root=tmp_path / "automation-backups",
    )
    app = ImportService(settings)
    inbox_file = settings.automation_inbox_root / "invalid.xlsx"
    inbox_file.write_bytes(b"not a workbook")
    automation = AutomationService(settings=settings, database=app.database, import_service=app)
    def fail_backup():
        raise OSError("disk error")

    monkeypatch.setattr(automation, "_create_backup", fail_backup)

    result = automation.run()

    assert result.status == "blocked_backup"
    assert result.issue_codes == ["AUTOMATION_BACKUP_FAILED"]
    assert inbox_file.is_file()
    with app.database.session() as session:
        assert session.query(AutomationRunRow).one().status == "blocked_backup"
        assert session.query(AutomationFileOutcomeRow).count() == 0
        assert session.query(TransactionRow).count() == 0


def test_dry_run_does_not_persist_automation_records(tmp_path):
    settings = Settings(data_root=tmp_path / "local")
    app = ImportService(settings)
    inbox_file = settings.automation_inbox_root / "invalid.xlsx"
    inbox_file.write_bytes(b"not a workbook")

    result = AutomationService(
        settings=settings, database=app.database, import_service=app
    ).run(dry_run=True)

    assert result.status == "dry_run"
    assert result.files[0].status == "invalid"
    assert inbox_file.is_file()
    with app.database.session() as session:
        assert session.query(AutomationRunRow).count() == 0
        assert session.query(AutomationFileOutcomeRow).count() == 0
