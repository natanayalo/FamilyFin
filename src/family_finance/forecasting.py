"""Deterministic local-only savings forecasting.

The engine in this module is deliberately free of database and Streamlit
concerns.  It accepts an immutable Phase 4 planning revision plus explicit
user-authored pools and cases, and returns one 36-month result.  Persistence
and lifecycle rules live in :class:`SavingsForecastService`.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any

from sqlalchemy import desc, select

from family_finance.models import (
    ForecastAdjustmentInput,
    ForecastAdjustmentOperation,
    ForecastCaseInput,
    ForecastComparison,
    ForecastComparisonCheckpoint,
    ForecastDraft,
    ForecastEventInput,
    ForecastEventType,
    ForecastMethodology,
    ForecastOverlay,
    ForecastPoolInput,
    ForecastPoolType,
    ForecastProjection,
    ForecastRevisionSnapshot,
    ForecastRole,
    ForecastRoutingInput,
    ForecastTargetType,
    MonthlyPoolResult,
    PlanningFrequency,
    PlanningItem,
    PlanningItemKind,
    PlanningRevision,
    TotalMonthlyResult,
)
from family_finance.persistence.db import Database, json_dumps, utc_now
from family_finance.persistence.models import (
    ForecastAdjustmentRow,
    ForecastCaseRow,
    ForecastEventRow,
    ForecastPoolRow,
    ForecastRevisionRow,
    ForecastRoutingRow,
    ForecastRow,
)

FORECAST_POLICY_VERSION = "savings-forecast-v1"
MONEY_CENT = Decimal("0.01")
ZERO = Decimal(0)
HORIZON_MONTHS = 36
CALCULATION_ORDER = [
    "Apply effective monthly return to each opening pool balance",
    "Add explicitly routed contributions",
    "Fulfil routed withdrawals up to the available pool balance",
    "Calculate household cash using fulfilled withdrawals",
    "Sweep positive remaining cash when the case enables a sweep",
    "Produce pool closing balances and the household ending balance",
]


class ForecastValidationError(ValueError):
    """A forecast assumption or projection violates the local policy."""


class StaleForecastRevisionError(ForecastValidationError):
    """A forecast save was based on an older current revision."""


ForecastStaleRevisionError = StaleForecastRevisionError


def _month_add(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _decimal_text(value: Decimal | str | float) -> str:
    number = Decimal(str(value))
    if not number.is_finite():
        raise ForecastValidationError("Forecast values must be finite")
    if number == 0:
        return "0"
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, (ForecastRole, ForecastPoolType, ForecastAdjustmentOperation, ForecastTargetType, ForecastEventType)):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def canonical_assumption_payload(snapshot: ForecastRevisionSnapshot) -> dict[str, Any]:
    """Return the stable, hashable representation of forecast assumptions."""

    data = snapshot.model_dump(
        mode="python",
        exclude={"forecast_id", "revision_id", "revision_number", "assumption_hash", "created_at", "notes", "provisional_acknowledged"},
    )
    normalized = _json_value(data)
    pool_id_to_name = {
        str(pool.get("pool_id")): str(pool.get("name"))
        for pool in normalized.get("starting_pools", [])
        if pool.get("pool_id")
    }
    for pool in normalized.get("starting_pools", []):
        pool.pop("pool_id", None)
    normalized["starting_pools"] = sorted(
        normalized.get("starting_pools", []),
        key=lambda pool: str(pool.get("name", "")).casefold(),
    )
    for case in normalized.get("cases", []):
        if case.get("sweep_pool_id"):
            case["sweep_pool_name"] = pool_id_to_name.get(
                str(case["sweep_pool_id"]), case.get("sweep_pool_id")
            )
        case.pop("sweep_pool_id", None)
        for route in case.get("routes", []):
            if route.get("pool_id"):
                route["pool_name"] = pool_id_to_name.get(str(route["pool_id"]), route["pool_id"])
            route.pop("pool_id", None)
        for event in case.get("events", []):
            if event.get("pool_id"):
                event["pool_name"] = pool_id_to_name.get(str(event["pool_id"]), event["pool_id"])
            event.pop("pool_id", None)
        case["routes"] = sorted(case.get("routes", []), key=lambda route: str(route.get("source_item_id", "")))
        case["adjustments"] = sorted(
            case.get("adjustments", []),
            key=lambda item: (str(item.get("target_type", "")), str(item.get("target", "")), int(item.get("start_month", 0))),
        )
        case["events"] = sorted(
            case.get("events", []),
            key=lambda item: (int(item.get("month", 0)), str(item.get("event_type", "")), str(item.get("label", ""))),
        )
    normalized["cases"] = sorted(normalized.get("cases", []), key=lambda case: str(case.get("role", "")))
    return normalized


def assumption_hash(snapshot: ForecastRevisionSnapshot) -> str:
    encoded = json.dumps(
        canonical_assumption_payload(snapshot),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def effective_monthly_rate(annual_return_rate: Decimal | str | float) -> Decimal:
    """Convert a fractional annual effective rate to a monthly rate."""

    annual = Decimal(str(annual_return_rate))
    if not annual.is_finite() or annual <= Decimal(-1):
        raise ForecastValidationError("Annual return rate must be finite and greater than -100 percent")
    with localcontext() as context:
        context.prec = 40
        rate = (Decimal(1) + annual) ** (Decimal(1) / Decimal(12)) - Decimal(1)
    return +rate


def _round_return(value: Decimal) -> Decimal:
    return value.quantize(MONEY_CENT, rounding=ROUND_HALF_EVEN)


class ForecastEngine:
    """Pure 36-month projection engine."""

    def __init__(self, *, policy_version: str = FORECAST_POLICY_VERSION) -> None:
        self.policy_version = policy_version

    def project(
        self,
        planning_revision: PlanningRevision,
        starting_pools: Sequence[ForecastPoolInput],
        case: ForecastCaseInput,
        *,
        forecast_id: str | None = None,
        scenario_id: str | None = None,
        currency: str = "ILS",
        source_revision_id: str | None = None,
        source_revision_number: int | None = None,
        start_month: date | None = None,
        provisional: bool = False,
        issue_codes: Sequence[str] = (),
        assumption_hash_value: str = "",
        overlay: ForecastOverlay | None = None,
    ) -> ForecastProjection:
        self.validate(planning_revision, starting_pools, case, overlay=overlay)
        scenario_id = scenario_id or planning_revision.scenario_id
        source_revision_id = source_revision_id or planning_revision.revision_id
        source_revision_number = source_revision_number or planning_revision.revision_number
        pool_ids = {pool.name: (pool.pool_id or pool.name) for pool in starting_pools}
        routes = self._routes(planning_revision.items, starting_pools, case.routes)
        monthly_rate = effective_monthly_rate(case.annual_return_rate)
        balances = {pool.name: pool.opening_balance for pool in starting_pools}
        source_start = start_month or min(
            (item.start_month or item.occurrence_month for item in planning_revision.items if item.start_month or item.occurrence_month),
            default=date(2000, 1, 1),
        )
        source_end = _month_add(source_start, 11)
        # The revision's scenario horizon is authoritative when there are no items.
        if planning_revision.items:
            starts = [item.start_month for item in planning_revision.items if item.start_month]
            if starts and start_month is None:
                source_start = min(starts)
                source_end = _month_add(source_start, 11)
        months: list[TotalMonthlyResult] = []
        first_shortfall: int | None = None
        for month_number in range(1, HORIZON_MONTHS + 1):
            month = _month_add(source_start, month_number - 1)
            income, expenses, explicit_contributions, requested_withdrawals = self._base_cash_flows(
                planning_revision.items,
                routes,
                case.adjustments,
                month_number,
                month,
                source_start,
                source_end,
                case.events,
                starting_pools,
                overlay,
            )
            pool_results: list[MonthlyPoolResult] = []
            available_after_return: dict[str, Decimal] = {}
            returns: dict[str, Decimal] = {}
            opening_balances = dict(balances)
            for pool in starting_pools:
                opening = opening_balances[pool.name]
                raw_return = _round_return(opening * monthly_rate)
                post_return = max(ZERO, opening + raw_return)
                applied_return = post_return - opening
                available_after_return[pool.name] = post_return
                returns[pool.name] = applied_return

            fulfilled_by_pool: dict[str, Decimal] = {}
            gaps_by_pool: dict[str, Decimal] = {}
            contributions_by_pool: dict[str, Decimal] = defaultdict(lambda: ZERO)
            for name, amount in explicit_contributions.items():
                contributions_by_pool[name] += amount
            for name, amount in requested_withdrawals.items():
                fulfilled = min(amount, available_after_return[name] + contributions_by_pool[name])
                fulfilled_by_pool[name] = fulfilled
                gaps_by_pool[name] = amount - fulfilled

            total_contributions = sum(contributions_by_pool.values(), ZERO)
            total_requested_withdrawals = sum(requested_withdrawals.values(), ZERO)
            total_fulfilled_withdrawals = sum(fulfilled_by_pool.values(), ZERO)
            total_gap = sum(gaps_by_pool.values(), ZERO)
            cash_before_sweep = income - expenses - total_contributions + total_fulfilled_withdrawals
            swept_surplus = ZERO
            swept_by_pool: dict[str, Decimal] = defaultdict(lambda: ZERO)
            if case.sweep_enabled and cash_before_sweep > ZERO:
                swept_surplus = cash_before_sweep
                sweep_name = self._resolve_pool_name(case.sweep_pool_name, case.sweep_pool_id, starting_pools)
                contributions_by_pool[sweep_name] += swept_surplus
                swept_by_pool[sweep_name] += swept_surplus
            cash_after_sweep = cash_before_sweep - swept_surplus

            # Apartment planning uses capital-only draws at the very end of
            # the selected month.  They therefore cannot be re-swept and do
            # not enter ordinary income, expense, or household cash metrics.
            requested_capital_by_pool: dict[str, Decimal] = defaultdict(lambda: ZERO)
            if overlay is not None and month_number == overlay.closing_month:
                for draw in overlay.capital_draws:
                    requested_capital_by_pool[draw.pool_name] += draw.amount
            fulfilled_capital_by_pool: dict[str, Decimal] = {}
            total_requested_capital = sum(requested_capital_by_pool.values(), ZERO)
            total_fulfilled_capital = ZERO

            for pool in starting_pools:
                closing = (
                    available_after_return[pool.name]
                    + contributions_by_pool[pool.name]
                    - fulfilled_by_pool.get(pool.name, ZERO)
                )
                closing = max(ZERO, closing)
                fulfilled_capital = min(
                    requested_capital_by_pool.get(pool.name, ZERO), closing
                )
                fulfilled_capital_by_pool[pool.name] = fulfilled_capital
                total_fulfilled_capital += fulfilled_capital
                closing = max(ZERO, closing - fulfilled_capital)
                pool_results.append(
                    MonthlyPoolResult(
                        month_number=month_number,
                        month=month,
                        pool_id=pool_ids[pool.name],
                        pool_name=pool.name,
                        pool_type=pool.pool_type,
                        opening_balance=opening_balances[pool.name],
                        estimated_return=returns[pool.name],
                        contributions=explicit_contributions.get(pool.name, ZERO),
                        swept_surplus=swept_by_pool.get(pool.name, ZERO),
                        requested_withdrawal=requested_withdrawals.get(pool.name, ZERO),
                        fulfilled_withdrawal=fulfilled_by_pool.get(pool.name, ZERO),
                    unmet_funding_gap=gaps_by_pool.get(pool.name, ZERO),
                    requested_capital_draw=requested_capital_by_pool.get(pool.name, ZERO),
                    fulfilled_capital_draw=fulfilled_capital,
                    closing_balance=closing,
                    )
                )
                balances[pool.name] = closing
            if total_gap > ZERO and first_shortfall is None:
                first_shortfall = month_number
            months.append(
                TotalMonthlyResult(
                    month_number=month_number,
                    month=month,
                    income=income,
                    expenses=expenses,
                    contributions=total_contributions,
                    requested_withdrawals=total_requested_withdrawals,
                    fulfilled_withdrawals=total_fulfilled_withdrawals,
                    unmet_funding_gap=total_gap,
                    swept_surplus=swept_surplus,
                    estimated_returns=sum(returns.values(), ZERO),
                    cash_before_sweep=cash_before_sweep,
                    cash_after_sweep=cash_after_sweep,
                    ending_balance=sum(balances.values(), ZERO),
                    requested_capital_draws=total_requested_capital,
                    fulfilled_capital_draws=total_fulfilled_capital,
                    pools=pool_results,
                )
            )
        methodology = ForecastMethodology(
            policy_version=self.policy_version,
            source_plan_revision_id=source_revision_id,
            source_plan_revision_number=source_revision_number,
            calculation_order=list(CALCULATION_ORDER),
        )
        return ForecastProjection(
            forecast_id=forecast_id,
            scenario_id=scenario_id,
            source_revision_id=source_revision_id,
            source_revision_number=source_revision_number,
            currency=currency,
            months=months,
            provisional=provisional,
            issue_codes=list(issue_codes),
            first_shortfall_month=first_shortfall,
            assumption_hash=assumption_hash_value,
            methodology=methodology,
        )

    calculate = project
    forecast = project

    def validate(
        self,
        planning_revision: PlanningRevision,
        starting_pools: Sequence[ForecastPoolInput],
        case: ForecastCaseInput,
        *,
        overlay: ForecastOverlay | None = None,
    ) -> None:
        if not starting_pools:
            raise ForecastValidationError("A forecast requires at least one starting pool")
        names = [pool.name.casefold() for pool in starting_pools]
        if len(set(names)) != len(names):
            raise ForecastValidationError("Forecast pool names must be unique")
        item_by_id = {item.id: item for item in planning_revision.items}
        saving_items = [
            item for item in planning_revision.items
            if item.kind in {PlanningItemKind.SAVINGS_CONTRIBUTION, PlanningItemKind.SAVINGS_WITHDRAWAL}
        ]
        routed_ids = {route.source_item_id for route in case.routes}
        if len(routed_ids) != len(case.routes):
            raise ForecastValidationError("Each savings item may route to exactly one pool per case")
        missing = [item.id or item.label for item in saving_items if item.id not in routed_ids]
        if missing:
            raise ForecastValidationError("Every savings contribution and withdrawal must route to one pool: " + ", ".join(missing))
        unknown = [route.source_item_id for route in case.routes if route.source_item_id not in item_by_id]
        if unknown:
            raise ForecastValidationError("Forecast routing references unknown planning item(s): " + ", ".join(unknown))
        for route in case.routes:
            item = item_by_id[route.source_item_id]
            if item.kind not in {PlanningItemKind.SAVINGS_CONTRIBUTION, PlanningItemKind.SAVINGS_WITHDRAWAL}:
                raise ForecastValidationError("Only savings contribution and withdrawal lines may be routed")
            self._resolve_pool_name(route.pool_name, route.pool_id, starting_pools)
        if case.sweep_enabled:
            self._resolve_pool_name(case.sweep_pool_name, case.sweep_pool_id, starting_pools)
        self._validate_adjustments(case.adjustments, planning_revision.items)
        for event in case.events:
            if event.event_type in {ForecastEventType.CONTRIBUTION, ForecastEventType.WITHDRAWAL}:
                self._resolve_pool_name(event.pool_name, event.pool_id, starting_pools)
        for pool in starting_pools:
            if pool.opening_balance < ZERO or not pool.opening_balance.is_finite():
                raise ForecastValidationError("Forecast opening balances must be finite and non-negative")
        if overlay is not None:
            item_by_id = {item.id: item for item in planning_revision.items}
            for item_id in overlay.stopped_source_item_ids:
                item = item_by_id.get(item_id)
                if item is None:
                    raise ForecastValidationError(
                        f"Forecast overlay references unknown planning item {item_id!r}"
                    )
                if item.kind != PlanningItemKind.EXPENSE:
                    raise ForecastValidationError(
                        "Forecast overlays may stop only expense planning lines"
                    )
            for draw in overlay.capital_draws:
                self._resolve_pool_name(draw.pool_name, None, starting_pools)

    @staticmethod
    def _validate_adjustments(
        adjustments: Sequence[ForecastAdjustmentInput],
        items: Sequence[PlanningItem] = (),
    ) -> None:
        occupied: set[tuple[str, int]] = set()
        for adjustment in adjustments:
            end = adjustment.end_month or HORIZON_MONTHS
            if end < adjustment.start_month:
                raise ForecastValidationError("Forecast adjustment end month cannot precede start month")
            if adjustment.operation == ForecastAdjustmentOperation.PERCENTAGE_CHANGE and adjustment.value <= -1:
                raise ForecastValidationError("Forecast percentage changes must be greater than -100 percent")
            affected_targets = [f"{adjustment.target_type.value}:{adjustment.target}"]
            if items:
                affected_targets = [
                    item.id
                    for item in items
                    if item.frequency == PlanningFrequency.MONTHLY
                    and item.kind in {PlanningItemKind.INCOME, PlanningItemKind.EXPENSE}
                    and (
                        (adjustment.target_type == ForecastTargetType.LINE and item.id == adjustment.target)
                        or (adjustment.target_type == ForecastTargetType.CATEGORY and item.category == adjustment.target)
                    )
                ] or affected_targets
            for month in range(adjustment.start_month, end + 1):
                for target in affected_targets:
                    key = (target, month)
                    if key in occupied:
                        raise ForecastValidationError("Overlapping forecast adjustments are not allowed for the same target and month")
                    occupied.add(key)

    @staticmethod
    def _resolve_pool_name(
        pool_name: str | None,
        pool_id: str | None,
        pools: Sequence[ForecastPoolInput],
    ) -> str:
        reference = pool_id or pool_name
        for pool in pools:
            if reference in {pool.name, pool.name.casefold(), pool.pool_id}:
                return pool.name
        raise ForecastValidationError(f"Forecast pool reference {reference!r} does not exist")

    def _routes(
        self,
        items: Sequence[PlanningItem],
        pools: Sequence[ForecastPoolInput],
        routes: Sequence[ForecastRoutingInput],
    ) -> dict[str, str]:
        result = {}
        for route in routes:
            result[route.source_item_id] = self._resolve_pool_name(route.pool_name, route.pool_id, pools)
        return result

    def _base_cash_flows(
        self,
        items: Sequence[PlanningItem],
        routes: dict[str, str],
        adjustments: Sequence[ForecastAdjustmentInput],
        month_number: int,
        month: date,
        source_start: date,
        source_end: date,
        events: Sequence[ForecastEventInput],
        pools: Sequence[ForecastPoolInput],
        overlay: ForecastOverlay | None = None,
    ) -> tuple[Decimal, Decimal, dict[str, Decimal], dict[str, Decimal]]:
        income = ZERO
        expenses = ZERO
        contributions: dict[str, Decimal] = defaultdict(lambda: ZERO)
        withdrawals: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for item in items:
            if not self._occurs(item, month, source_start, source_end):
                continue
            if (
                overlay is not None
                and month_number > overlay.closing_month
                and item.id in set(overlay.stopped_source_item_ids)
            ):
                continue
            amount = item.amount
            if item.frequency == PlanningFrequency.MONTHLY and item.kind in {PlanningItemKind.INCOME, PlanningItemKind.EXPENSE}:
                amount = self._adjusted_amount(item, amount, month_number, adjustments)
            if item.kind == PlanningItemKind.INCOME:
                income += amount
            elif item.kind == PlanningItemKind.EXPENSE:
                expenses += amount
            elif item.kind == PlanningItemKind.SAVINGS_CONTRIBUTION:
                contributions[routes[item.id]] += amount
            elif item.kind == PlanningItemKind.SAVINGS_WITHDRAWAL:
                withdrawals[routes[item.id]] += amount
        if overlay is not None and month_number > overlay.closing_month:
            expenses += sum((item.amount for item in overlay.post_move_expenses), ZERO)
            mortgage_period = month_number - overlay.closing_month
            if overlay.mortgage_payments:
                if mortgage_period <= len(overlay.mortgage_payments):
                    expenses += overlay.mortgage_payments[mortgage_period - 1]
            else:
                expenses += overlay.monthly_mortgage_payment
        for event in events:
            if event.month != month_number:
                continue
            if event.event_type == ForecastEventType.INCOME:
                income += event.amount
            elif event.event_type == ForecastEventType.EXPENSE:
                expenses += event.amount
            elif event.event_type == ForecastEventType.CONTRIBUTION:
                contributions[self._resolve_pool_name(event.pool_name, event.pool_id, pools)] += event.amount
            elif event.event_type == ForecastEventType.WITHDRAWAL:
                withdrawals[self._resolve_pool_name(event.pool_name, event.pool_id, pools)] += event.amount
        return income, expenses, contributions, withdrawals

    @staticmethod
    def _occurs(item: PlanningItem, month: date, source_start: date, source_end: date) -> bool:
        if item.frequency == PlanningFrequency.ONE_TIME:
            return item.occurrence_month == month
        if item.start_month is None or item.end_month is None:
            return False
        if month <= source_end:
            return item.start_month <= month <= item.end_month
        return item.start_month <= source_end <= item.end_month

    @staticmethod
    def _adjusted_amount(
        item: PlanningItem,
        base: Decimal,
        month_number: int,
        adjustments: Sequence[ForecastAdjustmentInput],
    ) -> Decimal:
        active = [
            adjustment
            for adjustment in adjustments
            if adjustment.start_month <= month_number <= (adjustment.end_month or HORIZON_MONTHS)
            and (
                (adjustment.target_type == ForecastTargetType.LINE and adjustment.target == item.id)
                or (
                    adjustment.target_type == ForecastTargetType.CATEGORY
                    and item.category is not None
                    and adjustment.target == item.category
                )
            )
        ]
        value = base
        for adjustment in active:
            if adjustment.operation == ForecastAdjustmentOperation.REPLACEMENT:
                value = adjustment.value
            elif adjustment.operation == ForecastAdjustmentOperation.FIXED_DELTA:
                value = base + adjustment.value
            else:
                value = base * (Decimal(1) + adjustment.value)
            if value < ZERO:
                raise ForecastValidationError(
                    f"Forecast adjustment produces a negative amount for {item.label} in month {month_number}"
                )
        return value


def compare_projections(projections: dict[ForecastRole, ForecastProjection], currency: str) -> ForecastComparison:
    checkpoints: dict[ForecastRole, list[ForecastComparisonCheckpoint]] = {}
    for role, projection in projections.items():
        role_checkpoints: list[ForecastComparisonCheckpoint] = []
        for horizon in (12, 24, 36):
            months = projection.months[:horizon]
            final = months[-1]
            role_checkpoints.append(
                ForecastComparisonCheckpoint(
                    horizon_month=horizon,
                    ending_balance=final.ending_balance,
                    contributions=sum((item.contributions for item in months), ZERO),
                    swept_surplus=sum((item.swept_surplus for item in months), ZERO),
                    withdrawals=sum((item.fulfilled_withdrawals for item in months), ZERO),
                    estimated_returns=sum((item.estimated_returns for item in months), ZERO),
                    funding_gap=sum((item.unmet_funding_gap for item in months), ZERO),
                )
            )
        checkpoints[role] = role_checkpoints
    return ForecastComparison(currency=currency, checkpoints=checkpoints)


def _iso_datetime(value: str | None):
    from datetime import datetime

    return datetime.fromisoformat(value) if value else None


class SavingsForecastService:
    """Persistence and lifecycle service for immutable savings forecasts."""

    def __init__(self, database: Database, planning_service: Any | None = None) -> None:
        self.database = database
        if planning_service is None:
            from family_finance.planning import PlanningService

            planning_service = PlanningService(database)
        self.planning = planning_service
        self.engine = ForecastEngine()

    # -- saved forecast identity and revision history ---------------------

    def list_forecasts(self, *, include_archived: bool = False):
        statement = select(ForecastRow).order_by(desc(ForecastRow.updated_at), ForecastRow.name)
        if not include_archived:
            statement = statement.where(ForecastRow.archived.is_(False))
        with self.database.session() as session:
            rows = session.execute(statement).scalars().all()
        return [self._summary(row) for row in rows]

    list_savings_forecasts = list_forecasts
    list_forecast = list_forecasts

    def get_forecast(self, forecast_id: str):
        with self.database.session() as session:
            row = session.get(ForecastRow, str(forecast_id))
        if row is None:
            raise ForecastValidationError(f"Forecast {forecast_id} not found")
        return self._summary(row)

    forecast = get_forecast
    get_savings_forecast = get_forecast

    def get_revision(self, forecast_id: str, revision_number: int | None = None) -> ForecastRevisionSnapshot:
        with self.database.session() as session:
            forecast = session.get(ForecastRow, str(forecast_id))
            if forecast is None:
                raise ForecastValidationError(f"Forecast {forecast_id} not found")
            number = revision_number or forecast.current_revision_number
            row = session.execute(
                select(ForecastRevisionRow).where(
                    ForecastRevisionRow.forecast_id == str(forecast_id),
                    ForecastRevisionRow.revision_number == number,
                )
            ).scalar_one_or_none()
        if row is None:
            raise ForecastValidationError(f"Forecast revision {number} not found")
        try:
            payload = json.loads(row.assumptions_json)
            payload["forecast_id"] = forecast_id
            payload["revision_id"] = row.id
            payload["revision_number"] = row.revision_number
            payload["assumption_hash"] = row.assumption_hash
            payload["created_at"] = _iso_datetime(row.created_at)
            snapshot = ForecastRevisionSnapshot.model_validate(payload)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ForecastValidationError("Saved forecast assumptions are invalid") from exc
        if assumption_hash(snapshot) != row.assumption_hash:
            raise ForecastValidationError("Saved forecast assumption hash is invalid")
        return snapshot

    revision = get_revision
    get_forecast_revision = get_revision

    def list_revisions(self, forecast_id: str):
        with self.database.session() as session:
            rows = session.execute(
                select(ForecastRevisionRow)
                .where(ForecastRevisionRow.forecast_id == str(forecast_id))
                .order_by(ForecastRevisionRow.revision_number)
            ).scalars().all()
        return [
            self._revision_summary(row)
            for row in rows
        ]

    list_forecast_revisions = list_revisions

    # -- create, draft, save, restore, clone, archive --------------------

    def create_forecast(
        self,
        name: str,
        scenario_id: str,
        starting_pools: Sequence[ForecastPoolInput | dict[str, Any]],
        cases: Sequence[ForecastCaseInput | dict[str, Any]] | dict[Any, ForecastCaseInput | dict[str, Any]],
        *,
        source_revision_number: int | None = None,
        notes: str = "",
        provisional_acknowledged: bool = False,
        acknowledge_provisional: bool | None = None,
        clone_of_forecast_id: str | None = None,
    ):
        snapshot = self._build_snapshot(
            scenario_id,
            starting_pools,
            cases,
            source_revision_number=source_revision_number,
            notes=notes,
            provisional_acknowledged=(
                provisional_acknowledged if acknowledge_provisional is None else acknowledge_provisional
            ),
        )
        self._validate_save_acknowledgements(snapshot)
        self._validate_snapshot(snapshot)
        forecast_id = str(uuid.uuid4())
        now = utc_now()
        with self.database.write_session() as session:
            session.add(
                ForecastRow(
                    id=forecast_id,
                    name=self._require_name(name),
                    scenario_id=snapshot.scenario_id,
                    source_revision_id=snapshot.source_revision_id,
                    source_revision_number=snapshot.source_revision_number,
                    currency=snapshot.currency,
                    horizon_months=snapshot.horizon_months,
                    current_revision_number=1,
                    clone_of_forecast_id=clone_of_forecast_id,
                    archived=False,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            self._insert_revision(session, forecast_id, 1, snapshot, now)
        return self.get_forecast(forecast_id)

    create = create_forecast

    def project_draft(
        self,
        scenario_id: str,
        starting_pools: Sequence[ForecastPoolInput | dict[str, Any]],
        cases: Sequence[ForecastCaseInput | dict[str, Any]] | dict[Any, ForecastCaseInput | dict[str, Any]],
        *,
        source_revision_number: int | None = None,
        forecast_id: str | None = None,
        notes: str = "",
        provisional_acknowledged: bool = False,
    ) -> ForecastDraft:
        snapshot = self._build_snapshot(
            scenario_id,
            starting_pools,
            cases,
            source_revision_number=source_revision_number,
            notes=notes,
            provisional_acknowledged=provisional_acknowledged,
        )
        projections: dict[ForecastRole, ForecastProjection] = {}
        for case in snapshot.cases:
            projections[case.role] = self.engine.project(
                self.planning.get_revision(snapshot.scenario_id, snapshot.source_revision_number),
                snapshot.starting_pools,
                case,
                forecast_id=forecast_id,
                scenario_id=snapshot.scenario_id,
                currency=snapshot.currency,
                source_revision_id=snapshot.source_revision_id,
                source_revision_number=snapshot.source_revision_number,
                start_month=self.planning.get_scenario(snapshot.scenario_id).start_month,
                provisional=self.planning.get_revision(snapshot.scenario_id, snapshot.source_revision_number).provisional,
                issue_codes=self.planning.get_revision(snapshot.scenario_id, snapshot.source_revision_number).issue_codes,
                assumption_hash_value=assumption_hash(snapshot),
            )
        return ForecastDraft(
            projections=projections,
            comparison=compare_projections(projections, snapshot.currency),
            assumption_hash=assumption_hash(snapshot),
        )

    project = project_draft

    def save_revision(
        self,
        forecast_id: str,
        snapshot: ForecastRevisionSnapshot | None = None,
        *legacy_args,
        expected_revision_number: int | None = None,
        starting_pools: Sequence[ForecastPoolInput | dict[str, Any]] | None = None,
        cases: Sequence[ForecastCaseInput | dict[str, Any]] | dict[Any, ForecastCaseInput | dict[str, Any]] | None = None,
        source_revision_number: int | None = None,
        notes: str = "",
        provisional_acknowledged: bool = False,
        acknowledge_provisional: bool | None = None,
    ) -> ForecastRevisionSnapshot:
        if isinstance(snapshot, int):
            # Phase 4 callers commonly pass ``(id, expected, items)``.  Keep
            # the equivalent positional shape available for forecast callers
            # while the typed snapshot form remains the preferred API.
            if expected_revision_number is None:
                expected_revision_number = snapshot
            snapshot = None
            if legacy_args and isinstance(legacy_args[0], ForecastRevisionSnapshot):
                snapshot = legacy_args[0]
                legacy_args = legacy_args[1:]
            elif legacy_args:
                starting_pools = legacy_args[0]
            if len(legacy_args) > 1:
                cases = legacy_args[1]
            if len(legacy_args) > 2:
                raise TypeError("save_revision received too many positional arguments")
        current = self.get_forecast(forecast_id)
        expected = current.current_revision_number if expected_revision_number is None else expected_revision_number
        if snapshot is None:
            if starting_pools is None or cases is None:
                raise ForecastValidationError("Save a forecast revision with starting_pools and cases")
            snapshot = self._build_snapshot(
                current.scenario_id,
                starting_pools,
                cases,
                source_revision_number=source_revision_number or current.source_revision_number,
                notes=notes,
                provisional_acknowledged=(
                    provisional_acknowledged if acknowledge_provisional is None else acknowledge_provisional
                ),
            )
        else:
            snapshot = self._normalize_snapshot(snapshot)
        self._validate_save_acknowledgements(snapshot)
        self._validate_snapshot(snapshot)
        if snapshot.scenario_id != current.scenario_id:
            raise ForecastValidationError("A forecast remains linked to its original planning scenario")
        if snapshot.source_revision_id != current.source_revision_id or snapshot.source_revision_number != current.source_revision_number:
            raise ForecastValidationError("A forecast remains pinned to its original planning revision; clone it to use another revision")
        source = self.planning.get_revision(current.scenario_id, current.source_revision_number)
        if source.revision_id != current.source_revision_id:
            raise ForecastValidationError("The pinned planning revision no longer matches the saved source link")
        number = expected + 1
        now = utc_now()
        with self.database.write_session() as session:
            row = session.get(ForecastRow, str(forecast_id))
            if row is None:
                raise ForecastValidationError(f"Forecast {forecast_id} not found")
            if row.current_revision_number != expected:
                raise StaleForecastRevisionError(
                    f"Forecast {forecast_id} is at revision {row.current_revision_number}; expected {expected}"
                )
            self._insert_revision(session, forecast_id, number, snapshot, now)
            row.current_revision_number = number
            row.updated_at = now
        return self.get_revision(forecast_id, number)

    def restore_revision(
        self,
        forecast_id: str,
        revision_number: int,
        *,
        expected_revision_number: int | None = None,
        notes: str = "Restored older forecast revision",
        provisional_acknowledged: bool = False,
    ) -> ForecastRevisionSnapshot:
        snapshot = self.get_revision(forecast_id, revision_number)
        snapshot.notes = notes
        if snapshot.provisional_acknowledged is False:
            snapshot.provisional_acknowledged = provisional_acknowledged
        return self.save_revision(
            forecast_id,
            snapshot,
            expected_revision_number=expected_revision_number,
        )

    restore_forecast_revision = restore_revision

    def clone_forecast(self, forecast_id: str, *, name: str | None = None):
        source = self.get_forecast(forecast_id)
        snapshot = self.get_revision(forecast_id)
        snapshot.forecast_id = None
        return self.create_forecast(
            name or f"{source.name} (copy)",
            source.scenario_id,
            snapshot.starting_pools,
            snapshot.cases,
            source_revision_number=source.source_revision_number,
            notes=snapshot.notes,
            provisional_acknowledged=snapshot.provisional_acknowledged,
            clone_of_forecast_id=source.forecast_id,
        )

    clone = clone_forecast

    def archive_forecast(self, forecast_id: str, archived: bool = True):
        with self.database.write_session() as session:
            row = session.get(ForecastRow, str(forecast_id))
            if row is None:
                raise ForecastValidationError(f"Forecast {forecast_id} not found")
            row.archived = bool(archived)
            row.updated_at = utc_now()
        return self.get_forecast(forecast_id)

    def unarchive_forecast(self, forecast_id: str):
        return self.archive_forecast(forecast_id, False)

    archive = archive_forecast
    save_forecast_revision = save_revision

    # -- conversion and validation ---------------------------------------

    def _build_snapshot(
        self,
        scenario_id: str,
        starting_pools: Sequence[ForecastPoolInput | dict[str, Any]],
        cases: Sequence[ForecastCaseInput | dict[str, Any]] | dict[Any, ForecastCaseInput | dict[str, Any]],
        *,
        source_revision_number: int | None,
        notes: str,
        provisional_acknowledged: bool,
    ) -> ForecastRevisionSnapshot:
        scenario = self.planning.get_scenario(scenario_id)
        revision = self.planning.get_revision(scenario_id, source_revision_number)
        if isinstance(cases, dict):
            parsed_cases = []
            for role, value in cases.items():
                payload = value.model_dump(mode="python") if isinstance(value, ForecastCaseInput) else dict(value)
                payload.setdefault("role", role)
                parsed_cases.append(ForecastCaseInput.model_validate(payload))
        else:
            parsed_cases = [value if isinstance(value, ForecastCaseInput) else ForecastCaseInput.model_validate(value) for value in cases]
        snapshot = ForecastRevisionSnapshot(
            scenario_id=scenario.scenario_id,
            source_revision_id=revision.revision_id,
            source_revision_number=revision.revision_number,
            currency=scenario.currency,
            policy_version=FORECAST_POLICY_VERSION,
            provisional_acknowledged=provisional_acknowledged,
            starting_pools=[
                value if isinstance(value, ForecastPoolInput) else ForecastPoolInput.model_validate(value)
                for value in starting_pools
            ],
            cases=parsed_cases,
            notes=notes,
        )
        return self._normalize_snapshot(snapshot)

    @staticmethod
    def _normalize_snapshot(snapshot: ForecastRevisionSnapshot) -> ForecastRevisionSnapshot:
        pools_by_ref: dict[str, str] = {}
        normalized_pools: list[ForecastPoolInput] = []
        for pool in snapshot.starting_pools:
            pools_by_ref[pool.name.casefold()] = pool.name
            pools_by_ref[pool.name] = pool.name
            if pool.pool_id:
                pools_by_ref[pool.pool_id] = pool.name
            normalized_pools.append(
                ForecastPoolInput(
                    name=pool.name,
                    pool_type=pool.pool_type,
                    opening_balance=pool.opening_balance,
                    as_of_date=pool.as_of_date,
                )
            )
        normalized_cases: list[ForecastCaseInput] = []
        for case in snapshot.cases:
            def resolve(name: str | None, pool_id: str | None) -> str | None:
                if name is None and pool_id is None:
                    return None
                key = pool_id or name or ""
                result = pools_by_ref.get(key, pools_by_ref.get(key.casefold()))
                if result is None:
                    raise ForecastValidationError(f"Forecast pool reference {key!r} does not exist")
                return result

            normalized_cases.append(
                ForecastCaseInput(
                    role=case.role,
                    annual_return_rate=case.annual_return_rate,
                    routes=[
                        ForecastRoutingInput(
                            source_item_id=route.source_item_id,
                            pool_name=resolve(route.pool_name, route.pool_id),
                        )
                        for route in case.routes
                    ],
                    sweep_enabled=case.sweep_enabled,
                    sweep_pool_name=resolve(case.sweep_pool_name, case.sweep_pool_id),
                    adjustments=case.adjustments,
                    events=[
                        ForecastEventInput(
                            event_type=event.event_type,
                            month=event.month,
                            amount=event.amount,
                            label=event.label,
                            pool_name=resolve(event.pool_name, event.pool_id),
                        )
                        for event in case.events
                    ],
                    confirmed=case.confirmed,
                )
            )
        return snapshot.model_copy(update={"starting_pools": normalized_pools, "cases": normalized_cases})

    def _validate_save_acknowledgements(self, snapshot: ForecastRevisionSnapshot) -> None:
        missing = [case.role.value for case in snapshot.cases if not case.confirmed]
        if missing:
            raise ForecastValidationError("Saving is blocked until every forecast case is explicitly confirmed: " + ", ".join(missing))
        source = self.planning.get_revision(snapshot.scenario_id, snapshot.source_revision_number)
        if source.provisional and not snapshot.provisional_acknowledged:
            raise ForecastValidationError("The provisional source planning revision requires an additional acknowledgement")

    def _validate_snapshot(self, snapshot: ForecastRevisionSnapshot) -> None:
        revision = self.planning.get_revision(snapshot.scenario_id, snapshot.source_revision_number)
        if revision.revision_id != snapshot.source_revision_id:
            raise ForecastValidationError("Forecast source revision is not the exact selected planning revision")
        scenario = self.planning.get_scenario(snapshot.scenario_id)
        for case in snapshot.cases:
            self.engine.project(
                revision,
                snapshot.starting_pools,
                case,
                scenario_id=snapshot.scenario_id,
                currency=snapshot.currency,
                source_revision_id=snapshot.source_revision_id,
                source_revision_number=snapshot.source_revision_number,
                start_month=scenario.start_month,
            )

    @staticmethod
    def _require_name(name: str) -> str:
        name = str(name).strip()
        if not name or len(name) > 200:
            raise ForecastValidationError("Forecast name must be non-empty and at most 200 characters")
        return name

    @staticmethod
    def _summary(row: ForecastRow):
        from family_finance.models import ForecastSummary

        return ForecastSummary(
            forecast_id=row.id,
            name=row.name,
            scenario_id=row.scenario_id,
            source_revision_id=row.source_revision_id,
            source_revision_number=row.source_revision_number,
            currency=row.currency,
            horizon_months=row.horizon_months,
            current_revision_number=row.current_revision_number,
            archived=bool(row.archived),
            clone_of_forecast_id=row.clone_of_forecast_id,
            created_at=_iso_datetime(row.created_at),
            updated_at=_iso_datetime(row.updated_at),
        )

    @staticmethod
    def _revision_summary(row: ForecastRevisionRow):
        from family_finance.models import ForecastRevisionSummary

        return ForecastRevisionSummary(
            revision_id=row.id,
            forecast_id=row.forecast_id,
            revision_number=row.revision_number,
            source_revision_id=row.source_revision_id,
            source_revision_number=row.source_revision_number,
            policy_version=row.policy_version,
            assumption_hash=row.assumption_hash,
            created_at=_iso_datetime(row.created_at),
            notes=row.notes,
        )

    def _insert_revision(self, session, forecast_id: str, revision_number: int, snapshot: ForecastRevisionSnapshot, now: str) -> None:
        snapshot = self._normalize_snapshot(snapshot)
        source = self.planning.get_revision(snapshot.scenario_id, snapshot.source_revision_number)
        if source.revision_id != snapshot.source_revision_id:
            raise ForecastValidationError("Forecast source revision is not the exact selected planning revision")
        digest = assumption_hash(snapshot)
        revision_id = str(uuid.uuid4())
        session.add(
            ForecastRevisionRow(
                id=revision_id,
                forecast_id=forecast_id,
                revision_number=revision_number,
                source_revision_id=snapshot.source_revision_id,
                source_revision_number=snapshot.source_revision_number,
                policy_version=snapshot.policy_version,
                assumption_hash=digest,
                assumptions_json=json_dumps(
                    snapshot.model_dump(
                        mode="json",
                        exclude={"forecast_id", "revision_id", "revision_number", "assumption_hash", "created_at"},
                    )
                ),
                notes=snapshot.notes,
                created_at=now,
            )
        )
        session.flush()
        for case in snapshot.cases:
            case_id = str(uuid.uuid4())
            session.add(
                ForecastCaseRow(
                    id=case_id,
                    revision_id=revision_id,
                    role=case.role.value,
                    annual_return_rate=_decimal_text(case.annual_return_rate),
                    sweep_enabled=case.sweep_enabled,
                    sweep_pool_id=None,
                    confirmed=case.confirmed,
                )
            )
            session.flush()
            pool_ids: dict[str, str] = {}
            for pool in snapshot.starting_pools:
                pool_id = str(uuid.uuid4())
                pool_ids[pool.name] = pool_id
                session.add(
                    ForecastPoolRow(
                        id=pool_id,
                        case_id=case_id,
                        name=pool.name,
                        pool_type=pool.pool_type.value,
                        opening_balance=_decimal_text(pool.opening_balance),
                        as_of_date=pool.as_of_date.isoformat(),
                    )
                )
            session.flush()
            if case.sweep_enabled:
                case_row = session.get(ForecastCaseRow, case_id)
                case_row.sweep_pool_id = pool_ids[case.sweep_pool_name or ""]
            for route in case.routes:
                session.add(
                    ForecastRoutingRow(
                        id=str(uuid.uuid4()),
                        case_id=case_id,
                        source_item_id=route.source_item_id,
                        pool_id=pool_ids[route.pool_name or ""],
                    )
                )
            for adjustment in case.adjustments:
                session.add(
                    ForecastAdjustmentRow(
                        id=str(uuid.uuid4()),
                        case_id=case_id,
                        target_type=adjustment.target_type.value,
                        target=adjustment.target,
                        operation=adjustment.operation.value,
                        value=_decimal_text(adjustment.value),
                        start_month=adjustment.start_month,
                        end_month=adjustment.end_month,
                    )
                )
            for event in case.events:
                session.add(
                    ForecastEventRow(
                        id=str(uuid.uuid4()),
                        case_id=case_id,
                        event_type=event.event_type.value,
                        month=event.month,
                        amount=_decimal_text(event.amount),
                        label=event.label,
                        pool_id=pool_ids.get(event.pool_name or ""),
                    )
                )


ForecastService = SavingsForecastService
ForecastRevisionStaleError = StaleForecastRevisionError


__all__ = [
    "CALCULATION_ORDER",
    "FORECAST_POLICY_VERSION",
    "ForecastEngine",
    "ForecastRevisionStaleError",
    "ForecastService",
    "ForecastStaleRevisionError",
    "ForecastValidationError",
    "SavingsForecastService",
    "StaleForecastRevisionError",
    "assumption_hash",
    "canonical_assumption_payload",
    "compare_projections",
    "effective_monthly_rate",
]
