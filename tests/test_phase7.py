from __future__ import annotations

import csv
import io
import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from family_finance.audit import AuditService
from family_finance.backup import BackupService
from family_finance.config import Settings
from family_finance.forecasting import ForecastValidationError
from family_finance.models import (
    ForecastCaseInput,
    ForecastRole,
    ForecastRoutingInput,
    NetWorthAccountInput,
    NetWorthBalanceInput,
    PlanningFrequency,
    PlanningItemInput,
    PlanningItemKind,
)
from family_finance.net_worth import (
    ExistingSnapshotRevisionError,
    NetWorthPreviewStaleError,
    NetWorthService,
    NetWorthValidationError,
)
from family_finance.services import ImportService


def _service(tmp_path):
    app = ImportService(Settings(data_root=tmp_path / "local"))
    service = app.net_worth_service
    service.create_account(
        NetWorthAccountInput(
            account_key="cash",
            display_name="Household cash",
            side="asset",
            category="cash",
            liquidity="liquid",
            active_from=date(2026, 1, 1),
        )
    )
    service.create_account(
        NetWorthAccountInput(
            account_key="pension",
            display_name="Pension",
            side="asset",
            category="pension",
            liquidity="restricted",
            active_from=date(2026, 1, 1),
        )
    )
    service.create_account(
        NetWorthAccountInput(
            account_key="mortgage",
            display_name="Mortgage",
            side="liability",
            category="mortgage",
            active_from=date(2026, 1, 1),
        )
    )
    return app, service


def _csv(service: NetWorthService, snapshot_date: str, amounts: dict[str, str]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=(
            "snapshot_date",
            "account_key",
            "account_name",
            "side",
            "category",
            "liquidity",
            "owner",
            "amount_ils",
            "valuation_date",
            "notes",
        ),
        lineterminator="\n",
    )
    writer.writeheader()
    for account_key, amount in amounts.items():
        account = service.get_account(account_key)
        writer.writerow(
            {
                "snapshot_date": snapshot_date,
                "account_key": account_key,
                "account_name": account.display_name,
                "side": account.side.value,
                "category": account.category.value,
                "liquidity": account.liquidity.value if account.liquidity else "",
                "owner": account.owner_label or "",
                "amount_ils": amount,
                "valuation_date": snapshot_date,
                "notes": "",
            }
        )
    return output.getvalue().encode()


def test_net_worth_validates_metadata_staleness_and_exact_aggregates(tmp_path):
    _app, service = _service(tmp_path)
    assert service.get_account("cash").stale_after_days == 45
    assert service.get_account("pension").stale_after_days == 120
    with pytest.raises(ValueError):
        NetWorthAccountInput(
            account_key="bad",
            display_name="Bad",
            side="asset",
            category="cash",
            liquidity=None,
        )
    with pytest.raises(NetWorthValidationError):
        service.create_snapshot(
            date(2026, 9, 1),
            [
                NetWorthBalanceInput(account_key="cash", amount_ils=100, valuation_date=date(2026, 9, 1)),
                NetWorthBalanceInput(account_key="pension", amount_ils=200, valuation_date=date(2026, 1, 1)),
            ],
        )
    first = service.create_snapshot(
        date(2026, 9, 1),
        {"cash": "100.10", "pension": "200.20", "mortgage": "40.05"},
    )
    summary = service.summary(snapshot_id=first.snapshot_id)
    assert summary.total_assets == Decimal("300.30")
    assert summary.total_liabilities == Decimal("40.05")
    assert summary.net_worth == Decimal("260.25")
    assert summary.liquid_assets == Decimal("100.10")
    assert summary.restricted_assets == Decimal("200.20")
    service.update_account("cash", display_name="Renamed cash")
    second = service.save_revision(
        first.snapshot_id,
        {"cash": "101.10", "pension": "200.20", "mortgage": "40.05"},
        expected_revision_number=1,
    )
    assert first.balances[0].account_name == "Household cash"
    assert second.balances[0].account_name == "Renamed cash"


def test_net_worth_csv_is_strict_idempotent_and_requires_explicit_new_revision(tmp_path):
    _app, service = _service(tmp_path)
    source = _csv(service, "2026-09-01", {"cash": "100", "pension": "200", "mortgage": "40"})
    preview = service.preview_csv(source, "balances.csv")
    assert preview.valid
    first = service.commit_csv(source, preview.preview_token, "balances.csv")
    assert service.commit_csv(source, preview.preview_token, "balances.csv").revision_id == first.revision_id
    revised = _csv(service, "2026-09-01", {"cash": "101", "pension": "200", "mortgage": "40"})
    revised_preview = service.preview_csv(revised)
    with pytest.raises(ExistingSnapshotRevisionError):
        service.commit_csv(revised, revised_preview.preview_token)
    second = service.commit_csv(revised, revised_preview.preview_token, create_new_revision=True)
    assert second.revision_number == 2
    stale_preview = service.preview_csv(_csv(service, "2026-10-01", {"cash": "102", "pension": "201", "mortgage": "39"}))
    service.update_account("cash", display_name="Cash after preview")
    with pytest.raises(NetWorthPreviewStaleError):
        service.commit_csv(
            _csv(service, "2026-10-01", {"cash": "102", "pension": "201", "mortgage": "39"}),
            stale_preview.preview_token,
        )


def test_net_worth_forecast_seed_is_pinned_and_later_snapshots_do_not_mutate_it(tmp_path):
    app, service = _service(tmp_path)
    first = service.create_snapshot(
        date(2026, 1, 1), {"cash": "100", "pension": "200", "mortgage": "40"}
    )
    scenario = app.planning_service.create_manual_scenario(
        "Baseline",
        date(2026, 1, 1),
        [
            PlanningItemInput(
                kind=PlanningItemKind.INCOME,
                label="Salary",
                amount=100,
                frequency=PlanningFrequency.MONTHLY,
                start_month=date(2026, 1, 1),
                end_month=date(2026, 12, 1),
            )
        ],
    )
    cases = [ForecastCaseInput(role=role, annual_return_rate=0, confirmed=True) for role in ForecastRole]
    forecast = app.savings_forecast_service.create_forecast_from_net_worth(
        "Seeded forecast", scenario.scenario_id, first.revision_id, ["cash"], cases
    )
    saved = app.savings_forecast_service.get_revision(forecast.forecast_id)
    assert saved.net_worth_snapshot_revision_id == first.revision_id
    assert saved.starting_pools[0].opening_balance == Decimal(100)
    service.save_revision(
        first.snapshot_id,
        {"cash": "999", "pension": "200", "mortgage": "40"},
        expected_revision_number=1,
    )
    assert app.savings_forecast_service.get_revision(forecast.forecast_id).starting_pools[0].opening_balance == Decimal(100)
    assert AuditService(app.database, app.settings).run().passed
    backup_root = tmp_path / "backup"
    BackupService(app.database, app.settings).create(backup_root)
    assert BackupService(app.database, app.settings).verify(backup_root).passed


def test_historical_revision_uses_captured_account_coverage_after_lifecycle_edit(tmp_path):
    app, service = _service(tmp_path)
    first = service.create_snapshot(
        date(2026, 9, 1), {"cash": "100", "pension": "200", "mortgage": "40"}
    )
    service.close_account("mortgage", date(2026, 8, 31))

    revised = service.save_revision(
        first.snapshot_id,
        {"cash": "101", "pension": "201", "mortgage": "39"},
        expected_revision_number=1,
    )

    assert {item.account_key for item in revised.balances} == {"cash", "pension", "mortgage"}
    assert AuditService(app.database, app.settings).run().passed


def test_forecast_rejects_mid_month_net_worth_opening_that_would_recount_cash_flows(tmp_path):
    app, service = _service(tmp_path)
    snapshot = service.create_snapshot(
        date(2026, 1, 15), {"cash": "100", "pension": "200", "mortgage": "40"}
    )
    scenario = app.planning_service.create_manual_scenario(
        "January plan",
        date(2026, 1, 1),
        [
            PlanningItemInput(
                kind=PlanningItemKind.INCOME,
                label="Salary",
                amount=100,
                frequency=PlanningFrequency.MONTHLY,
                start_month=date(2026, 1, 1),
                end_month=date(2026, 12, 1),
            )
        ],
    )
    cases = [ForecastCaseInput(role=role, annual_return_rate=0, confirmed=True) for role in ForecastRole]

    with pytest.raises(ForecastValidationError, match="first-of-month or month-end"):
        app.savings_forecast_service.create_forecast_from_net_worth(
            "Unsafe mid-month forecast",
            scenario.scenario_id,
            snapshot.revision_id,
            ["cash"],
            cases,
        )


def test_audit_and_backup_reject_deleted_forecast_pool_rows(tmp_path):
    app, service = _service(tmp_path)
    snapshot = service.create_snapshot(
        date(2026, 1, 1), {"cash": "100", "pension": "200", "mortgage": "40"}
    )
    scenario = app.planning_service.create_manual_scenario(
        "January plan",
        date(2026, 1, 1),
        [
            PlanningItemInput(
                kind=PlanningItemKind.INCOME,
                label="Salary",
                amount=100,
                frequency=PlanningFrequency.MONTHLY,
                start_month=date(2026, 1, 1),
                end_month=date(2026, 12, 1),
            )
        ],
    )
    cases = [ForecastCaseInput(role=role, annual_return_rate=0, confirmed=True) for role in ForecastRole]
    forecast = app.savings_forecast_service.create_forecast_from_net_worth(
        "Forecast with a pool",
        scenario.scenario_id,
        snapshot.revision_id,
        ["cash"],
        cases,
    )
    backup_root = tmp_path / "backup"
    BackupService(app.database, app.settings).create(backup_root)

    with app.database.connect() as connection:
        connection.execute(
            "DELETE FROM savings_forecast_pools WHERE case_id IN "
            "(SELECT id FROM savings_forecast_cases WHERE revision_id IN "
            "(SELECT id FROM savings_forecast_revisions WHERE forecast_id = ?))",
            (forecast.forecast_id,),
        )
        connection.commit()
    report = AuditService(app.database, app.settings).run()
    audit_codes = {code for check in report.checks for code in check.issue_codes}
    assert "FORECAST_POOL_SET_INVALID" in audit_codes

    backup_db = next(path for path in backup_root.iterdir() if path.name != "manifest.json")
    with sqlite3.connect(backup_db) as connection:
        connection.execute(
            "DELETE FROM savings_forecast_pools WHERE case_id IN "
            "(SELECT id FROM savings_forecast_cases WHERE revision_id IN "
            "(SELECT id FROM savings_forecast_revisions WHERE forecast_id = ?))",
            (forecast.forecast_id,),
        )
        connection.commit()
    verification = BackupService(app.database, app.settings).verify(backup_root)
    backup_codes = {code for check in verification.checks for code in check.issue_codes}
    assert "FORECAST_POOL_SET_INVALID" in backup_codes


def test_audit_rejects_deleted_forecast_routing_rows(tmp_path):
    app, service = _service(tmp_path)
    snapshot = service.create_snapshot(
        date(2026, 1, 1), {"cash": "100", "pension": "200", "mortgage": "40"}
    )
    scenario = app.planning_service.create_manual_scenario(
        "Savings plan",
        date(2026, 1, 1),
        [
            PlanningItemInput(
                kind=PlanningItemKind.SAVINGS_CONTRIBUTION,
                label="Monthly savings",
                amount=25,
                frequency=PlanningFrequency.MONTHLY,
                start_month=date(2026, 1, 1),
                end_month=date(2026, 12, 1),
            )
        ],
    )
    source_revision = app.planning_service.get_revision(scenario.scenario_id)
    savings_item = next(item for item in source_revision.items if item.kind == PlanningItemKind.SAVINGS_CONTRIBUTION)
    cases = [
        ForecastCaseInput(
            role=role,
            annual_return_rate=0,
                routes=[ForecastRoutingInput(source_item_id=savings_item.id, pool_name="Household cash")],
            confirmed=True,
        )
        for role in ForecastRole
    ]
    forecast = app.savings_forecast_service.create_forecast_from_net_worth(
        "Forecast with routing",
        scenario.scenario_id,
        snapshot.revision_id,
        ["cash"],
        cases,
    )
    with app.database.connect() as connection:
        connection.execute(
            "DELETE FROM savings_forecast_routings WHERE case_id = "
            "(SELECT id FROM savings_forecast_cases WHERE revision_id = "
            "(SELECT id FROM savings_forecast_revisions WHERE forecast_id = ? LIMIT 1) LIMIT 1)",
            (forecast.forecast_id,),
        )
        connection.commit()

    report = AuditService(app.database, app.settings).run()
    codes = {code for check in report.checks for code in check.issue_codes}
    assert "FORECAST_NORMALIZED_ROWS_INVALID" in codes


def test_balance_snapshot_dates_are_hash_and_backup_protected(tmp_path):
    app, service = _service(tmp_path)
    revision = service.create_snapshot(
        date(2026, 9, 1), {"cash": "100", "pension": "200", "mortgage": "40"}
    )
    backup_root = tmp_path / "backup"
    BackupService(app.database, app.settings).create(backup_root)

    with sqlite3.connect(app.database.path) as connection:
        connection.execute(
            "UPDATE net_worth_balances SET snapshot_date = ?, valuation_date = ? WHERE revision_id = ?",
            ("2026-08-31", "2026-08-31", revision.revision_id),
        )
        connection.commit()
    with pytest.raises(NetWorthValidationError, match="balance snapshot date"):
        service.get_revision(revision.snapshot_id)

    backup_db = next(path for path in backup_root.iterdir() if path.name != "manifest.json")
    with sqlite3.connect(backup_db) as connection:
        connection.execute(
            "UPDATE net_worth_balances SET snapshot_date = ?, valuation_date = ? WHERE revision_id = ?",
            ("2026-08-31", "2026-08-31", revision.revision_id),
        )
        connection.commit()
    verification = BackupService(app.database, app.settings).verify(backup_root)
    codes = {code for check in verification.checks for code in check.issue_codes}
    assert "NET_WORTH_BALANCE_SNAPSHOT_DATE_INVALID" in codes


def test_historical_csv_template_includes_accounts_closed_after_snapshot(tmp_path):
    _app, service = _service(tmp_path)
    service.create_snapshot(
        date(2026, 9, 1), {"cash": "100", "pension": "200", "mortgage": "40"}
    )
    service.close_account("mortgage", date(2026, 12, 31))

    rows = list(csv.DictReader(io.StringIO(service.csv_template(date(2026, 9, 1)).decode())))

    assert {row["account_key"] for row in rows} == {"cash", "pension", "mortgage"}


def test_historical_csv_template_round_trips_after_registry_metadata_edit(tmp_path):
    _app, service = _service(tmp_path)
    service.create_snapshot(
        date(2026, 9, 1), {"cash": "100", "pension": "200", "mortgage": "40"}
    )
    service.update_account("cash", display_name="Cash today")

    preview = service.preview_csv(service.csv_template(date(2026, 9, 1)), "historical.csv")

    assert preview.valid, preview.issues
