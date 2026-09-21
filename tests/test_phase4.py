from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic.config import Config

from alembic import command
from family_finance.audit import AuditService
from family_finance.backup import BackupService
from family_finance.config import Settings
from family_finance.models import (
    CompletenessAssessment,
    MetricBreakdown,
    MonthlyMetrics,
    PlanningItemInput,
)
from family_finance.planning import StaleRevisionError
from family_finance.services import ImportService

CSV_FIXTURE = Path(__file__).resolve().parents[1] / "data" / "הוצאות בית מעודכן 18_4_26.xlsx - בית כללי.csv"
WORKBOOK_FIXTURE = Path(__file__).resolve().parents[1] / "data" / "familybiz report 21-09-26.xlsx"


def service(tmp_path):
    return ImportService(Settings(data_root=tmp_path / "local"))


def test_manual_revision_edit_stale_restore_clone_and_archive(tmp_path):
    app = service(tmp_path)
    start = date(2026, 10, 1)
    item = PlanningItemInput(
        kind="income",
        label="Salary",
        amount=Decimal("10000.25"),
        frequency="monthly",
        start_month=start,
        end_month=date(2027, 9, 1),
    )
    scenario = app.planning_service.create_manual_scenario("Baseline", start, [item])
    projection = app.planning_service.project_draft(scenario.scenario_id)
    assert projection.months[0].income == Decimal("10000.25")

    edited = PlanningItemInput(
        kind="income",
        label="Salary",
        amount=Decimal("10001.75"),
        frequency="monthly",
        start_month=start,
        end_month=date(2027, 9, 1),
    )
    saved = app.planning_service.save_revision(scenario.scenario_id, 1, [edited], notes="raise")
    assert saved.revision_number == 2
    assert app.planning_service.get_revision(scenario.scenario_id, 1).items[0].amount == Decimal("10000.25")
    with pytest.raises(StaleRevisionError):
        app.planning_service.save_revision(scenario.scenario_id, 1, [item])

    restored = app.planning_service.restore_revision(scenario.scenario_id, 1)
    assert restored.revision_number == 3
    assert restored.items[0].amount == Decimal("10000.25")
    clone = app.planning_service.clone_scenario(scenario.scenario_id)
    assert clone.clone_of_scenario_id == scenario.scenario_id
    archived = app.planning_service.archive_scenario(scenario.scenario_id)
    assert archived.archived is True
    assert len(app.planning_service.list_revisions(scenario.scenario_id)) == 3


def test_historical_seed_persists_provisional_quality_and_snapshot(tmp_path):
    app = service(tmp_path)
    preview = app.planning_service.preview_history_seed(
        start_month=date(2026, 10, 1), history_months=3
    )
    assert preview.provisional is True
    assert len(preview.completeness_snapshot) == 3
    scenario = app.planning_service.commit_history_seed(preview.preview_token)
    revision = app.planning_service.get_revision(scenario.scenario_id)
    projection = app.planning_service.project_draft(scenario.scenario_id)
    assert revision.provisional is True
    assert revision.issue_codes == preview.issue_codes
    assert revision.completeness_snapshot == preview.completeness_snapshot
    assert projection.provisional is True
    assert projection.issue_codes == preview.issue_codes
    draft_item = PlanningItemInput(
        kind="expense",
        label="Draft expense",
        amount=Decimal(25),
        frequency="monthly",
        start_month=date(2026, 10, 1),
        end_month=date(2027, 9, 1),
    )
    draft = app.planning_service.project_draft(
        scenario.scenario_id,
        [draft_item],
        revision_number=1,
    )
    assert draft.provisional is True
    assert draft.issue_codes == preview.issue_codes


def test_csv_seed_counts_mapping_notes_quality_archive_audit_and_backup(tmp_path):
    app = service(tmp_path)
    workbook_bytes = WORKBOOK_FIXTURE.read_bytes()
    import_preview = app.preview_import(workbook_bytes, WORKBOOK_FIXTURE.name)
    app.commit_import(workbook_bytes, import_preview.preview_token, WORKBOOK_FIXTURE.name)
    csv_bytes = CSV_FIXTURE.read_bytes()
    preview = app.planning_service.preview_csv_seed(csv_bytes, CSV_FIXTURE.name)
    assert (preview.expense_target_count, preview.recurring_income_count, preview.savings_summary_count) == (24, 2, 1)
    assert len(preview.expense_notes) == 9
    assert preview.provisional is True
    assert "CSV_EXPENSE_CONTROL_GAP" in preview.issue_codes
    mappings = {
        mapping["csv_category"]: mapping["suggested_analysis_categories"][0]
        for mapping in preview.mappings
        if mapping["exact_match"]
    }
    assert mappings
    scenario = app.planning_service.commit_csv_seed(csv_bytes, preview.preview_token, mappings=mappings)
    revision = app.planning_service.get_revision(scenario.scenario_id)
    assert revision.provisional is True
    assert "CSV_EXPENSE_CONTROL_GAP" in revision.issue_codes
    assert "CSV_CATEGORY_UNMAPPED" in revision.issue_codes
    assert len(revision.expense_notes) == 9
    assert sum(bool(item.notes) for item in revision.items) == 9
    assert sum(item.category is not None for item in revision.items if item.kind.value == "expense") == len(mappings)
    archive = next((tmp_path / "local" / "planning-imports").glob("*"))
    assert archive.read_bytes() == csv_bytes

    audit = AuditService(app.database, app.settings).run()
    assert audit.passed
    backup_dir = tmp_path / "backup"
    manifest = BackupService(app.database, app.settings).create(backup_dir)
    assert manifest.schema_revision
    assert BackupService(app.database, app.settings).verify(backup_dir).passed


def test_csv_quality_recomputed_after_all_expenses_are_mapped(tmp_path):
    app = service(tmp_path)
    workbook_bytes = WORKBOOK_FIXTURE.read_bytes()
    import_preview = app.preview_import(workbook_bytes, WORKBOOK_FIXTURE.name)
    app.commit_import(workbook_bytes, import_preview.preview_token, WORKBOOK_FIXTURE.name)
    csv_bytes = CSV_FIXTURE.read_bytes()
    preview = app.planning_service.preview_csv_seed(csv_bytes, CSV_FIXTURE.name)
    categories = app.planning_service.analysis_categories("ILS")
    assert categories
    mappings = {
        mapping["csv_category"]: mapping["suggested_analysis_categories"][0]
        if mapping["suggested_analysis_categories"]
        else categories[0]
        for mapping in preview.mappings
    }
    scenario = app.planning_service.commit_csv_seed(csv_bytes, preview.preview_token, mappings=mappings)
    revision = app.planning_service.get_revision(scenario.scenario_id)
    assert "CSV_CATEGORY_UNMAPPED" not in revision.issue_codes
    assert all(
        item.category is not None
        for item in revision.items
        if item.kind.value == "expense"
    )


def test_downgrade_preserves_phase4_integrity_constraints(tmp_path):
    database_path = tmp_path / "migration.sqlite3"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0005_planning_quality")
    command.downgrade(config, "0004_budget_planning")

    with sqlite3.connect(database_path) as connection:
        planning_items_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'planning_items'"
        ).fetchone()[0]
        revisions_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'planning_scenario_revisions'"
        ).fetchone()[0]
    assert "kind IN ('income', 'expense', 'savings_contribution', 'savings_withdrawal')" in planning_items_sql
    assert "frequency IN ('monthly', 'one_time')" in planning_items_sql
    assert "CAST(amount AS NUMERIC) >= 0" in planning_items_sql
    assert "frequency = 'monthly'" in planning_items_sql
    assert "revision_number >= 1" in revisions_sql

    command.upgrade(config, "0005_planning_quality")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0005_planning_quality"


def test_actuals_are_unavailable_without_observed_rows_and_unmapped_variance_stays_unavailable(tmp_path):
    app = service(tmp_path)
    start = date(2026, 10, 1)
    item = PlanningItemInput(
        kind="expense",
        label="Unmapped",
        amount=Decimal(100),
        frequency="monthly",
        start_month=start,
        end_month=date(2027, 9, 1),
    )
    scenario = app.planning_service.create_manual_scenario("Actual comparison", start, [item])
    incomplete = CompletenessAssessment(
        source_period_complete=False,
        classification_complete=True,
        complete=False,
        source_coverage="partial",
        issues=["SOURCE_PERIOD_PARTIAL_OR_UNKNOWN"],
    )
    metrics = MonthlyMetrics(
        month=start,
        currency="ILS",
        classification_policy_version="test",
        source_period_completeness=incomplete,
        completeness=incomplete,
        spending_by_category={"Unmapped": Decimal(50)},
        breakdowns={
            "spending_by_category:Unmapped": MetricBreakdown(
                name="spending_by_category:Unmapped",
                value=Decimal(50),
                contributor_transaction_ids=[1],
            )
        },
    )
    with patch.object(app.planning_service.metrics, "calculate_monthly_metrics", return_value=metrics), patch.object(
        app.planning_service.metrics.repository, "accepted_transactions", return_value=[]
    ):
        comparison = app.planning_service.compare_actual(scenario.scenario_id)
    first = comparison.months[0]
    assert first.actual_income is None
    assert first.actual_expenses is None
    assert first.actual_surplus is None
    assert first.actual_net_savings is None
    assert first.expense_variances is None
    assert first.category_variance_unavailable == ["Unmapped"]


def test_streamlit_app_smoke_boots_with_phase4_schema(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("FAMILY_FINANCE_DATA_ROOT", str(tmp_path / "ui-local"))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "streamlit_app.py"))
    app.run(timeout=30)
    assert not app.exception
