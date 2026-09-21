import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from family_finance.audit import AuditService
from family_finance.backup import BackupService
from family_finance.config import Settings
from family_finance.forecasting import (
    ForecastValidationError,
    StaleForecastRevisionError,
    _round_return,
    effective_monthly_rate,
)
from family_finance.models import (
    ForecastAdjustmentInput,
    ForecastAdjustmentOperation,
    ForecastCaseInput,
    ForecastEventInput,
    ForecastEventType,
    ForecastPoolInput,
    ForecastRole,
    ForecastRoutingInput,
    ForecastTargetType,
    PlanningFrequency,
    PlanningItemInput,
    PlanningItemKind,
)
from family_finance.services import ImportService


def _app(tmp_path, items):
    app = ImportService(Settings(data_root=tmp_path / "local"))
    scenario = app.planning_service.create_manual_scenario("Forecast plan", date(2026, 1, 1), items)
    revision = app.planning_service.get_revision(scenario.scenario_id)
    return app, scenario, revision


def _cases(revision, *, sweep=False, adjustment=None):
    savings = [
        item
        for item in revision.items
        if item.kind in {PlanningItemKind.SAVINGS_CONTRIBUTION, PlanningItemKind.SAVINGS_WITHDRAWAL}
    ]
    return [
        ForecastCaseInput(
            role=role,
            annual_return_rate=Decimal(0),
            routes=[ForecastRoutingInput(source_item_id=item.id, pool_name="Cash") for item in savings],
            sweep_enabled=sweep,
            sweep_pool_name="Cash" if sweep else None,
            adjustments=[adjustment] if adjustment else [],
            confirmed=True,
        )
        for role in ForecastRole
    ]


def test_forecast_rolls_month_12_schedules_and_slices_one_projection(tmp_path):
    items = [
        PlanningItemInput(
            kind=PlanningItemKind.INCOME,
            label="Salary",
            amount=Decimal(100),
            frequency=PlanningFrequency.MONTHLY,
            start_month=date(2026, 1, 1),
            end_month=date(2026, 12, 1),
        ),
        PlanningItemInput(
            kind=PlanningItemKind.SAVINGS_CONTRIBUTION,
            label="Save",
            amount=Decimal(10),
            frequency=PlanningFrequency.MONTHLY,
            start_month=date(2026, 1, 1),
            end_month=date(2026, 12, 1),
        ),
    ]
    app, scenario, revision = _app(tmp_path, items)
    draft = app.savings_forecast_service.project_draft(
        scenario.scenario_id,
        [ForecastPoolInput(name="Cash", pool_type="cash", opening_balance=Decimal(0), as_of_date=date(2026, 1, 1))],
        _cases(revision, sweep=True),
    )
    result = draft[ForecastRole.BASELINE]
    assert len(result.months) == 36
    assert result.months[0].pools[0].opening_balance == Decimal(0)
    assert result.months[1].pools[0].opening_balance == result.months[0].pools[0].closing_balance
    assert result.months[11].ending_balance == Decimal(1200)
    assert result.months[35].ending_balance == Decimal(3600)
    assert [item.horizon_month for item in draft.comparison.checkpoints[ForecastRole.BASELINE]] == [12, 24, 36]
    assert effective_monthly_rate(Decimal("0.12")) > Decimal("0.009")


def test_partial_withdrawal_reports_gap_and_does_not_draw_against_savings(tmp_path):
    item = PlanningItemInput(
        kind=PlanningItemKind.SAVINGS_WITHDRAWAL,
        label="Emergency withdrawal",
        amount=Decimal(150),
        frequency=PlanningFrequency.MONTHLY,
        start_month=date(2026, 1, 1),
        end_month=date(2026, 1, 1),
    )
    app, scenario, revision = _app(tmp_path, [item])
    result = app.savings_forecast_service.project_draft(
        scenario.scenario_id,
        [ForecastPoolInput(name="Cash", pool_type="cash", opening_balance=Decimal(100), as_of_date=date(2026, 1, 1))],
        _cases(revision),
    )[ForecastRole.BASELINE]
    assert result.months[0].fulfilled_withdrawals == Decimal(100)
    assert result.months[0].unmet_funding_gap == Decimal(50)
    assert result.first_shortfall_month == 1
    assert result.months[0].cash_before_sweep == Decimal(100)
    assert result.months[1].fulfilled_withdrawals == Decimal(0)


def test_adjustment_overlap_and_negative_result_are_rejected(tmp_path):
    item = PlanningItemInput(
        kind=PlanningItemKind.INCOME,
        label="Salary",
        amount=Decimal(100),
        frequency=PlanningFrequency.MONTHLY,
        start_month=date(2026, 1, 1),
        end_month=date(2026, 12, 1),
        category="salary",
    )
    app, scenario, revision = _app(tmp_path, [item])
    line_id = revision.items[0].id
    negative = ForecastAdjustmentInput(
        target_type=ForecastTargetType.LINE,
        target=line_id,
        operation=ForecastAdjustmentOperation.FIXED_DELTA,
        value=Decimal(-101),
        start_month=1,
    )
    with pytest.raises(ForecastValidationError):
        app.savings_forecast_service.project_draft(
            scenario.scenario_id,
            [ForecastPoolInput(name="Cash", pool_type="cash", opening_balance=Decimal(0), as_of_date=date(2026, 1, 1))],
            _cases(revision, adjustment=negative),
        )
    overlap = ForecastAdjustmentInput(
        target_type=ForecastTargetType.LINE,
        target=line_id,
        operation=ForecastAdjustmentOperation.REPLACEMENT,
        value=Decimal(110),
        start_month=1,
    )
    with pytest.raises(ForecastValidationError):
        app.savings_forecast_service.project_draft(
            scenario.scenario_id,
            [ForecastPoolInput(name="Cash", pool_type="cash", opening_balance=Decimal(0), as_of_date=date(2026, 1, 1))],
            [case.model_copy(update={"adjustments": [overlap, overlap]}) for case in _cases(revision)],
        )


def test_forecast_revision_is_append_only_and_optimistic(tmp_path):
    item = PlanningItemInput(
        kind=PlanningItemKind.INCOME,
        label="Salary",
        amount=Decimal(100),
        frequency=PlanningFrequency.MONTHLY,
        start_month=date(2026, 1, 1),
        end_month=date(2026, 12, 1),
    )
    app, scenario, revision = _app(tmp_path, [item])
    pool = ForecastPoolInput(name="Cash", pool_type="cash", opening_balance=Decimal(0), as_of_date=date(2026, 1, 1))
    forecast = app.savings_forecast_service.create_forecast("F", scenario.scenario_id, [pool], _cases(revision))
    saved = app.savings_forecast_service.save_revision(
        forecast.forecast_id,
        expected_revision_number=1,
        starting_pools=[pool],
        cases=_cases(revision),
    )
    assert saved.revision_number == 2
    with pytest.raises(StaleForecastRevisionError):
        app.savings_forecast_service.save_revision(
            forecast.forecast_id,
            expected_revision_number=1,
            starting_pools=[pool],
            cases=_cases(revision),
        )


def test_one_time_events_and_positive_only_sweep_are_ordered_by_month(tmp_path):
    items = [
        PlanningItemInput(
            kind=PlanningItemKind.INCOME,
            label="Salary",
            amount=Decimal(100),
            frequency=PlanningFrequency.MONTHLY,
            start_month=date(2026, 1, 1),
            end_month=date(2026, 12, 1),
        ),
        PlanningItemInput(
            kind=PlanningItemKind.EXPENSE,
            label="Rent",
            amount=Decimal(40),
            frequency=PlanningFrequency.MONTHLY,
            start_month=date(2026, 1, 1),
            end_month=date(2026, 12, 1),
        ),
        PlanningItemInput(
            kind=PlanningItemKind.SAVINGS_CONTRIBUTION,
            label="Save",
            amount=Decimal(10),
            frequency=PlanningFrequency.MONTHLY,
            start_month=date(2026, 1, 1),
            end_month=date(2026, 12, 1),
        ),
    ]
    app, scenario, revision = _app(tmp_path, items)
    events = [
        ForecastEventInput(event_type=ForecastEventType.INCOME, month=2, amount=Decimal(25)),
        ForecastEventInput(event_type=ForecastEventType.EXPENSE, month=3, amount=Decimal(150)),
    ]
    cases = [case.model_copy(update={"events": events}) for case in _cases(revision, sweep=True)]
    months = app.savings_forecast_service.project_draft(
        scenario.scenario_id,
        [ForecastPoolInput(name="Cash", pool_type="cash", opening_balance=0, as_of_date=date(2026, 1, 1))],
        cases,
    )[ForecastRole.BASELINE].months
    assert months[0].swept_surplus == Decimal(50)
    assert months[1].income == Decimal(125)
    assert months[1].swept_surplus == Decimal(75)
    assert months[2].expenses == Decimal(190)
    assert months[2].cash_before_sweep == Decimal(-100)
    assert months[2].swept_surplus == Decimal(0)


def test_all_adjustment_operations_are_supported_without_overlapping_months(tmp_path):
    item = PlanningItemInput(
        kind=PlanningItemKind.INCOME,
        label="Salary",
        amount=Decimal(100),
        frequency=PlanningFrequency.MONTHLY,
        start_month=date(2026, 1, 1),
        end_month=date(2026, 12, 1),
        category="salary",
    )
    app, scenario, revision = _app(tmp_path, [item])
    line_id = revision.items[0].id
    adjustments = [
        ForecastAdjustmentInput(
            target_type=ForecastTargetType.LINE,
            target=line_id,
            operation=ForecastAdjustmentOperation.REPLACEMENT,
            value=Decimal(80),
            start_month=1,
            end_month=1,
        ),
        ForecastAdjustmentInput(
            target_type=ForecastTargetType.CATEGORY,
            target="salary",
            operation=ForecastAdjustmentOperation.FIXED_DELTA,
            value=Decimal(10),
            start_month=2,
            end_month=2,
        ),
        ForecastAdjustmentInput(
            target_type=ForecastTargetType.CATEGORY,
            target="salary",
            operation=ForecastAdjustmentOperation.PERCENTAGE_CHANGE,
            value=Decimal("0.10"),
            start_month=3,
            end_month=3,
        ),
    ]
    cases = [case.model_copy(update={"adjustments": adjustments}) for case in _cases(revision)]
    months = app.savings_forecast_service.project_draft(
        scenario.scenario_id,
        [ForecastPoolInput(name="Cash", pool_type="cash", opening_balance=0, as_of_date=date(2026, 1, 1))],
        cases,
    )[ForecastRole.BASELINE].months
    assert [months[index].income for index in range(3)] == [Decimal(80), Decimal(110), Decimal(110)]


def test_return_rounding_and_zero_floor_are_deterministic(tmp_path):
    items = [
        PlanningItemInput(
            kind=PlanningItemKind.INCOME,
            label="Income",
            amount=Decimal(0),
            frequency=PlanningFrequency.MONTHLY,
            start_month=date(2026, 1, 1),
            end_month=date(2026, 12, 1),
        )
    ]
    app, scenario, revision = _app(tmp_path, items)
    pools = [
        ForecastPoolInput(name="One", pool_type="cash", opening_balance=Decimal("1.00"), as_of_date=date(2026, 1, 1)),
        ForecastPoolInput(name="Three", pool_type="cash", opening_balance=Decimal("3.00"), as_of_date=date(2026, 1, 1)),
    ]
    cases = [case.model_copy(update={"annual_return_rate": Decimal("0.061678")}) for case in _cases(revision)]
    months = app.savings_forecast_service.project_draft(scenario.scenario_id, pools, cases)[ForecastRole.BASELINE].months
    assert _round_return(Decimal("0.005")) == Decimal("0.00")
    assert months[0].pools[0].estimated_return == Decimal("0.01")
    assert months[0].pools[1].estimated_return == Decimal("0.02")

    floor_cases = [case.model_copy(update={"annual_return_rate": Decimal("-0.999999")}) for case in _cases(revision)]
    floor_month = app.savings_forecast_service.project_draft(
        scenario.scenario_id,
        [ForecastPoolInput(name="Tiny", pool_type="cash", opening_balance=Decimal("0.01"), as_of_date=date(2026, 1, 1))],
        floor_cases,
    )[ForecastRole.BASELINE].months[0].pools[0]
    assert floor_month.closing_balance == Decimal(0)
    assert floor_month.estimated_return == Decimal("-0.01")


def test_invalid_contract_values_and_unconfirmed_cases_are_blocked(tmp_path):
    with pytest.raises(ValueError):
        ForecastPoolInput(name="Bad", pool_type="cash", opening_balance=-1, as_of_date=date(2026, 1, 1))
    with pytest.raises(ValueError):
        ForecastCaseInput(role=ForecastRole.BASELINE, annual_return_rate=-1)
    with pytest.raises(ValueError):
        ForecastAdjustmentInput(
            target_type=ForecastTargetType.LINE,
            target="line",
            operation=ForecastAdjustmentOperation.REPLACEMENT,
            value=-1,
            start_month=1,
        )

    app, scenario, revision = _app(tmp_path, [])
    cases = [case.model_copy(update={"confirmed": False}) for case in _cases(revision)]
    with pytest.raises(ForecastValidationError, match="explicitly confirmed"):
        app.savings_forecast_service.create_forecast(
            "Blocked", scenario.scenario_id,
            [ForecastPoolInput(name="Cash", pool_type="cash", opening_balance=0, as_of_date=date(2026, 1, 1))],
            cases,
        )


def test_assumption_hash_is_order_independent_and_lifecycle_is_append_only(tmp_path):
    app, scenario, revision = _app(tmp_path, [])
    pool = ForecastPoolInput(name="Cash", pool_type="cash", opening_balance=0, as_of_date=date(2026, 1, 1))
    cases = _cases(revision)
    first = app.savings_forecast_service.project_draft(scenario.scenario_id, [pool], cases)
    second = app.savings_forecast_service.project_draft(scenario.scenario_id, [pool], list(reversed(cases)))
    assert first.assumption_hash == second.assumption_hash

    forecast = app.savings_forecast_service.create_forecast("Lifecycle", scenario.scenario_id, [pool], cases)
    restored = app.savings_forecast_service.restore_revision(forecast.forecast_id, 1, expected_revision_number=1)
    assert restored.revision_number == 2
    clone = app.savings_forecast_service.clone_forecast(forecast.forecast_id)
    assert clone.clone_of_forecast_id == forecast.forecast_id
    app.savings_forecast_service.archive_forecast(forecast.forecast_id)
    assert all(item.forecast_id != forecast.forecast_id for item in app.savings_forecast_service.list_forecasts())
    assert any(item.forecast_id == forecast.forecast_id for item in app.savings_forecast_service.list_forecasts(include_archived=True))
    app.savings_forecast_service.unarchive_forecast(forecast.forecast_id)
    assert any(item.forecast_id == forecast.forecast_id for item in app.savings_forecast_service.list_forecasts())


def test_migration_cycle_and_integrity_audit_backup_cover_forecasts(tmp_path):
    database_path = tmp_path / "forecast-migration.sqlite3"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {"savings_forecast_cases", "savings_forecast_pools"} <= tables
    command.downgrade(config, "0005_planning_quality")
    command.upgrade(config, "head")

    app, scenario, revision = _app(tmp_path / "runtime", [])
    pool = ForecastPoolInput(name="Cash", pool_type="cash", opening_balance=0, as_of_date=date(2026, 1, 1))
    app.savings_forecast_service.create_forecast("Audited", scenario.scenario_id, [pool], _cases(revision))
    assert AuditService(app.database, app.settings).run().passed
    backup = tmp_path / "backup"
    BackupService(app.database, app.settings).create(backup)
    assert BackupService(app.database, app.settings).verify(backup).passed

    with sqlite3.connect(app.database.path) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute("UPDATE savings_forecast_cases SET annual_return_rate = 'NaN'")
    audit = AuditService(app.database, app.settings).run()
    assert not audit.passed
    assert "FORECAST_RETURN_RATE_INVALID" in {
        code for check in audit.checks for code in check.issue_codes
    }
    with sqlite3.connect(backup / app.database.path.name) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute("UPDATE savings_forecast_cases SET annual_return_rate = 'NaN'")
    verification = BackupService(app.database, app.settings).verify(backup)
    assert not verification.passed
    assert "FORECAST_RETURN_RATE_INVALID" in {
        code for check in verification.checks for code in check.issue_codes
    }
