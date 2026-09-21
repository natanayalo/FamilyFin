"""Apartment purchase planning on top of immutable Phase 5 forecasts.

This module owns the Phase 6 contracts' calculation and persistence boundary.
It deliberately keeps purchase funding out of ordinary household income and
expense metrics while asking :class:`ForecastEngine` to calculate the monthly
household overlay.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any

from sqlalchemy import desc, select

from family_finance.forecasting import (
    ForecastEngine,
    SavingsForecastService,
    _month_add,
)
from family_finance.forecasting import (
    assumption_hash as forecast_assumption_hash,
)
from family_finance.models import (
    ApartmentComparison,
    ApartmentComparisonRow,
    ApartmentDraft,
    ApartmentGuardrails,
    ApartmentMonthlyResult,
    ApartmentRevisionSnapshot,
    ApartmentRevisionSummary,
    ApartmentStudySummary,
    ForecastCapitalDraw,
    ForecastOverlay,
    ForecastOverlayExpense,
    ForecastRole,
    MortgageAssumption,
    MortgageScheduleRow,
    PlanningItemKind,
    PoolDrawInput,
    PurchaseAlternativeInput,
    PurchaseProjection,
    PurchaseReadiness,
)
from family_finance.persistence.db import Database, json_dumps, utc_now
from family_finance.persistence.models import (
    ApartmentAlternativeRow,
    ApartmentHousingCostRow,
    ApartmentPoolDrawRow,
    ApartmentPurchaseCostRow,
    ApartmentRevisionRow,
    ApartmentStoppedHousingLineRow,
    ApartmentStudyRow,
)

APARTMENT_POLICY_VERSION = "apartment-planning-v1"
MONEY_CENT = Decimal("0.01")
ZERO = Decimal(0)


class ApartmentValidationError(ValueError):
    """An apartment assumption or lifecycle operation is invalid."""


class StaleApartmentRevisionError(ApartmentValidationError):
    """A save was based on an older current apartment revision."""


ApartmentStaleRevisionError = StaleApartmentRevisionError


def _decimal_text(value: Decimal | str | float) -> str:
    number = Decimal(str(value))
    if not number.is_finite():
        raise ApartmentValidationError("Apartment money values must be finite")
    if number == 0:
        return "0"
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _round_cent(value: Decimal) -> Decimal:
    return value.quantize(MONEY_CENT, rounding=ROUND_HALF_EVEN)


def calculate_mortgage_schedule(
    mortgage: MortgageAssumption | Decimal | int | str,
    annual_nominal_rate: Decimal | int | str | None = None,
    term_months: int | None = None,
) -> list[MortgageScheduleRow]:
    """Return a complete cent-rounded fixed-rate amortization schedule.

    Passing a :class:`MortgageAssumption` is the preferred API.  The scalar
    form remains useful for callers that want to test the pure formula.
    """

    if isinstance(mortgage, MortgageAssumption):
        assumption = mortgage
    else:
        if annual_nominal_rate is None or term_months is None:
            raise ApartmentValidationError("Mortgage rate and term are required")
        assumption = MortgageAssumption(
            principal=Decimal(str(mortgage)),
            annual_nominal_rate=Decimal(str(annual_nominal_rate)),
            term_months=int(term_months),
        )
    principal = _round_cent(assumption.principal)
    with localcontext() as context:
        context.prec = 50
        monthly_rate = assumption.annual_nominal_rate / Decimal(12)
        if principal == ZERO:
            payment = ZERO
        elif monthly_rate == ZERO:
            payment = _round_cent(principal / Decimal(assumption.term_months))
        else:
            raw = principal * monthly_rate / (
                Decimal(1) - (Decimal(1) + monthly_rate) ** (-assumption.term_months)
            )
            payment = _round_cent(raw)

        remaining = principal
        schedule: list[MortgageScheduleRow] = []
        for period in range(1, assumption.term_months + 1):
            interest = _round_cent(remaining * monthly_rate)
            if period == assumption.term_months:
                # The final payment is deliberately adjusted to eliminate any
                # cent-rounding residual from the fixed payment stream.
                principal_paid = remaining
                final_payment = _round_cent(interest + principal_paid)
                remaining_after = ZERO
            else:
                principal_paid = _round_cent(payment - interest)
                principal_paid = max(principal_paid, ZERO)
                principal_paid = min(principal_paid, remaining)
                final_payment = _round_cent(interest + principal_paid)
                remaining_after = _round_cent(remaining - principal_paid)
            schedule.append(
                MortgageScheduleRow(
                    period=period,
                    payment=final_payment,
                    interest=interest,
                    principal=principal_paid,
                    remaining_principal=remaining_after,
                )
            )
            remaining = remaining_after
    return schedule


mortgage_schedule = calculate_mortgage_schedule
build_mortgage_schedule = calculate_mortgage_schedule


def canonical_apartment_assumption_payload(snapshot: ApartmentRevisionSnapshot) -> dict[str, Any]:
    """Produce an order-independent representation for the study hash."""

    payload = snapshot.model_dump(
        mode="python",
        exclude={
            "study_id",
            "revision_id",
            "revision_number",
            "assumption_hash",
            "created_at",
            "notes",
            "source_quality_acknowledged",
        },
    )

    def normalize(value: Any) -> Any:
        if isinstance(value, Decimal):
            return _decimal_text(value)
        if isinstance(value, dict):
            return {str(key): normalize(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if hasattr(value, "value"):
            return value.value
        return value

    payload = normalize(payload)
    payload["alternatives"] = sorted(
        payload.get("alternatives", []), key=lambda item: str(item.get("name", "")).casefold()
    )
    for alternative in payload["alternatives"]:
        alternative["purchase_costs"] = sorted(
            alternative.get("purchase_costs", []), key=lambda item: str(item.get("label", "")).casefold()
        )
        alternative["pool_draws"] = sorted(
            alternative.get("pool_draws", []),
            key=lambda item: str(item.get("pool_name") or item.get("pool_id") or "").casefold(),
        )
        alternative["housing_costs"] = sorted(
            alternative.get("housing_costs", []), key=lambda item: str(item.get("label", "")).casefold()
        )
        alternative["stopped_housing_line_ids"] = sorted(
            alternative.get("stopped_housing_line_ids", [])
        )
    return payload


def apartment_assumption_hash(snapshot: ApartmentRevisionSnapshot) -> str:
    encoded = json.dumps(
        canonical_apartment_assumption_payload(snapshot),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ApartmentPlanningService:
    """Create, project, persist, and restore immutable apartment studies."""

    def __init__(
        self,
        database: Database,
        forecast_service: SavingsForecastService | None = None,
        planning_service: Any | None = None,
    ) -> None:
        self.database = database
        if forecast_service is None:
            forecast_service = SavingsForecastService(database, planning_service=planning_service)
        self.forecasting = forecast_service
        self.planning = planning_service or forecast_service.planning
        self.engine = ForecastEngine()

    # -- study identity and revision history ----------------------------

    def list_studies(self, *, include_archived: bool = False) -> list[ApartmentStudySummary]:
        statement = select(ApartmentStudyRow).order_by(desc(ApartmentStudyRow.updated_at), ApartmentStudyRow.name)
        if not include_archived:
            statement = statement.where(ApartmentStudyRow.archived.is_(False))
        with self.database.session() as session:
            rows = session.execute(statement).scalars().all()
        return [self._summary(row) for row in rows]

    list_apartment_studies = list_studies
    list_apartment_plans = list_studies

    def get_study(self, study_id: str) -> ApartmentStudySummary:
        with self.database.session() as session:
            row = session.get(ApartmentStudyRow, str(study_id))
        if row is None:
            raise ApartmentValidationError(f"Apartment study {study_id} not found")
        return self._summary(row)

    study = get_study
    get = get_study
    get_apartment_study = get_study

    def list_revisions(self, study_id: str) -> list[ApartmentRevisionSummary]:
        with self.database.session() as session:
            rows = session.execute(
                select(ApartmentRevisionRow)
                .where(ApartmentRevisionRow.study_id == str(study_id))
                .order_by(ApartmentRevisionRow.revision_number)
            ).scalars().all()
        return [self._revision_summary(row) for row in rows]

    list_apartment_revisions = list_revisions

    def get_revision(self, study_id: str, revision_number: int | None = None) -> ApartmentRevisionSnapshot:
        summary = self.get_study(study_id)
        number = revision_number or summary.current_revision_number
        with self.database.session() as session:
            row = session.execute(
                select(ApartmentRevisionRow).where(
                    ApartmentRevisionRow.study_id == str(study_id),
                    ApartmentRevisionRow.revision_number == number,
                )
            ).scalar_one_or_none()
        if row is None:
            raise ApartmentValidationError(f"Apartment study revision {number} not found")
        try:
            payload = json.loads(row.assumptions_json)
            payload.update(
                {
                    "study_id": study_id,
                    "revision_id": row.id,
                    "revision_number": row.revision_number,
                    "assumption_hash": row.assumption_hash,
                    "created_at": _iso_datetime(row.created_at),
                    "source_quality_acknowledged": bool(row.source_quality_acknowledged),
                }
            )
            snapshot = ApartmentRevisionSnapshot.model_validate(payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ApartmentValidationError("Saved apartment assumptions are invalid") from exc
        if apartment_assumption_hash(snapshot) != row.assumption_hash:
            raise ApartmentValidationError("Saved apartment assumption hash is invalid")
        self._validate_pinned_forecast(snapshot)
        return snapshot

    revision = get_revision
    get_study_revision = get_revision

    # -- draft and save ---------------------------------------------------

    def project_draft(
        self,
        forecast_id: str,
        alternatives: Sequence[PurchaseAlternativeInput | dict[str, Any]],
        *,
        forecast_revision_number: int | None = None,
        guardrails: ApartmentGuardrails | dict[str, Any] | None = None,
        source_quality_acknowledged: bool = False,
        notes: str = "",
    ) -> ApartmentDraft:
        snapshot = self._build_snapshot(
            forecast_id,
            alternatives,
            forecast_revision_number=forecast_revision_number,
            guardrails=guardrails,
            source_quality_acknowledged=source_quality_acknowledged,
            notes=notes,
        )
        projections = [self._project_alternative(snapshot, alternative) for alternative in snapshot.alternatives]
        comparison = self._comparison(snapshot.currency, projections)
        source = self.forecasting.get_revision(snapshot.forecast_id, snapshot.forecast_revision_number)
        source_plan = self.planning.get_revision(
            self.forecasting.get_forecast(snapshot.forecast_id).scenario_id,
            source.source_revision_number,
        )
        return ApartmentDraft(
            projections=projections,
            comparison=comparison,
            assumption_hash=apartment_assumption_hash(snapshot),
            source_quality_warning=bool(source_plan.provisional),
        )

    draft_projection = project_draft
    project = project_draft

    def available_pool_balances(
        self,
        forecast_id: str,
        forecast_role: ForecastRole | str,
        purchase_month: int,
        *,
        forecast_revision_number: int | None = None,
    ) -> dict[str, Decimal]:
        """Return selected-case balances immediately before an apartment draw.

        This is intentionally a read-only helper for the UI: it runs the
        exact Phase 5 case through month-end return, contribution, withdrawal,
        and sweep order without applying any purchase overlay.
        """

        if not 1 <= int(purchase_month) <= 36:
            raise ApartmentValidationError("Purchase month must be between 1 and 36")
        forecast = self.forecasting.get_forecast(forecast_id)
        source = self.forecasting.get_revision(forecast_id, forecast_revision_number)
        role = ForecastRole(forecast_role)
        case = next((item for item in source.cases if item.role == role), None)
        if case is None:
            raise ApartmentValidationError(f"Forecast role {role.value} is not available")
        plan = self.planning.get_revision(forecast.scenario_id, source.source_revision_number)
        scenario = self.planning.get_scenario(forecast.scenario_id)
        projection = self.engine.project(
            plan,
            source.starting_pools,
            case,
            forecast_id=forecast_id,
            scenario_id=forecast.scenario_id,
            currency=forecast.currency,
            source_revision_id=source.source_revision_id,
            source_revision_number=source.source_revision_number,
            start_month=scenario.start_month,
            assumption_hash_value=source.assumption_hash,
        )
        return {
            item.pool_name: item.closing_balance
            for item in projection.months[int(purchase_month) - 1].pools
        }

    get_available_pool_balances = available_pool_balances

    def create_study(
        self,
        name: str,
        forecast_id: str,
        alternatives: Sequence[PurchaseAlternativeInput | dict[str, Any]],
        *,
        forecast_revision_number: int | None = None,
        guardrails: ApartmentGuardrails | dict[str, Any] | None = None,
        notes: str = "",
        source_quality_acknowledged: bool = False,
        acknowledge_provisional: bool | None = None,
        clone_of_study_id: str | None = None,
    ) -> ApartmentStudySummary:
        if acknowledge_provisional is not None:
            source_quality_acknowledged = acknowledge_provisional
        snapshot = self._build_snapshot(
            forecast_id,
            alternatives,
            forecast_revision_number=forecast_revision_number,
            guardrails=guardrails,
            source_quality_acknowledged=source_quality_acknowledged,
            notes=notes,
        )
        self._validate_save(snapshot)
        study_id = str(uuid.uuid4())
        now = utc_now()
        with self.database.write_session() as session:
            session.add(
                ApartmentStudyRow(
                    id=study_id,
                    name=self._require_name(name),
                    forecast_id=snapshot.forecast_id,
                    forecast_revision_id=snapshot.forecast_revision_id,
                    forecast_revision_number=snapshot.forecast_revision_number,
                    forecast_assumption_hash=snapshot.forecast_assumption_hash,
                    currency=snapshot.currency,
                    current_revision_number=1,
                    clone_of_study_id=clone_of_study_id,
                    archived=False,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            self._insert_revision(session, study_id, 1, snapshot, now)
        return self.get_study(study_id)

    create = create_study

    def save_revision(
        self,
        study_id: str,
        snapshot: ApartmentRevisionSnapshot | None = None,
        *,
        expected_revision_number: int | None = None,
        alternatives: Sequence[PurchaseAlternativeInput | dict[str, Any]] | None = None,
        guardrails: ApartmentGuardrails | dict[str, Any] | None = None,
        notes: str = "",
        source_quality_acknowledged: bool = False,
        acknowledge_provisional: bool | None = None,
    ) -> ApartmentRevisionSnapshot:
        current = self.get_study(study_id)
        expected = current.current_revision_number if expected_revision_number is None else expected_revision_number
        if snapshot is None:
            if alternatives is None:
                raise ApartmentValidationError("Save an apartment revision with alternatives")
            snapshot = self._build_snapshot(
                current.forecast_id,
                alternatives,
                forecast_revision_number=current.forecast_revision_number,
                guardrails=guardrails,
                source_quality_acknowledged=(
                    source_quality_acknowledged
                    if acknowledge_provisional is None
                    else acknowledge_provisional
                ),
                notes=notes,
            )
        else:
            snapshot = snapshot.model_copy(update={"study_id": study_id})
        self._validate_save(snapshot)
        if snapshot.forecast_id != current.forecast_id or snapshot.forecast_revision_id != current.forecast_revision_id:
            raise ApartmentValidationError(
                "An apartment study remains pinned to its original forecast revision; clone it to use another revision"
            )
        number = expected + 1
        now = utc_now()
        with self.database.write_session() as session:
            row = session.get(ApartmentStudyRow, str(study_id))
            if row is None:
                raise ApartmentValidationError(f"Apartment study {study_id} not found")
            if row.current_revision_number != expected:
                raise StaleApartmentRevisionError(
                    f"Apartment study {study_id} is at revision {row.current_revision_number}; expected {expected}"
                )
            self._insert_revision(session, study_id, number, snapshot, now)
            row.current_revision_number = number
            row.updated_at = now
        return self.get_revision(study_id, number)

    save_study_revision = save_revision

    def restore_revision(
        self,
        study_id: str,
        revision_number: int,
        *,
        expected_revision_number: int | None = None,
        notes: str = "Restored older apartment study revision",
        source_quality_acknowledged: bool = False,
    ) -> ApartmentRevisionSnapshot:
        snapshot = self.get_revision(study_id, revision_number)
        snapshot = snapshot.model_copy(
            update={"notes": notes, "source_quality_acknowledged": snapshot.source_quality_acknowledged or source_quality_acknowledged}
        )
        return self.save_revision(study_id, snapshot, expected_revision_number=expected_revision_number)

    restore_study_revision = restore_revision
    restore = restore_revision

    def clone_study(self, study_id: str, *, name: str | None = None) -> ApartmentStudySummary:
        source = self.get_study(study_id)
        snapshot = self.get_revision(study_id)
        return self.create_study(
            name or f"{source.name} (copy)",
            source.forecast_id,
            snapshot.alternatives,
            forecast_revision_number=source.forecast_revision_number,
            guardrails=snapshot.guardrails,
            notes=snapshot.notes,
            source_quality_acknowledged=snapshot.source_quality_acknowledged,
            clone_of_study_id=source.study_id,
        )

    clone = clone_study

    def archive_study(self, study_id: str, archived: bool = True) -> ApartmentStudySummary:
        with self.database.write_session() as session:
            row = session.get(ApartmentStudyRow, str(study_id))
            if row is None:
                raise ApartmentValidationError(f"Apartment study {study_id} not found")
            row.archived = bool(archived)
            row.updated_at = utc_now()
        return self.get_study(study_id)

    def unarchive_study(self, study_id: str) -> ApartmentStudySummary:
        return self.archive_study(study_id, False)

    archive = archive_study
    unarchive = unarchive_study

    # -- calculation ------------------------------------------------------

    def _project_alternative(
        self, snapshot: ApartmentRevisionSnapshot, alternative: PurchaseAlternativeInput
    ) -> PurchaseProjection:
        forecast = self.forecasting.get_forecast(snapshot.forecast_id)
        forecast_snapshot = self.forecasting.get_revision(
            snapshot.forecast_id, snapshot.forecast_revision_number
        )
        planning_revision = self.planning.get_revision(
            forecast.scenario_id, forecast_snapshot.source_revision_number
        )
        scenario = self.planning.get_scenario(forecast.scenario_id)
        case = next((item for item in forecast_snapshot.cases if item.role == alternative.forecast_role), None)
        if case is None:
            raise ApartmentValidationError(f"Forecast role {alternative.forecast_role.value} is not available")
        schedule = calculate_mortgage_schedule(alternative.mortgage)
        overlay = ForecastOverlay(
            closing_month=alternative.purchase_month,
            stopped_source_item_ids=list(alternative.stopped_housing_line_ids),
            post_move_expenses=[
                ForecastOverlayExpense(label=item.label, amount=item.amount)
                for item in alternative.housing_costs
            ],
            monthly_mortgage_payment=ZERO,
            mortgage_payments=[item.payment for item in schedule],
            capital_draws=[
                ForecastCapitalDraw(
                    pool_name=self._resolve_pool_name(draw, forecast_snapshot), amount=draw.amount
                )
                for draw in alternative.pool_draws
            ],
        )
        source_projection = self.engine.project(
            planning_revision,
            forecast_snapshot.starting_pools,
            case,
            forecast_id=snapshot.forecast_id,
            scenario_id=forecast.scenario_id,
            currency=snapshot.currency,
            source_revision_id=forecast_snapshot.source_revision_id,
            source_revision_number=forecast_snapshot.source_revision_number,
            start_month=scenario.start_month,
            provisional=planning_revision.provisional,
            issue_codes=planning_revision.issue_codes,
            assumption_hash_value=snapshot.forecast_assumption_hash,
            overlay=overlay,
        )
        purchase_month = source_projection.months[alternative.purchase_month - 1]
        available_pool_balances = {
            pool.pool_name: pool.closing_balance + pool.fulfilled_capital_draw
            for pool in purchase_month.pools
        }
        remaining_by_pool = {pool.pool_name: pool.closing_balance for pool in purchase_month.pools}
        purchase_cost_total = sum((item.amount for item in alternative.purchase_costs), ZERO)
        total_uses = alternative.property_price + purchase_cost_total
        required_equity = alternative.equity_requirement.minimum_amount(alternative.property_price)
        proposed_equity = alternative.property_price - alternative.mortgage.principal
        requested_draw_total = sum((item.amount for item in alternative.pool_draws), ZERO)
        fulfilled_draw_total = purchase_month.fulfilled_capital_draws
        total_sources = alternative.mortgage.principal + alternative.family_gift + fulfilled_draw_total
        funding_gap = max(total_uses - total_sources, ZERO)
        housing_total = sum((item.amount for item in alternative.housing_costs), ZERO)
        monthly = self._monthly_results(
            source_projection,
            planning_revision,
            scenario.start_month,
            alternative,
            housing_total,
            schedule,
            case.adjustments,
        )
        maximum_ratio, ratio_has_zero_income = self._housing_ratio(
            source_projection,
            alternative.purchase_month,
            housing_total,
            schedule,
            include_first_payment_for_month_36=alternative.purchase_month == 36,
        )
        equity_ok = proposed_equity >= required_equity
        source_ok = total_sources >= total_uses
        mortgage_ok = alternative.mortgage.principal <= alternative.property_price - required_equity
        liquidity = sum(remaining_by_pool.values(), ZERO)
        liquidity_ok = (
            snapshot.guardrails.minimum_remaining_liquidity is None
            or liquidity >= snapshot.guardrails.minimum_remaining_liquidity
        )
        ratio_ok = True
        if snapshot.guardrails.maximum_housing_cost_to_income_ratio is not None:
            ratio_ok = not ratio_has_zero_income and (
                maximum_ratio is not None
                and maximum_ratio <= snapshot.guardrails.maximum_housing_cost_to_income_ratio
            )
        failures: list[str] = []
        if not equity_ok:
            failures.append("Proposed equity is below the required minimum")
        if not source_ok:
            failures.append("Purchase sources do not fully cover purchase uses")
        if not mortgage_ok:
            failures.append("Mortgage principal exceeds the price after required equity")
        if not liquidity_ok:
            failures.append("Remaining liquidity is below the configured minimum")
        if not ratio_ok:
            failures.append("Housing cost to income ratio exceeds the configured guardrail")
        readiness = PurchaseReadiness(
            equity_requirement_met=equity_ok,
            sources_cover_uses=source_ok,
            mortgage_within_required_equity=mortgage_ok,
            minimum_liquidity_met=liquidity_ok,
            housing_ratio_guardrail_met=ratio_ok,
            ready=not failures,
            failures=failures,
        )
        return PurchaseProjection(
            alternative_name=alternative.name,
            forecast_role=alternative.forecast_role,
            purchase_month=alternative.purchase_month,
            purchase_price=alternative.property_price,
            purchase_costs=purchase_cost_total,
            total_uses=total_uses,
            proposed_equity=proposed_equity,
            required_equity=required_equity,
            mortgage_principal=alternative.mortgage.principal,
            family_gift=alternative.family_gift,
            requested_pool_draws=requested_draw_total,
            fulfilled_pool_draws=fulfilled_draw_total,
            total_sources=total_sources,
            funding_gap=funding_gap,
            available_pool_balances=available_pool_balances,
            remaining_liquidity_by_pool=remaining_by_pool,
            remaining_liquidity=liquidity,
            mortgage_schedule=schedule,
            total_interest=sum((item.interest for item in schedule), ZERO),
            total_repayment=sum((item.payment for item in schedule), ZERO),
            monthly=monthly,
            readiness=readiness,
            maximum_housing_ratio=maximum_ratio,
            worst_monthly_cash_flow=min((item.cash_after_sweep for item in monthly), default=ZERO),
            month_36_balance=source_projection.months[-1].ending_balance,
            source_projection=source_projection,
        )

    def _monthly_results(
        self,
        projection,
        planning_revision,
        scenario_start: date,
        alternative: PurchaseAlternativeInput,
        housing_total: Decimal,
        mortgage_schedule: Sequence[MortgageScheduleRow],
        adjustments,
    ) -> list[ApartmentMonthlyResult]:
        result: list[ApartmentMonthlyResult] = []
        for item in projection.months:
            post_move = item.month_number > alternative.purchase_month
            payment = self._mortgage_payment_for_month(
                mortgage_schedule, alternative.purchase_month, item.month_number
            )
            housing = (housing_total + payment) if post_move else ZERO
            removed = self._removed_housing_cost(
                planning_revision, scenario_start, item.month_number, item.month, alternative, adjustments
            )
            net_change = removed - housing if post_move else ZERO
            result.append(
                ApartmentMonthlyResult(
                    month_number=item.month_number,
                    month=item.month,
                    income=item.income,
                    expenses=item.expenses,
                    housing_cost=housing,
                    removed_housing_costs=removed,
                    net_cash_flow_change=net_change,
                    cash_after_sweep=item.cash_after_sweep,
                    ending_balance=item.ending_balance,
                    pools={pool.pool_name: pool.closing_balance for pool in item.pools},
                )
            )
        return result

    def _removed_housing_cost(
        self,
        revision,
        scenario_start: date,
        month_number: int,
        month: date,
        alternative: PurchaseAlternativeInput,
        adjustments,
    ) -> Decimal:
        if month_number <= alternative.purchase_month:
            return ZERO
        source_end = _month_add(scenario_start, 11)
        stopped = set(alternative.stopped_housing_line_ids)
        total = ZERO
        for item in revision.items:
            if item.id not in stopped or item.kind != PlanningItemKind.EXPENSE:
                continue
            if not ForecastEngine._occurs(item, month, scenario_start, source_end):
                continue
            amount = item.amount
            if item.frequency.value == "monthly":
                amount = ForecastEngine._adjusted_amount(item, amount, month_number, adjustments)
            total += amount
        return total

    def _housing_ratio(
        self,
        projection,
        purchase_month: int,
        housing_total: Decimal,
        mortgage_schedule: Sequence[MortgageScheduleRow],
        *,
        include_first_payment_for_month_36: bool,
    ) -> tuple[Decimal | None, bool]:
        ratios: list[Decimal] = []
        zero_income = False
        start = purchase_month + 1
        months = projection.months[start - 1 :]
        if include_first_payment_for_month_36 and purchase_month == 36:
            months = [projection.months[-1]]
        for month in months:
            housing = housing_total + self._mortgage_payment_for_month(
                mortgage_schedule, purchase_month, month.month_number
            )
            if purchase_month == 36 and month.month_number == 36:
                housing = housing_total + (
                    mortgage_schedule[0].payment if mortgage_schedule else ZERO
                )
            if month.income <= ZERO:
                if housing > ZERO:
                    zero_income = True
                continue
            ratios.append(housing / month.income)
        return (max(ratios) if ratios else (Decimal("Infinity") if zero_income else ZERO)), zero_income

    @staticmethod
    def _mortgage_payment_for_month(
        mortgage_schedule: Sequence[MortgageScheduleRow], purchase_month: int, month_number: int
    ) -> Decimal:
        period = month_number - purchase_month
        if period < 1 or period > len(mortgage_schedule):
            return ZERO
        return mortgage_schedule[period - 1].payment

    def _comparison(self, currency: str, projections: Sequence[PurchaseProjection]) -> ApartmentComparison:
        return ApartmentComparison(
            currency=currency,
            alternatives=[
                ApartmentComparisonRow(
                    alternative_name=item.alternative_name,
                    purchase_month=item.purchase_month,
                    purchase_price=item.purchase_price,
                    forecast_role=item.forecast_role,
                    mortgage_payment=item.mortgage_schedule[0].payment if item.mortgage_schedule else ZERO,
                    total_interest=item.total_interest,
                    closing_gap=item.funding_gap,
                    remaining_liquidity=item.remaining_liquidity,
                    maximum_housing_ratio=item.maximum_housing_ratio,
                    worst_monthly_cash_flow=item.worst_monthly_cash_flow,
                    month_36_balance=item.month_36_balance,
                )
                for item in projections
            ],
        )

    # -- normalization, validation, and persistence ---------------------

    def _build_snapshot(
        self,
        forecast_id: str,
        alternatives: Sequence[PurchaseAlternativeInput | dict[str, Any]],
        *,
        forecast_revision_number: int | None,
        guardrails: ApartmentGuardrails | dict[str, Any] | None,
        source_quality_acknowledged: bool,
        notes: str,
    ) -> ApartmentRevisionSnapshot:
        forecast = self.forecasting.get_forecast(forecast_id)
        source = self.forecasting.get_revision(forecast_id, forecast_revision_number)
        parsed = [
            item if isinstance(item, PurchaseAlternativeInput) else PurchaseAlternativeInput.model_validate(item)
            for item in alternatives
        ]
        snapshot = ApartmentRevisionSnapshot(
            forecast_id=forecast.forecast_id,
            forecast_revision_id=source.revision_id or "",
            forecast_revision_number=source.revision_number,
            forecast_assumption_hash=source.assumption_hash,
            currency=forecast.currency,
            policy_version=APARTMENT_POLICY_VERSION,
            source_quality_acknowledged=source_quality_acknowledged,
            guardrails=(
                guardrails
                if isinstance(guardrails, ApartmentGuardrails)
                else ApartmentGuardrails.model_validate(guardrails or {})
            ),
            alternatives=parsed,
            notes=notes,
        )
        self._normalize_alternative_line_refs(snapshot, forecast)
        self._validate_overfunding(snapshot)
        return snapshot

    def _normalize_alternative_line_refs(self, snapshot: ApartmentRevisionSnapshot, forecast) -> None:
        source = self.forecasting.get_revision(snapshot.forecast_id, snapshot.forecast_revision_number)
        planning_revision = self.planning.get_revision(forecast.scenario_id, source.source_revision_number)
        items_by_id = {item.id: item for item in planning_revision.items}
        item_ids_by_label = {item.label.casefold(): item.id for item in planning_revision.items}
        pools_by_name = {pool.name.casefold(): pool.name for pool in source.starting_pools}
        for alternative in snapshot.alternatives:
            normalized_stopped: list[str] = []
            for reference in alternative.stopped_housing_line_ids:
                item_id = reference if reference in items_by_id else item_ids_by_label.get(reference.casefold())
                if item_id is None:
                    raise ApartmentValidationError(f"Stopped housing line {reference!r} does not exist in the pinned plan")
                if items_by_id[item_id].kind != PlanningItemKind.EXPENSE:
                    raise ApartmentValidationError("Only expense planning lines may stop after moving")
                normalized_stopped.append(item_id)
            alternative.stopped_housing_line_ids = normalized_stopped
            normalized_draws: list[PoolDrawInput] = []
            for draw in alternative.pool_draws:
                reference = draw.pool_name or draw.pool_id or ""
                pool_name = pools_by_name.get(reference.casefold())
                if pool_name is None:
                    raise ApartmentValidationError(f"Pool draw references unknown forecast pool {reference!r}")
                normalized_draws.append(PoolDrawInput(pool_name=pool_name, amount=draw.amount))
            alternative.pool_draws = normalized_draws

    def _validate_save(self, snapshot: ApartmentRevisionSnapshot) -> None:
        self._validate_pinned_forecast(snapshot)
        missing = [item.name for item in snapshot.alternatives if not item.confirmed]
        if missing:
            raise ApartmentValidationError(
                "Saving is blocked until every apartment alternative is explicitly confirmed: "
                + ", ".join(missing)
            )
        source = self.forecasting.get_revision(snapshot.forecast_id, snapshot.forecast_revision_number)
        summary = self.forecasting.get_forecast(snapshot.forecast_id)
        plan = self.planning.get_revision(summary.scenario_id, source.source_revision_number)
        if plan.provisional and not snapshot.source_quality_acknowledged:
            raise ApartmentValidationError(
                "The pinned forecast has provisional source issues that require an acknowledgement"
            )
        self._validate_overfunding(snapshot)

    @staticmethod
    def _validate_overfunding(snapshot: ApartmentRevisionSnapshot) -> None:
        for alternative in snapshot.alternatives:
            purchase_cost_total = sum((item.amount for item in alternative.purchase_costs), ZERO)
            total_uses = alternative.property_price + purchase_cost_total
            requested_sources = alternative.mortgage.principal + alternative.family_gift + sum(
                (item.amount for item in alternative.pool_draws), ZERO
            )
            if requested_sources > total_uses:
                raise ApartmentValidationError(
                    f"Alternative {alternative.name!r} requests sources greater than total purchase uses"
                )

    def _validate_pinned_forecast(self, snapshot: ApartmentRevisionSnapshot) -> None:
        source = self.forecasting.get_revision(snapshot.forecast_id, snapshot.forecast_revision_number)
        if source.revision_id != snapshot.forecast_revision_id or source.assumption_hash != snapshot.forecast_assumption_hash:
            raise ApartmentValidationError("Apartment study is not pinned to the exact forecast revision and hash")
        if forecast_assumption_hash(source) != snapshot.forecast_assumption_hash:
            raise ApartmentValidationError("Pinned forecast assumption hash is invalid")

    def _resolve_pool_name(self, draw: PoolDrawInput, forecast_snapshot) -> str:
        reference = draw.pool_name or draw.pool_id or ""
        for pool in forecast_snapshot.starting_pools:
            if reference.casefold() in {pool.name.casefold(), str(pool.pool_id or "").casefold()}:
                return pool.name
        raise ApartmentValidationError(f"Pool draw references unknown forecast pool {reference!r}")

    def _insert_revision(self, session, study_id: str, number: int, snapshot: ApartmentRevisionSnapshot, now: str) -> None:
        digest = apartment_assumption_hash(snapshot)
        revision_id = str(uuid.uuid4())
        session.add(
            ApartmentRevisionRow(
                id=revision_id,
                study_id=study_id,
                revision_number=number,
                forecast_id=snapshot.forecast_id,
                forecast_revision_id=snapshot.forecast_revision_id,
                forecast_revision_number=snapshot.forecast_revision_number,
                forecast_assumption_hash=snapshot.forecast_assumption_hash,
                policy_version=snapshot.policy_version,
                assumption_hash=digest,
                assumptions_json=json_dumps(
                    snapshot.model_dump(
                        mode="json",
                        exclude={"study_id", "revision_id", "revision_number", "assumption_hash", "created_at"},
                    )
                ),
                notes=snapshot.notes,
                source_quality_acknowledged=snapshot.source_quality_acknowledged,
                created_at=now,
            )
        )
        session.flush()
        for alternative in snapshot.alternatives:
            alternative_id = str(uuid.uuid4())
            session.add(
                ApartmentAlternativeRow(
                    id=alternative_id,
                    revision_id=revision_id,
                    name=alternative.name,
                    forecast_role=alternative.forecast_role.value,
                    purchase_month=alternative.purchase_month,
                    property_price=_decimal_text(alternative.property_price),
                    family_gift=_decimal_text(alternative.family_gift),
                    equity_mode=alternative.equity_requirement.mode,
                    equity_value=_decimal_text(alternative.equity_requirement.value),
                    mortgage_principal=_decimal_text(alternative.mortgage.principal),
                    mortgage_annual_nominal_rate=_decimal_text(alternative.mortgage.annual_nominal_rate),
                    mortgage_term_months=alternative.mortgage.term_months,
                    confirmed=alternative.confirmed,
                )
            )
            session.flush()
            for item in alternative.purchase_costs:
                session.add(ApartmentPurchaseCostRow(id=str(uuid.uuid4()), alternative_id=alternative_id, label=item.label, amount=_decimal_text(item.amount)))
            for item in alternative.pool_draws:
                session.add(ApartmentPoolDrawRow(id=str(uuid.uuid4()), alternative_id=alternative_id, pool_name=item.pool_name or item.pool_id or "", amount=_decimal_text(item.amount)))
            for item_id in alternative.stopped_housing_line_ids:
                session.add(ApartmentStoppedHousingLineRow(id=str(uuid.uuid4()), alternative_id=alternative_id, source_item_id=item_id))
            for item in alternative.housing_costs:
                session.add(ApartmentHousingCostRow(id=str(uuid.uuid4()), alternative_id=alternative_id, label=item.label, amount=_decimal_text(item.amount)))

    @staticmethod
    def _summary(row: ApartmentStudyRow) -> ApartmentStudySummary:
        return ApartmentStudySummary(
            study_id=row.id,
            name=row.name,
            forecast_id=row.forecast_id,
            forecast_revision_id=row.forecast_revision_id,
            forecast_revision_number=row.forecast_revision_number,
            forecast_assumption_hash=row.forecast_assumption_hash,
            currency=row.currency,
            current_revision_number=row.current_revision_number,
            archived=bool(row.archived),
            clone_of_study_id=row.clone_of_study_id,
            created_at=_iso_datetime(row.created_at),
            updated_at=_iso_datetime(row.updated_at),
        )

    @staticmethod
    def _revision_summary(row: ApartmentRevisionRow) -> ApartmentRevisionSummary:
        return ApartmentRevisionSummary(
            revision_id=row.id,
            study_id=row.study_id,
            revision_number=row.revision_number,
            forecast_id=row.forecast_id,
            forecast_revision_id=row.forecast_revision_id,
            forecast_revision_number=row.forecast_revision_number,
            forecast_assumption_hash=row.forecast_assumption_hash,
            policy_version=row.policy_version,
            assumption_hash=row.assumption_hash,
            created_at=_iso_datetime(row.created_at),
            notes=row.notes,
        )

    @staticmethod
    def _require_name(name: str) -> str:
        name = str(name).strip()
        if not name or len(name) > 200:
            raise ApartmentValidationError("Apartment study names must be non-empty and at most 200 characters")
        return name


def _iso_datetime(value: str | None):
    from datetime import datetime

    return datetime.fromisoformat(value) if value else None


ApartmentService = ApartmentPlanningService
ApartmentPlanService = ApartmentPlanningService


__all__ = [
    "APARTMENT_POLICY_VERSION",
    "ApartmentPlanService",
    "ApartmentPlanningService",
    "ApartmentService",
    "ApartmentStaleRevisionError",
    "ApartmentValidationError",
    "StaleApartmentRevisionError",
    "apartment_assumption_hash",
    "build_mortgage_schedule",
    "calculate_mortgage_schedule",
    "canonical_apartment_assumption_payload",
    "mortgage_schedule",
]
