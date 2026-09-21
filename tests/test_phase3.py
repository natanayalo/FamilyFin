from __future__ import annotations

import shutil
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from family_finance.audit import AuditService
from family_finance.backup import BackupService
from family_finance.config import Settings
from family_finance.dashboard import DashboardService
from family_finance.insights import InsightsService
from family_finance.models import DashboardFilters
from family_finance.persistence.db import Database
from family_finance.services import ImportService

from .conftest import make_workbook


def _import(tmp_path: Path, rows: list[list[object]], *, report_end: str = "30/09/2026"):
    settings = Settings(data_root=tmp_path / "local")
    service = ImportService(settings)
    workbook = make_workbook(rows, report_end=report_end)
    preview = service.preview_import(workbook, "phase3.xlsx")
    service.commit_import(workbook, preview.preview_token, "phase3.xlsx")
    return service, settings


def test_dashboard_filters_series_and_contributors(tmp_path):
    service, _ = _import(
        tmp_path,
        [
            ["01/09/2026", 1000, "salary", "01/09/2026", "credit", "salary", "ILS", "ILS", 1000],
            ["02/09/2026", -250, "shop", "02/09/2026", "purchase", "food", "ILS", "ILS", -250],
        ],
    )
    dashboard = DashboardService(service.database)
    filters = DashboardFilters(start_month="2026-08", end_month="2026-09", currency="ils")
    result = dashboard.overview(filters)

    assert [point.month.isoformat() for point in result.series] == ["2026-08-01", "2026-09-01"]
    assert result.selected_month is not None
    assert result.selected_month.metrics.net_consumption == Decimal(250)
    assert result.selected_month.complete is False
    contributors = dashboard.contributors(result.selected_month.metrics.contributors_for("gross_consumption"))
    assert contributors[0].description == "shop"
    assert contributors[0].account_label
    with pytest.raises(ValueError):
        DashboardFilters(start_month="2026-10", end_month="2026-09", currency="ILS")


def test_recurring_and_anomaly_insights_are_deterministic(tmp_path):
    rows = [
        ["01/01/2026", -100, "Monthly merchant", "01/01/2026", "purchase", "food", "ILS", "ILS", -100],
        ["01/02/2026", -100, "Monthly merchant", "01/02/2026", "purchase", "food", "ILS", "ILS", -100],
        ["01/03/2026", -100, "Monthly merchant", "01/03/2026", "purchase", "food", "ILS", "ILS", -100],
    ]
    for month in range(1, 7):
        rows.append([f"15/{month:02d}/2026", -100, f"baseline-{month}", f"15/{month:02d}/2026", "purchase", "food", "ILS", "ILS", -100])
    rows.append(["31/07/2026", -300, "target", "31/07/2026", "purchase", "food", "ILS", "ILS", -300])
    service, _ = _import(tmp_path, rows, report_end="31/07/2026")
    insights = InsightsService(service.database)

    recurring = insights.potential_recurring_spending("2026-01", "2026-03")
    assert len(recurring) == 1
    assert recurring[0].amount_range == (Decimal(100), Decimal(100))
    anomalies = insights.unusual_category_spending("2026-07", "2026-07")
    assert any(item.direction == "high" and item.category == "food" for item in anomalies)
    expenses = DashboardService(service.database).expenses(
        DashboardFilters(start_month="2026-01", end_month="2026-03", currency="ILS")
    )
    assert expenses.potential_recurring_spending


def test_zero_baseline_anomaly_obeys_materiality(tmp_path):
    rows = [
        ["15/01/2026", -1000, "baseline", "15/01/2026", "purchase", "food", "ILS", "ILS", -1000],
        ["15/02/2026", -1000, "baseline", "15/02/2026", "purchase", "food", "ILS", "ILS", -1000],
        ["15/03/2026", -1000, "baseline", "15/03/2026", "purchase", "food", "ILS", "ILS", -1000],
        ["15/04/2026", -1000, "baseline", "15/04/2026", "purchase", "food", "ILS", "ILS", -1000],
        ["15/05/2026", -1000, "baseline", "15/05/2026", "purchase", "food", "ILS", "ILS", -1000],
        ["15/06/2026", -1000, "baseline", "15/06/2026", "purchase", "food", "ILS", "ILS", -1000],
        ["31/07/2026", -1, "new category", "31/07/2026", "purchase", "new", "ILS", "ILS", -1],
    ]
    service, _ = _import(tmp_path, rows, report_end="31/07/2026")
    anomalies = InsightsService(service.database).unusual_category_spending("2026-07", "2026-07")
    assert all(item.category != "new" for item in anomalies)


def test_audit_backup_and_log_privacy(tmp_path):
    service, settings = _import(
        tmp_path,
        [["01/09/2026", -17.40, "private merchant", "01/09/2026", "purchase", "food", "ILS", "ILS", -17.40]],
    )
    assert AuditService(database=service.database, settings=settings).run().passed
    log_text = settings.log_path.read_text(encoding="utf-8")
    backup = BackupService(database=service.database, settings=settings)
    manifest = backup.create(tmp_path / "backup")
    assert backup.verify(tmp_path / "backup").passed
    restored = tmp_path / "restored"
    restored.mkdir()
    shutil.copy2(tmp_path / "backup" / "family_finance.sqlite3", restored / "family_finance.sqlite3")
    shutil.copytree(tmp_path / "backup" / "imports", restored / "imports")
    shutil.rmtree(settings.data_root)
    restored_settings = Settings(data_root=restored)
    restored_database = Database(restored_settings.database_path)
    assert AuditService(database=restored_database, settings=restored_settings).run().passed
    restored_backup = BackupService(database=restored_database, settings=restored_settings)
    assert restored_backup.create(tmp_path / "second-backup").schema_revision
    database_path = tmp_path / "backup" / service.database.path.name
    database_path.write_bytes(b"malformed sqlite")
    corrupt_result = restored_backup.verify(tmp_path / "backup")
    assert not corrupt_result.passed
    assert any("SQLITE" in code for check in corrupt_result.checks for code in check.issue_codes)
    assert "private merchant" not in log_text
    assert "17.40" not in log_text
    assert manifest.schema_revision


def test_audit_and_backup_verification_do_not_create_missing_data_roots(tmp_path):
    settings = Settings(data_root=tmp_path / "missing-local")
    audit = AuditService(settings=settings).run()
    assert not audit.passed
    assert any("DATABASE_MISSING" in code for check in audit.checks for code in check.issue_codes)
    assert not settings.data_root.exists()

    verification = BackupService(settings=settings).verify(tmp_path / "missing-backup")
    assert not verification.passed
    assert not settings.data_root.exists()
    assert not (tmp_path / "missing-backup").exists()


def test_read_only_audit_sees_committed_wal_frames(tmp_path):
    settings = Settings(data_root=tmp_path / "local")
    database = Database(settings.database_path)
    database.engine.dispose()
    writer = sqlite3.connect(settings.database_path)
    writer.execute("PRAGMA journal_mode = WAL")
    writer.execute("PRAGMA wal_autocheckpoint = 0")
    writer.execute(
        "INSERT INTO accounts (account_kind, provider, source_reference_fingerprint, display_label, currency) "
        "VALUES (?, ?, ?, ?, ?)",
        ("bank", "fixture", "wal-account", "WAL fixture", "ILS"),
    )
    writer.execute(
        "INSERT INTO import_batches (id, parser_version, status, statistics_json, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("wal-batch", "test", "committed", '{"total_records": 0}', "2026-09-21T00:00:00+00:00"),
    )
    writer.execute(
        "INSERT INTO source_records (import_batch_id, account_id, sheet_name, section_index, "
        "source_row_number, raw_payload_json, normalized_json, row_fingerprint, validation_state, issues_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "wal-batch",
            1,
            "fixture",
            0,
            1,
            "{}",
            '{"booking_date":"2026-09-01"}',
            "wal-source",
            "invalid-state",
            "[]",
            "2026-09-21T00:00:00+00:00",
        ),
    )
    writer.commit()
    assert writer.execute("SELECT COUNT(*) FROM source_records").fetchone()[0] == 1

    report = AuditService(settings=settings).run()
    writer.close()

    assert not report.passed
    assert any(
        "UNKNOWN_SOURCE_LIFECYCLE_STATE" in code
        for check in report.checks
        for code in check.issue_codes
    )


def test_empty_dashboard_has_no_observed_zero_activity(tmp_path):
    settings = Settings(data_root=tmp_path / "local")
    database = Database(settings.database_path)
    dashboard = DashboardService(database)
    filters = DashboardFilters(start_month="2026-01", end_month="2026-12", currency="ILS")

    overview = dashboard.overview(filters)
    expenses = dashboard.expenses(filters)
    quality = dashboard.data_quality(filters)

    assert overview.series == []
    assert overview.selected_month is None
    assert overview.headline == {}
    assert expenses.series == []
    assert expenses.selected_month is None
    assert quality.incomplete_months == []
    assert quality.freshness_date is None


def test_insight_contributors_are_drillable(tmp_path):
    service, _ = _import(
        tmp_path,
        [
            ["01/01/2026", -100, "Monthly merchant", "01/01/2026", "purchase", "food", "ILS", "ILS", -100],
            ["01/02/2026", -100, "Monthly merchant", "01/02/2026", "purchase", "food", "ILS", "ILS", -100],
            ["01/03/2026", -100, "Monthly merchant", "01/03/2026", "purchase", "food", "ILS", "ILS", -100],
        ],
    )
    dashboard = DashboardService(service.database)
    result = dashboard.expenses(
        DashboardFilters(start_month="2026-01", end_month="2026-03", currency="ILS")
    )

    insight = result.potential_recurring_spending[0]
    contributors = dashboard.contributors(insight.contributor_transaction_ids)
    assert [item.transaction_id for item in contributors] == insight.contributor_transaction_ids


def test_data_quality_scopes_dates_and_deduplicates_source_issues(tmp_path):
    service, _ = _import(
        tmp_path,
        [
            ["01/09/2026", -10, "ils", "01/09/2026", "purchase", "food", "ILS", "ILS", -10],
            ["01/09/2026", -10, "usd", "01/09/2026", "purchase", "food", "USD", "USD", -10],
            ["01/10/2026", -10, "late usd", "01/10/2026", "purchase", "food", "USD", "USD", -10],
        ],
        report_end="31/10/2026",
    )
    dashboard = DashboardService(service.database)
    september = dashboard.data_quality(
        DashboardFilters(start_month="2026-09", end_month="2026-09", currency="ILS")
    )
    assert september.issue_counts["NON_ILS_CURRENCY"] == 1
    assert september.currencies == {"ILS": 1, "USD": 1}
    assert september.covered_end.isoformat() == "2026-09-01"
