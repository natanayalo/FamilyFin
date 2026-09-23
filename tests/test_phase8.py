from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace

from family_finance.audit import AuditService
from family_finance.automation import AutomationService
from family_finance.backup import BackupService
from family_finance.config import Settings
from family_finance.models import ImportStatus
from family_finance.persistence.models import AutomationFileOutcomeRow, AutomationRunRow
from family_finance.services import ImportService


def test_reviewing_attention_file_keeps_future_audits_passing(tmp_path):
    settings = Settings(data_root=tmp_path / "local")
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
    settings = Settings(data_root=tmp_path / "local")
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
