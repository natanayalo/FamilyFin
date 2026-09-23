"""Read-only integrity and provenance audit for the local financial store."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from family_finance.apartment import apartment_assumption_hash
from family_finance.config import Settings
from family_finance.forecasting import assumption_hash
from family_finance.models import (
    ApartmentRevisionSnapshot,
    AuditCheck,
    AuditReport,
    ForecastRevisionSnapshot,
)
from family_finance.net_worth import NetWorthService, NetWorthValidationError
from family_finance.persistence.db import Database
from family_finance.persistence.models import (
    ApartmentAlternativeRow,
    ApartmentHousingCostRow,
    ApartmentPoolDrawRow,
    ApartmentPurchaseCostRow,
    ApartmentRevisionRow,
    ApartmentStoppedHousingLineRow,
    ApartmentStudyRow,
    ForecastAdjustmentRow,
    ForecastCaseRow,
    ForecastEventRow,
    ForecastPoolRow,
    ForecastRevisionRow,
    ForecastRoutingRow,
    ForecastRow,
    ImportBatchRow,
    NetWorthAccountRow,
    NetWorthBalanceRow,
    NetWorthSnapshotRevisionRow,
    NetWorthSnapshotRow,
    NetWorthSourceFileRow,
    PlanningItemRow,
    PlanningScenarioRevisionRow,
    PlanningScenarioRow,
    PlanningSourceFileRow,
    ReconciliationCaseRow,
    SourceFileRow,
    SourceRecordRow,
    TransactionRow,
    TransactionSourceRow,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class AuditService:
    def __init__(self, database: Database | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_environment()
        self.database = database
        if self.database is None and self.settings.database_path.is_file():
            self.database = Database(self.settings.database_path, read_only=True)

    def run(self) -> AuditReport:
        if self.database is None:
            return AuditReport(
                passed=False,
                checks=[AuditCheck(name="database", passed=False, issue_codes=["DATABASE_MISSING"])],
            )
        checks = [
            self._safe_check(self._integrity_check),
            self._safe_check(self._foreign_keys_check),
            self._safe_check(self._schema_check),
            self._safe_check(self._archive_hash_check),
            self._safe_check(self._source_lifecycle_check),
            self._safe_check(self._transaction_provenance_check),
            self._safe_check(self._batch_count_check),
            self._safe_check(self._planning_invariant_check),
            self._safe_check(self._forecast_invariant_check),
            self._safe_check(self._net_worth_invariant_check),
            self._safe_check(self._apartment_invariant_check),
            self._safe_check(self._phase8_invariant_check),
        ]
        return AuditReport(passed=all(check.passed for check in checks), checks=checks)

    def _safe_check(self, check) -> AuditCheck:
        try:
            return check()
        except (OSError, sqlite3.DatabaseError, SQLAlchemyError):
            return AuditCheck(name="database", passed=False, issue_codes=["DATABASE_UNREADABLE"])

    def _check(self, name: str, passed: bool, *codes: str) -> AuditCheck:
        return AuditCheck(name=name, passed=passed, issue_codes=[] if passed else list(codes))

    def _integrity_check(self) -> AuditCheck:
        with self.database.engine.connect() as connection:
            result = str(connection.exec_driver_sql("PRAGMA integrity_check").scalar_one())
        return self._check("sqlite_integrity", result == "ok", "SQLITE_INTEGRITY_ERROR")

    def _foreign_keys_check(self) -> AuditCheck:
        with self.database.engine.connect() as connection:
            rows = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
        return self._check("foreign_keys", not rows, "FOREIGN_KEY_ERROR")

    def _schema_check(self) -> AuditCheck:
        project_root = Path(__file__).resolve().parents[2]
        config = Config(str(project_root / "alembic.ini"))
        head = ScriptDirectory.from_config(config).get_current_head()
        with self.database.engine.connect() as connection:
            current = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one_or_none()
        return self._check("alembic_head", str(current) == str(head), "SCHEMA_REVISION_MISMATCH")

    def _archive_hash_check(self) -> AuditCheck:
        missing = False
        mismatch = False
        with self.database.session() as session:
            rows = session.execute(select(SourceFileRow)).scalars().all()
        for row in rows:
            path = Path(row.archived_path)
            if not path.is_absolute():
                path = self.settings.data_root / path
            if not path.exists():
                relocated = sorted(self.settings.archive_root.glob(f"{row.sha256}.*"))
                if relocated:
                    path = relocated[0]
            if not path.exists():
                missing = True
            elif _sha256(path) != row.sha256:
                mismatch = True
        with self.database.session() as session:
            planning_rows = session.execute(select(PlanningSourceFileRow)).scalars().all()
        for row in planning_rows:
            path = Path(row.archived_path)
            if not path.is_absolute():
                path = self.settings.data_root / path
            if not path.exists():
                relocated = sorted(self.settings.planning_archive_root.glob(f"{row.sha256}.*"))
                if relocated:
                    path = relocated[0]
            if not path.exists():
                missing = True
            elif _sha256(path) != row.sha256:
                mismatch = True
        with self.database.session() as session:
            net_worth_rows = session.execute(select(NetWorthSourceFileRow)).scalars().all()
        for row in net_worth_rows:
            path = Path(row.archived_path)
            if not path.is_absolute():
                path = self.settings.data_root / path
            if not path.exists():
                relocated = sorted(self.settings.net_worth_archive_root.glob(f"{row.sha256}.*"))
                if relocated:
                    path = relocated[0]
            if not path.exists():
                missing = True
            elif _sha256(path) != row.sha256:
                mismatch = True
        codes = []
        if missing:
            codes.append("ARCHIVE_MISSING")
        if mismatch:
            codes.append("ARCHIVE_HASH_MISMATCH")
        return self._check("archive_hashes", not codes, *codes)

    def _source_lifecycle_check(self) -> AuditCheck:
        codes: list[str] = []
        with self.database.session() as session:
            sources = session.execute(select(SourceRecordRow)).scalars().all()
            for source in sources:
                link_count = int(
                    session.execute(
                        select(func.count())
                        .select_from(TransactionSourceRow)
                        .where(TransactionSourceRow.source_record_id == source.id)
                    ).scalar_one()
                )
                open_case_count = int(
                    session.execute(
                        select(func.count())
                        .select_from(ReconciliationCaseRow)
                        .where(
                            ReconciliationCaseRow.source_record_id == source.id,
                            ReconciliationCaseRow.status == "open",
                        )
                    ).scalar_one()
                )
                case_statuses = [row[0] for row in session.execute(
                    select(ReconciliationCaseRow.status).where(
                        ReconciliationCaseRow.source_record_id == source.id
                    )
                ).all()]
                if source.validation_state == "accepted" and link_count != 1:
                    codes.append("ACCEPTED_SOURCE_LINK_MISSING_OR_DUPLICATE")
                elif source.validation_state == "accepted" and open_case_count:
                    codes.append("ACCEPTED_SOURCE_HAS_OPEN_CASE")
                elif source.validation_state == "unresolved" and open_case_count != 1:
                    codes.append("UNRESOLVED_SOURCE_CASE_MISSING")
                elif source.validation_state == "dismissed" and (
                    link_count or case_statuses != ["dismissed"]
                ):
                    codes.append("DISMISSED_SOURCE_LIFECYCLE_INVALID")
                elif source.validation_state not in {"accepted", "unresolved", "dismissed"}:
                    codes.append("UNKNOWN_SOURCE_LIFECYCLE_STATE")
        return self._check("source_row_lifecycle", not codes, *sorted(set(codes)))

    def _transaction_provenance_check(self) -> AuditCheck:
        with self.database.session() as session:
            transactions = session.execute(select(TransactionRow.id)).all()
            missing = [
                transaction_id
                for (transaction_id,) in transactions
                if int(
                    session.execute(
                        select(func.count())
                        .select_from(TransactionSourceRow)
                        .where(TransactionSourceRow.transaction_id == transaction_id)
                    ).scalar_one()
                )
                < 1
            ]
            non_accepted_links = session.execute(
                select(TransactionSourceRow.transaction_id)
                .join(SourceRecordRow, SourceRecordRow.id == TransactionSourceRow.source_record_id)
                .where(SourceRecordRow.validation_state != "accepted")
            ).all()
        if non_accepted_links:
            missing.extend(int(row[0]) for row in non_accepted_links)
        return self._check("transaction_provenance", not missing, "TRANSACTION_PROVENANCE_MISSING")

    def _batch_count_check(self) -> AuditCheck:
        codes: list[str] = []
        with self.database.session() as session:
            batches = session.execute(select(ImportBatchRow)).scalars().all()
            for batch in batches:
                if batch.status == "duplicate":
                    continue
                expected = _statistics_total(batch.statistics_json)
                actual = int(
                    session.execute(
                        select(func.count())
                        .select_from(SourceRecordRow)
                        .where(SourceRecordRow.import_batch_id == batch.id)
                    ).scalar_one()
                )
                if expected is not None and expected != actual:
                    codes.append("BATCH_SOURCE_COUNT_MISMATCH")
        return self._check("batch_count_reconciliation", not codes, *sorted(set(codes)))

    def _planning_invariant_check(self) -> AuditCheck:
        codes: list[str] = []
        with self.database.session() as session:
            scenarios = session.execute(select(PlanningScenarioRow)).scalars().all()
            for scenario in scenarios:
                revisions = session.execute(
                    select(PlanningScenarioRevisionRow)
                    .where(PlanningScenarioRevisionRow.scenario_id == scenario.id)
                    .order_by(PlanningScenarioRevisionRow.revision_number)
                ).scalars().all()
                numbers = [row.revision_number for row in revisions]
                if numbers != list(range(1, scenario.current_revision_number + 1)):
                    codes.append("PLANNING_REVISION_SEQUENCE_INVALID")
                for revision in revisions:
                    items = session.execute(
                        select(PlanningItemRow).where(PlanningItemRow.revision_id == revision.id)
                    ).scalars().all()
                    for item in items:
                        try:
                            amount = Decimal(item.amount)
                            if amount < 0 or not amount.is_finite():
                                codes.append("PLANNING_AMOUNT_INVALID")
                        except (InvalidOperation, ValueError):
                            codes.append("PLANNING_AMOUNT_INVALID")
                        if item.frequency == "monthly" and not (item.start_month and item.end_month and not item.occurrence_month):
                            codes.append("PLANNING_SCHEDULE_INVALID")
                        if item.frequency == "one_time" and not (item.occurrence_month and not item.start_month and not item.end_month):
                            codes.append("PLANNING_SCHEDULE_INVALID")
        return self._check("planning_invariants", not codes, *sorted(set(codes)))

    def _forecast_invariant_check(self) -> AuditCheck:
        """Verify saved forecast continuity without recalculating projections."""

        codes: list[str] = []
        with self.database.session() as session:
            forecasts = session.execute(select(ForecastRow)).scalars().all()
            for forecast in forecasts:
                if forecast.horizon_months != 36:
                    codes.append("FORECAST_HORIZON_INVALID")
                source = session.get(PlanningScenarioRevisionRow, forecast.source_revision_id)
                if source is None or source.scenario_id != forecast.scenario_id or source.revision_number != forecast.source_revision_number:
                    codes.append("FORECAST_SOURCE_PLAN_REFERENCE_INVALID")
                revisions = session.execute(
                    select(ForecastRevisionRow)
                    .where(ForecastRevisionRow.forecast_id == forecast.id)
                    .order_by(ForecastRevisionRow.revision_number)
                ).scalars().all()
                numbers = [row.revision_number for row in revisions]
                if numbers != list(range(1, forecast.current_revision_number + 1)):
                    codes.append("FORECAST_REVISION_SEQUENCE_INVALID")
                if not revisions or revisions[-1].revision_number != forecast.current_revision_number:
                    codes.append("FORECAST_CURRENT_REVISION_POINTER_INVALID")
                for revision in revisions:
                    if revision.source_revision_id != forecast.source_revision_id or revision.source_revision_number != forecast.source_revision_number:
                        codes.append("FORECAST_SOURCE_PLAN_REFERENCE_INVALID")
                    if revision.net_worth_snapshot_revision_id and session.get(
                        NetWorthSnapshotRevisionRow, revision.net_worth_snapshot_revision_id
                    ) is None:
                        codes.append("FORECAST_NET_WORTH_SOURCE_INVALID")
                    snapshot = None
                    try:
                        payload = json.loads(revision.assumptions_json)
                        snapshot_hash = assumption_hash(ForecastRevisionSnapshot.model_validate(payload))
                        snapshot = ForecastRevisionSnapshot.model_validate(payload)
                        if snapshot_hash != revision.assumption_hash:
                            codes.append("FORECAST_ASSUMPTION_HASH_INVALID")
                    except (TypeError, ValueError, json.JSONDecodeError):
                        codes.append("FORECAST_ASSUMPTIONS_INVALID")
                    cases = session.execute(
                        select(ForecastCaseRow).where(ForecastCaseRow.revision_id == revision.id)
                    ).scalars().all()
                    roles = sorted(case.role for case in cases)
                    if roles != ["baseline", "conservative", "optimistic"]:
                        codes.append("FORECAST_CASE_SET_INVALID")
                    for case in cases:
                        try:
                            rate = Decimal(case.annual_return_rate)
                            if not rate.is_finite() or rate <= Decimal(-1):
                                codes.append("FORECAST_RETURN_RATE_INVALID")
                        except (InvalidOperation, TypeError, ValueError):
                            codes.append("FORECAST_RETURN_RATE_INVALID")
                        pools = session.execute(
                            select(ForecastPoolRow).where(ForecastPoolRow.case_id == case.id)
                        ).scalars().all()
                        pool_ids = {pool.id for pool in pools}
                        if not pools:
                            codes.append("FORECAST_POOL_SET_EMPTY")
                        if snapshot is not None:
                            expected_pool_names = [
                                item.name.casefold() for item in snapshot.starting_pools
                            ]
                            actual_pool_names = [pool.name.casefold() for pool in pools]
                            if (
                                len(actual_pool_names) != len(expected_pool_names)
                                or set(actual_pool_names) != set(expected_pool_names)
                            ):
                                codes.append("FORECAST_POOL_SET_INVALID")
                        for pool in pools:
                            try:
                                amount = Decimal(pool.opening_balance)
                                if amount < 0 or not amount.is_finite():
                                    codes.append("FORECAST_OPENING_BALANCE_INVALID")
                            except (InvalidOperation, ValueError):
                                codes.append("FORECAST_OPENING_BALANCE_INVALID")
                            if pool.pool_type not in {"cash", "investment"}:
                                codes.append("FORECAST_POOL_TYPE_INVALID")
                            if pool.net_worth_snapshot_revision_id:
                                source_revision = session.get(
                                    NetWorthSnapshotRevisionRow, pool.net_worth_snapshot_revision_id
                                )
                                if source_revision is None:
                                    codes.append("FORECAST_NET_WORTH_SOURCE_INVALID")
                                if revision.net_worth_snapshot_revision_id != pool.net_worth_snapshot_revision_id:
                                    codes.append("FORECAST_NET_WORTH_SOURCE_INVALID")
                                if source_revision is not None:
                                    source_balance = session.execute(
                                        select(NetWorthBalanceRow).where(
                                            NetWorthBalanceRow.revision_id == source_revision.id,
                                            NetWorthBalanceRow.account_key == pool.net_worth_account_key,
                                        )
                                    ).scalar_one_or_none()
                                    if source_balance is None:
                                        codes.append("FORECAST_NET_WORTH_PROVENANCE_INVALID")
                                    else:
                                        try:
                                            if Decimal(pool.opening_balance) != Decimal(source_balance.amount_ils):
                                                codes.append("FORECAST_NET_WORTH_PROVENANCE_INVALID")
                                        except (InvalidOperation, TypeError, ValueError):
                                            codes.append("FORECAST_NET_WORTH_PROVENANCE_INVALID")
                                        if pool.as_of_date != source_revision.snapshot_date:
                                            codes.append("FORECAST_NET_WORTH_PROVENANCE_INVALID")
                                        if pool.source_valuation_date != source_balance.valuation_date:
                                            codes.append("FORECAST_NET_WORTH_PROVENANCE_INVALID")
                            elif pool.net_worth_account_key:
                                codes.append("FORECAST_NET_WORTH_PROVENANCE_INVALID")
                            if pool.net_worth_account_key and session.execute(
                                select(NetWorthAccountRow).where(
                                    NetWorthAccountRow.account_key == pool.net_worth_account_key
                                )
                            ).scalar_one_or_none() is None:
                                codes.append("FORECAST_NET_WORTH_ACCOUNT_INVALID")
                            if snapshot is not None:
                                expected_pool = next(
                                    (
                                        item for item in snapshot.starting_pools
                                        if item.name.casefold() == pool.name.casefold()
                                    ),
                                    None,
                                )
                                if expected_pool is None:
                                    codes.append("FORECAST_NORMALIZED_ROWS_INVALID")
                                else:
                                    try:
                                        normalized_valid = (
                                            expected_pool.pool_type.value == pool.pool_type
                                            and expected_pool.net_worth_account_key == pool.net_worth_account_key
                                            and expected_pool.net_worth_snapshot_revision_id == pool.net_worth_snapshot_revision_id
                                            and expected_pool.as_of_date.isoformat() == pool.as_of_date
                                            and Decimal(expected_pool.opening_balance) == Decimal(pool.opening_balance)
                                            and (
                                                expected_pool.source_valuation_date.isoformat()
                                                if expected_pool.source_valuation_date else None
                                            ) == pool.source_valuation_date
                                        )
                                    except (InvalidOperation, TypeError, ValueError):
                                        normalized_valid = False
                                    if not normalized_valid:
                                        codes.append("FORECAST_NORMALIZED_ROWS_INVALID")
                        if case.sweep_enabled and case.sweep_pool_id not in pool_ids:
                            codes.append("FORECAST_SWEEP_POOL_INVALID")
                        routes = session.execute(
                            select(ForecastRoutingRow).where(ForecastRoutingRow.case_id == case.id)
                        ).scalars().all()
                        if snapshot is not None:
                            expected_case = next(
                                (item for item in snapshot.cases if item.role.value == case.role),
                                None,
                            )
                            if expected_case is None:
                                codes.append("FORECAST_NORMALIZED_ROWS_INVALID")
                            else:
                                expected_route_ids = {
                                    route.source_item_id for route in expected_case.routes
                                }
                                actual_route_ids = {route.source_item_id for route in routes}
                                if (
                                    len(routes) != len(expected_case.routes)
                                    or actual_route_ids != expected_route_ids
                                ):
                                    codes.append("FORECAST_NORMALIZED_ROWS_INVALID")
                        for route in routes:
                            if route.pool_id not in pool_ids:
                                codes.append("FORECAST_ROUTING_POOL_INVALID")
                            item = session.get(PlanningItemRow, route.source_item_id)
                            if item is None or item.revision_id != forecast.source_revision_id or item.kind not in {"savings_contribution", "savings_withdrawal"}:
                                codes.append("FORECAST_ROUTING_SOURCE_INVALID")
                        events = session.execute(
                            select(ForecastEventRow).where(ForecastEventRow.case_id == case.id)
                        ).scalars().all()
                        if snapshot is not None and expected_case is not None:
                            pool_name_by_id = {pool.id: pool.name for pool in pools}
                            try:
                                expected_events = {
                                    (
                                        event.event_type.value,
                                        event.month,
                                        Decimal(event.amount),
                                        event.label,
                                        event.pool_name,
                                    )
                                    for event in expected_case.events
                                }
                                actual_events = {
                                    (
                                        event.event_type,
                                        event.month,
                                        Decimal(event.amount),
                                        event.label,
                                        pool_name_by_id.get(event.pool_id),
                                    )
                                    for event in events
                                }
                            except (InvalidOperation, TypeError, ValueError):
                                expected_events = set()
                                actual_events = {None}
                            if len(events) != len(expected_case.events) or actual_events != expected_events:
                                codes.append("FORECAST_NORMALIZED_ROWS_INVALID")
                        for event in events:
                            if event.event_type in {"contribution", "withdrawal"} and event.pool_id not in pool_ids:
                                codes.append("FORECAST_EVENT_POOL_INVALID")
                        adjustments = session.execute(
                            select(ForecastAdjustmentRow).where(ForecastAdjustmentRow.case_id == case.id)
                        ).scalars().all()
                        if snapshot is not None and expected_case is not None:
                            try:
                                expected_adjustments = {
                                    (
                                        adjustment.target_type.value,
                                        adjustment.target,
                                        adjustment.operation.value,
                                        Decimal(adjustment.value),
                                        adjustment.start_month,
                                        adjustment.end_month,
                                    )
                                    for adjustment in expected_case.adjustments
                                }
                                actual_adjustments = {
                                    (
                                        adjustment.target_type,
                                        adjustment.target,
                                        adjustment.operation,
                                        Decimal(adjustment.value),
                                        adjustment.start_month,
                                        adjustment.end_month,
                                    )
                                    for adjustment in adjustments
                                }
                            except (InvalidOperation, TypeError, ValueError):
                                expected_adjustments = set()
                                actual_adjustments = {None}
                            if (
                                len(adjustments) != len(expected_case.adjustments)
                                or actual_adjustments != expected_adjustments
                            ):
                                codes.append("FORECAST_NORMALIZED_ROWS_INVALID")
                        occupied: set[tuple[str, int]] = set()
                        for adjustment in adjustments:
                            end = adjustment.end_month or 36
                            for month in range(adjustment.start_month, end + 1):
                                key = (f"{adjustment.target_type}:{adjustment.target}", month)
                                if key in occupied:
                                    codes.append("FORECAST_ADJUSTMENT_OVERLAP")
                                occupied.add(key)
        return self._check("forecast_invariants", not codes, *sorted(set(codes)))

    def _net_worth_invariant_check(self) -> AuditCheck:
        codes: list[str] = []
        service = NetWorthService(self.database, self.settings)
        with self.database.session() as session:
            accounts = session.execute(select(NetWorthAccountRow)).scalars().all()
            identities = session.execute(select(NetWorthSnapshotRow)).scalars().all()
            revisions = session.execute(
                select(NetWorthSnapshotRevisionRow).order_by(NetWorthSnapshotRevisionRow.snapshot_date, NetWorthSnapshotRevisionRow.revision_number)
            ).scalars().all()
        for account in accounts:
            if account.side not in {"asset", "liability"}:
                codes.append("NET_WORTH_ACCOUNT_SIDE_INVALID")
            if account.side == "asset" and account.liquidity not in {"liquid", "restricted", "illiquid"}:
                codes.append("NET_WORTH_ASSET_LIQUIDITY_INVALID")
            if account.side == "liability" and account.liquidity is not None:
                codes.append("NET_WORTH_LIABILITY_LIQUIDITY_INVALID")
            if account.active_to and account.active_to < account.active_from:
                codes.append("NET_WORTH_ACCOUNT_DATES_INVALID")
        for identity in identities:
            identity_revisions = [row for row in revisions if row.snapshot_id == identity.id]
            numbers = [row.revision_number for row in identity_revisions]
            if numbers != list(range(1, identity.current_revision_number + 1)):
                codes.append("NET_WORTH_REVISION_SEQUENCE_INVALID")
            if not identity_revisions or identity_revisions[-1].revision_number != identity.current_revision_number:
                codes.append("NET_WORTH_CURRENT_REVISION_POINTER_INVALID")
        for row in revisions:
            try:
                snapshot = service._revision_from_row(row)
                active = set(snapshot.active_account_keys) or {
                    item.account_key for item in snapshot.balances
                }
                actual = {item.account_key for item in snapshot.balances}
                if actual != active:
                    codes.append("NET_WORTH_ACCOUNT_COVERAGE_INVALID")
                if any(item.snapshot_date != snapshot.snapshot_date for item in snapshot.balances):
                    codes.append("NET_WORTH_BALANCE_SNAPSHOT_DATE_INVALID")
                if any(item.valuation_date > snapshot.snapshot_date for item in snapshot.balances):
                    codes.append("NET_WORTH_FUTURE_VALUATION_DATE")
            except (TypeError, ValueError, InvalidOperation, NetWorthValidationError):
                codes.append("NET_WORTH_REVISION_INVALID")
        return self._check("net_worth_invariants", not codes, *sorted(set(codes)))

    def _apartment_invariant_check(self) -> AuditCheck:
        """Verify apartment study continuity and pinned forecast integrity."""

        codes: list[str] = []
        with self.database.session() as session:
            studies = session.execute(select(ApartmentStudyRow)).scalars().all()
            for study in studies:
                forecast = session.get(ForecastRow, study.forecast_id)
                forecast_revision = session.get(ForecastRevisionRow, study.forecast_revision_id)
                if (
                    forecast is None
                    or forecast_revision is None
                    or forecast_revision.forecast_id != study.forecast_id
                    or forecast_revision.revision_number != study.forecast_revision_number
                    or forecast_revision.assumption_hash != study.forecast_assumption_hash
                ):
                    codes.append("APARTMENT_PINNED_FORECAST_INVALID")
                revisions = session.execute(
                    select(ApartmentRevisionRow)
                    .where(ApartmentRevisionRow.study_id == study.id)
                    .order_by(ApartmentRevisionRow.revision_number)
                ).scalars().all()
                numbers = [row.revision_number for row in revisions]
                if numbers != list(range(1, study.current_revision_number + 1)):
                    codes.append("APARTMENT_REVISION_SEQUENCE_INVALID")
                if not revisions or revisions[-1].revision_number != study.current_revision_number:
                    codes.append("APARTMENT_CURRENT_REVISION_POINTER_INVALID")
                for revision in revisions:
                    if (
                        revision.forecast_id != study.forecast_id
                        or revision.forecast_revision_id != study.forecast_revision_id
                        or revision.forecast_revision_number != study.forecast_revision_number
                        or revision.forecast_assumption_hash != study.forecast_assumption_hash
                    ):
                        codes.append("APARTMENT_PINNED_FORECAST_INVALID")
                    try:
                        snapshot = ApartmentRevisionSnapshot.model_validate(json.loads(revision.assumptions_json))
                        if apartment_assumption_hash(snapshot) != revision.assumption_hash:
                            codes.append("APARTMENT_ASSUMPTION_HASH_INVALID")
                        if len(snapshot.alternatives) < 2 or len(snapshot.alternatives) > 4:
                            codes.append("APARTMENT_ALTERNATIVE_SET_INVALID")
                        if len({item.name.casefold() for item in snapshot.alternatives}) != len(snapshot.alternatives):
                            codes.append("APARTMENT_ALTERNATIVE_NAMES_INVALID")
                        for alternative in snapshot.alternatives:
                            if alternative.forecast_role.value not in {"conservative", "baseline", "optimistic"}:
                                codes.append("APARTMENT_FORECAST_ROLE_INVALID")
                            if alternative.purchase_month < 1 or alternative.purchase_month > 36:
                                codes.append("APARTMENT_PURCHASE_MONTH_INVALID")
                        codes.extend(self._apartment_normalized_row_codes(session, revision.id, snapshot))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        codes.append("APARTMENT_ASSUMPTIONS_INVALID")
        return self._check("apartment_invariants", not codes, *sorted(set(codes)))

    def _phase8_invariant_check(self) -> AuditCheck:
        """Check automation continuity, alert history, and summary hashes."""
        codes: list[str] = []
        with self.database.engine.connect() as connection:
            runs = connection.execute(text(
                "SELECT id, status, finished_at FROM automation_runs"
            )).fetchall()
            run_ids = {str(row[0]) for row in runs}
            outcomes = connection.execute(text(
                "SELECT run_id, status, sha256, managed_path FROM automation_file_outcomes"
            )).fetchall()
            if any(str(row[0]) not in run_ids for row in outcomes):
                codes.append("AUTOMATION_OUTCOME_RUN_REFERENCE_INVALID")
            for _run_id, status, digest, managed_path in outcomes:
                if status not in {"committed", "duplicate", "needs_review", "ready", "invalid", "unstable"}:
                    codes.append("AUTOMATION_OUTCOME_STATUS_INVALID")
                if digest and len(str(digest)) != 64:
                    codes.append("AUTOMATION_FILE_HASH_INVALID")
                if managed_path:
                    path = Path(str(managed_path))
                    if not path.is_absolute():
                        path = self.settings.data_root / path
                    if not path.is_file() or path.is_symlink():
                        codes.append("AUTOMATION_MANAGED_PATH_INVALID")
                    elif digest and _sha256(path) != str(digest):
                        codes.append("AUTOMATION_FILE_HASH_MISMATCH")

            preferences = connection.execute(text(
                "SELECT planning_scenario_id, planning_revision_id, forecast_id, "
                "forecast_revision_id, apartment_study_id, apartment_revision_id "
                "FROM automation_preferences WHERE id = 1"
            )).fetchone()
            if preferences:
                plan_id, plan_revision, forecast_id, forecast_revision, study_id, study_revision = preferences
                if plan_id and connection.execute(text("SELECT 1 FROM planning_scenarios WHERE id = :id"), {"id": plan_id}).fetchone() is None:
                    codes.append("PREFERENCE_SCENARIO_REFERENCE_INVALID")
                if plan_revision and connection.execute(text("SELECT 1 FROM planning_scenario_revisions WHERE id = :id"), {"id": plan_revision}).fetchone() is None:
                    codes.append("PREFERENCE_SCENARIO_REVISION_REFERENCE_INVALID")
                if forecast_id and connection.execute(text("SELECT 1 FROM savings_forecasts WHERE id = :id"), {"id": forecast_id}).fetchone() is None:
                    codes.append("PREFERENCE_FORECAST_REFERENCE_INVALID")
                if forecast_revision and connection.execute(text("SELECT 1 FROM savings_forecast_revisions WHERE id = :id"), {"id": forecast_revision}).fetchone() is None:
                    codes.append("PREFERENCE_FORECAST_REVISION_REFERENCE_INVALID")
                if study_id and connection.execute(text("SELECT 1 FROM apartment_studies WHERE id = :id"), {"id": study_id}).fetchone() is None:
                    codes.append("PREFERENCE_APARTMENT_REFERENCE_INVALID")
                if study_revision and connection.execute(text("SELECT 1 FROM apartment_study_revisions WHERE id = :id"), {"id": study_revision}).fetchone() is None:
                    codes.append("PREFERENCE_APARTMENT_REVISION_REFERENCE_INVALID")

            alerts = connection.execute(text(
                "SELECT fingerprint, algorithm_version, condition_type, subject_identity, currency, evidence_period "
                "FROM insight_alerts"
            )).fetchall()
            for fingerprint, algorithm, condition, subject, currency, period in alerts:
                calculated = hashlib.sha256(json.dumps({
                    "algorithm_version": algorithm,
                    "condition_type": condition,
                    "subject_identity": subject,
                    "currency": currency,
                    "evidence_period": period,
                }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                if calculated != fingerprint:
                    codes.append("ALERT_FINGERPRINT_INVALID")
            alert_ids = {str(row[0]) for row in connection.execute(text("SELECT id FROM insight_alerts")).fetchall()}
            event_alert_ids = {str(row[0]) for row in connection.execute(text("SELECT DISTINCT alert_id FROM insight_alert_events")).fetchall()}
            if not event_alert_ids.issubset(alert_ids):
                codes.append("ALERT_EVENT_REFERENCE_INVALID")

            summaries = connection.execute(text(
                "SELECT id, identity_id, revision_number, content_json, content_hash, contributor_provenance_json "
                "FROM monthly_summary_revisions"
            )).fetchall()
            summary_identity_ids = {str(row[0]) for row in connection.execute(text("SELECT id FROM monthly_summary_identities")).fetchall()}
            numbers: dict[str, list[int]] = {}
            for summary_id, identity_id, revision_number, content_json, content_hash, provenance_json in summaries:
                if str(identity_id) not in summary_identity_ids:
                    codes.append("SUMMARY_IDENTITY_REFERENCE_INVALID")
                numbers.setdefault(str(identity_id), []).append(int(revision_number))
                if hashlib.sha256(str(content_json).encode()).hexdigest() != str(content_hash):
                    codes.append("SUMMARY_CONTENT_HASH_INVALID")
                try:
                    content = json.loads(content_json)
                    expected_provenance = {
                        "algorithm_version": content.get("algorithm_version"),
                        "contributors": content.get("contributor_provenance", {}),
                        "anomalies": "category_anomalies",
                    }
                    if json.loads(provenance_json or "{}") != expected_provenance:
                        codes.append("SUMMARY_CONTRIBUTOR_PROVENANCE_INVALID")
                except (TypeError, ValueError, json.JSONDecodeError):
                    codes.append("SUMMARY_CONTENT_INVALID")
            for revision_numbers in numbers.values():
                if sorted(revision_numbers) != list(range(1, len(revision_numbers) + 1)):
                    codes.append("SUMMARY_REVISION_SEQUENCE_INVALID")

        for root in (self.settings.automation_processed_root, self.settings.automation_needs_review_root):
            if any(path.is_symlink() for path in root.rglob("*") if path.exists()):
                codes.append("AUTOMATION_MANAGED_SYMLINK")
        return self._check("phase8_invariants", not codes, *sorted(set(codes)))

    @staticmethod
    def _apartment_normalized_row_codes(session, revision_id: str, snapshot: ApartmentRevisionSnapshot) -> list[str]:
        codes: list[str] = []
        rows = session.execute(
            select(ApartmentAlternativeRow)
            .where(ApartmentAlternativeRow.revision_id == revision_id)
            .order_by(ApartmentAlternativeRow.name)
        ).scalars().all()
        if len(rows) != len(snapshot.alternatives):
            codes.append("APARTMENT_ALTERNATIVE_ROWS_INVALID")
        expected_by_name = {item.name.casefold(): item for item in snapshot.alternatives}
        actual_by_name = {row.name.casefold(): row for row in rows}
        if set(expected_by_name) != set(actual_by_name):
            codes.append("APARTMENT_NORMALIZED_ALTERNATIVES_INVALID")
        for name, expected in expected_by_name.items():
            row = actual_by_name.get(name)
            if row is None:
                continue
            try:
                scalar_match = (
                    row.forecast_role == expected.forecast_role.value
                    and row.purchase_month == expected.purchase_month
                    and Decimal(row.property_price) == expected.property_price
                    and Decimal(row.family_gift) == expected.family_gift
                    and row.equity_mode == expected.equity_requirement.mode
                    and Decimal(row.equity_value) == expected.equity_requirement.value
                    and Decimal(row.mortgage_principal) == expected.mortgage.principal
                    and Decimal(row.mortgage_annual_nominal_rate) == expected.mortgage.annual_nominal_rate
                    and row.mortgage_term_months == expected.mortgage.term_months
                    and bool(row.confirmed) == expected.confirmed
                )
            except (InvalidOperation, TypeError, ValueError):
                scalar_match = False
            if not scalar_match:
                codes.append("APARTMENT_NORMALIZED_ALTERNATIVE_INVALID")

            purchase_costs = session.execute(
                select(ApartmentPurchaseCostRow)
                .where(ApartmentPurchaseCostRow.alternative_id == row.id)
                .order_by(ApartmentPurchaseCostRow.label, ApartmentPurchaseCostRow.id)
            ).scalars().all()
            expected_costs = sorted((item.label, item.amount) for item in expected.purchase_costs)
            try:
                actual_costs = sorted((item.label, Decimal(item.amount)) for item in purchase_costs)
            except (InvalidOperation, TypeError, ValueError):
                actual_costs = []
            if actual_costs != expected_costs:
                codes.append("APARTMENT_NORMALIZED_PURCHASE_COSTS_INVALID")

            draws = session.execute(
                select(ApartmentPoolDrawRow)
                .where(ApartmentPoolDrawRow.alternative_id == row.id)
                .order_by(ApartmentPoolDrawRow.pool_name, ApartmentPoolDrawRow.id)
            ).scalars().all()
            expected_draws = sorted((item.pool_name or item.pool_id or "", item.amount) for item in expected.pool_draws)
            try:
                actual_draws = sorted((item.pool_name, Decimal(item.amount)) for item in draws)
            except (InvalidOperation, TypeError, ValueError):
                actual_draws = []
            if actual_draws != expected_draws:
                codes.append("APARTMENT_NORMALIZED_POOL_DRAWS_INVALID")

            stopped = session.execute(
                select(ApartmentStoppedHousingLineRow)
                .where(ApartmentStoppedHousingLineRow.alternative_id == row.id)
                .order_by(ApartmentStoppedHousingLineRow.source_item_id, ApartmentStoppedHousingLineRow.id)
            ).scalars().all()
            if [item.source_item_id for item in stopped] != sorted(expected.stopped_housing_line_ids):
                codes.append("APARTMENT_NORMALIZED_STOPPED_LINES_INVALID")

            housing = session.execute(
                select(ApartmentHousingCostRow)
                .where(ApartmentHousingCostRow.alternative_id == row.id)
                .order_by(ApartmentHousingCostRow.label, ApartmentHousingCostRow.id)
            ).scalars().all()
            expected_housing = sorted((item.label, item.amount) for item in expected.housing_costs)
            try:
                actual_housing = sorted((item.label, Decimal(item.amount)) for item in housing)
            except (InvalidOperation, TypeError, ValueError):
                actual_housing = []
            if actual_housing != expected_housing:
                codes.append("APARTMENT_NORMALIZED_HOUSING_COSTS_INVALID")
        return codes


def _statistics_total(value: str) -> int | None:
    try:
        data: dict[str, Any] = json.loads(value)
        return int(data["total_records"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


__all__ = ["AuditService"]
