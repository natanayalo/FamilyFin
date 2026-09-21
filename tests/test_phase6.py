import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from family_finance.apartment import (
    ApartmentValidationError,
    StaleApartmentRevisionError,
    calculate_mortgage_schedule,
)
from family_finance.audit import AuditService
from family_finance.backup import BackupService
from family_finance.config import Settings
from family_finance.models import (
    ApartmentGuardrails,
    EquityRequirement,
    ForecastCaseInput,
    ForecastPoolInput,
    ForecastRole,
    HousingCostInput,
    MortgageAssumption,
    PlanningFrequency,
    PlanningItemInput,
    PlanningItemKind,
    PoolDrawInput,
    PurchaseAlternativeInput,
    PurchaseCostInput,
)
from family_finance.services import ImportService


def _forecast_app(tmp_path):
    app = ImportService(Settings(data_root=tmp_path / "local"))
    scenario = app.planning_service.create_manual_scenario(
        "Apartment plan",
        date(2026, 1, 1),
        [
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
        ],
    )
    revision = app.planning_service.get_revision(scenario.scenario_id)
    cases = [
        ForecastCaseInput(role=role, annual_return_rate=Decimal(0), sweep_enabled=True, sweep_pool_name="Cash", confirmed=True)
        for role in ForecastRole
    ]
    forecast = app.savings_forecast_service.create_forecast(
        "Apartment source",
        scenario.scenario_id,
        [ForecastPoolInput(name="Cash", pool_type="cash", opening_balance=0, as_of_date=date(2026, 1, 1))],
        cases,
    )
    return app, forecast, revision


def _alternative(revision, name="Option A", *, month=2, draw=Decimal(50), confirmed=True):
    return PurchaseAlternativeInput(
        name=name,
        forecast_role=ForecastRole.BASELINE,
        purchase_month=month,
        property_price=Decimal(105),
        family_gift=Decimal(10),
        purchase_costs=[PurchaseCostInput(label="Manual fees", amount=Decimal(5))],
        equity_requirement=EquityRequirement(mode="percentage", value=Decimal(".2")),
        mortgage=MortgageAssumption(
            principal=Decimal(50), annual_nominal_rate=Decimal(".06"), term_months=12
        ),
        pool_draws=[PoolDrawInput(pool_name="Cash", amount=draw)],
        stopped_housing_line_ids=[next(item.id for item in revision.items if item.kind == PlanningItemKind.EXPENSE)],
        housing_costs=[HousingCostInput(label="Maintenance", amount=Decimal(2))],
        confirmed=confirmed,
    )


def test_mortgage_schedule_zero_rate_and_final_cent_adjustment():
    zero = calculate_mortgage_schedule(
        MortgageAssumption(principal=Decimal(100), annual_nominal_rate=0, term_months=12)
    )
    assert zero[-1].remaining_principal == Decimal(0)
    assert sum((item.principal for item in zero), Decimal(0)) == Decimal(100)
    positive = calculate_mortgage_schedule(
        MortgageAssumption(principal=Decimal(50), annual_nominal_rate=Decimal(".06"), term_months=12)
    )
    assert positive[-1].remaining_principal == Decimal(0)
    assert positive[0].interest == Decimal("0.25")


def test_apartment_projection_closes_after_sweep_and_stops_rent(tmp_path):
    app, forecast, revision = _forecast_app(tmp_path)
    alternative = _alternative(revision)
    draft = app.apartment_planning_service.project_draft(
        forecast.forecast_id,
        [alternative, _alternative(revision, "Option B", month=3)],
        guardrails=ApartmentGuardrails(minimum_remaining_liquidity=Decimal(1)),
    )
    projection = draft.projections[0]
    closing_month = projection.source_projection.months[1]
    assert closing_month.pools[0].swept_surplus == Decimal(60)
    assert closing_month.pools[0].fulfilled_capital_draw == Decimal(50)
    assert projection.funding_gap == Decimal(0)
    assert projection.monthly[1].expenses == Decimal(40)
    assert projection.monthly[2].expenses < Decimal(40)
    assert projection.monthly[2].removed_housing_costs == Decimal(40)
    assert projection.monthly[1].ending_balance == Decimal(70)
    assert projection.monthly[14].expenses == Decimal(2)
    assert projection.monthly[14].housing_cost == Decimal(2)


def test_apartment_lifecycle_is_pinned_append_only_and_rejects_overfunding(tmp_path):
    app, forecast, revision = _forecast_app(tmp_path)
    alternatives = [_alternative(revision), _alternative(revision, "Option B", month=3)]
    service = app.apartment_planning_service
    saved = service.create_study("Study", forecast.forecast_id, alternatives)
    restored = service.restore_revision(saved.study_id, 1, expected_revision_number=1)
    assert restored.revision_number == 2
    with pytest.raises(StaleApartmentRevisionError):
        service.save_revision(saved.study_id, restored, expected_revision_number=1)
    overfunded = [_alternative(revision, draw=Decimal(100)), _alternative(revision, "Other", draw=Decimal(100))]
    with pytest.raises(ApartmentValidationError, match="sources greater"):
        service.project_draft(forecast.forecast_id, overfunded)
    with pytest.raises(ApartmentValidationError, match="sources greater"):
        service.create_study("Overfunded", forecast.forecast_id, overfunded)
    clone = service.clone_study(saved.study_id)
    assert clone.clone_of_study_id == saved.study_id


def test_month_36_purchase_keeps_first_payment_out_of_month_36_cash_flow(tmp_path):
    app, forecast, revision = _forecast_app(tmp_path)
    draft = app.apartment_planning_service.project_draft(
        forecast.forecast_id,
        [_alternative(revision, month=36), _alternative(revision, "Option B", month=3)],
    )
    projection = draft.projections[0]
    month_36 = projection.monthly[35]
    assert month_36.housing_cost == Decimal(0)
    assert month_36.net_cash_flow_change == Decimal(0)
    assert month_36.expenses == Decimal(40)
    assert projection.maximum_housing_ratio > Decimal(0)


def test_apartment_audit_and_backup_reconcile_normalized_rows(tmp_path):
    app, forecast, revision = _forecast_app(tmp_path)
    app.apartment_planning_service.create_study(
        "Study", forecast.forecast_id, [_alternative(revision), _alternative(revision, "Option B", month=3)]
    )
    with sqlite3.connect(app.database.path) as connection:
        connection.execute("UPDATE apartment_alternatives SET property_price = '999' WHERE name = 'Option A'")
    audit = AuditService(app.database, app.settings).run()
    assert not audit.passed
    assert "APARTMENT_NORMALIZED_ALTERNATIVE_INVALID" in {
        code for check in audit.checks for code in check.issue_codes
    }

    clean_root = tmp_path / "clean"
    clean_app, clean_forecast, clean_revision = _forecast_app(clean_root)
    clean_app.apartment_planning_service.create_study(
        "Study", clean_forecast.forecast_id, [_alternative(clean_revision), _alternative(clean_revision, "Option B", month=3)]
    )
    backup_root = tmp_path / "backup"
    BackupService(clean_app.database, clean_app.settings).create(backup_root)
    with sqlite3.connect(backup_root / clean_app.database.path.name) as connection:
        connection.execute("UPDATE apartment_alternatives SET property_price = '999' WHERE name = 'Option A'")
    verification = BackupService(clean_app.database, clean_app.settings).verify(backup_root)
    assert not verification.passed
    assert "APARTMENT_NORMALIZED_ALTERNATIVE_INVALID" in {
        code for check in verification.checks for code in check.issue_codes
    }
