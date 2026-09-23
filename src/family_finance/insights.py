"""Deterministic, non-persisted dashboard insight detectors."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import pairwise
from statistics import median
from uuid import uuid4

from sqlalchemy import select

from family_finance.audit import AuditService
from family_finance.classification import ClassificationService
from family_finance.config import Settings
from family_finance.metrics import MetricsService
from family_finance.models import (
    AutomationPreferences,
    EconomicClass,
    InsightAlert,
    MonthlyMetrics,
    MonthlySummaryRevision,
    PotentialRecurringSpending,
    UnusualCategorySpending,
)
from family_finance.persistence.db import Database, json_dumps, utc_now
from family_finance.persistence.models import (
    AutomationPreferencesRow,
    ImportBatchRow,
    InsightAlertEventRow,
    InsightAlertRow,
    MonthlySummaryIdentityRow,
    MonthlySummaryRevisionRow,
)
from family_finance.persistence.repositories import FinancialRepository

_SPACE_RE = re.compile(r"\s+")


def _normalized_description(value: str) -> str:
    return _SPACE_RE.sub(" ", value.strip().casefold())


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _month_shift(month: date, offset: int) -> date:
    year = month.year + (month.month - 1 + offset) // 12
    number = (month.month - 1 + offset) % 12 + 1
    return date(year, number, 1)


class InsightsService:
    def __init__(
        self,
        database: Database,
        *,
        classifier: ClassificationService | None = None,
        metrics: MetricsService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.database = database
        self.settings = settings or Settings.from_environment()
        self.repository = FinancialRepository(database)
        self.classifier = classifier or ClassificationService(database)
        self.metrics = metrics or MetricsService(database, classifier=self.classifier)

    @property
    def algorithm_version(self) -> str:
        return self.settings.automation_algorithm_version

    def get_preferences(self) -> AutomationPreferences:
        with self.database.session() as session:
            row = session.get(AutomationPreferencesRow, 1)
        if row is None:
            return AutomationPreferences()
        return AutomationPreferences(
            planning_scenario_id=row.planning_scenario_id,
            planning_revision_id=row.planning_revision_id,
            forecast_id=row.forecast_id,
            forecast_revision_id=row.forecast_revision_id,
            forecast_role=row.forecast_role,
            apartment_study_id=row.apartment_study_id,
            apartment_revision_id=row.apartment_revision_id,
            apartment_alternative_name=row.apartment_alternative_name,
            updated_at=_parse_datetime(row.updated_at),
        )

    primary_preferences = get_preferences

    def save_preferences(
        self, preferences: AutomationPreferences | dict[str, object]
    ) -> AutomationPreferences:
        value = (
            preferences
            if isinstance(preferences, AutomationPreferences)
            else AutomationPreferences.model_validate(preferences)
        )
        # Store the exact immutable revision that is current at selection
        # time.  The selectors therefore never silently follow later edits.
        if value.planning_scenario_id:
            from family_finance.planning import PlanningService

            planning = PlanningService(self.database, metrics=self.metrics, classifier=self.classifier)
            scenario = planning.get_scenario(value.planning_scenario_id)
            value = value.model_copy(update={
                "planning_revision_id": planning.get_revision(scenario.scenario_id).revision_id,
            })
        if value.forecast_id:
            from family_finance.forecasting import SavingsForecastService

            forecast = SavingsForecastService(self.database)
            saved_forecast = forecast.get_forecast(value.forecast_id)
            role = value.forecast_role or "baseline"
            if role not in {"baseline", "conservative", "optimistic"}:
                raise ValueError("forecast_role must be baseline, conservative, or optimistic")
            value = value.model_copy(update={
                "forecast_revision_id": forecast.get_revision(saved_forecast.forecast_id).revision_id,
                "forecast_role": role,
            })
        if value.apartment_study_id:
            from family_finance.apartment import ApartmentPlanningService

            apartment = ApartmentPlanningService(self.database)
            study = apartment.get_study(value.apartment_study_id)
            revision = apartment.get_revision(study.study_id)
            value = value.model_copy(update={"apartment_revision_id": revision.revision_id})
        else:
            value = value.model_copy(update={"apartment_revision_id": None})
        if not value.planning_scenario_id:
            value = value.model_copy(update={"planning_revision_id": None})
        if not value.forecast_id:
            value = value.model_copy(update={"forecast_revision_id": None, "forecast_role": None})
        now = utc_now()
        with self.database.write_session() as session:
            row = session.get(AutomationPreferencesRow, 1)
            if row is None:
                row = AutomationPreferencesRow(id=1, updated_at=now)
                session.add(row)
            for field in (
                "planning_scenario_id", "planning_revision_id", "forecast_id",
                "forecast_revision_id", "forecast_role", "apartment_study_id",
                "apartment_revision_id", "apartment_alternative_name",
            ):
                setattr(row, field, getattr(value, field))
            row.updated_at = now
        return self.get_preferences()

    set_preferences = save_preferences

    def list_alerts(
        self, *, state: str | None = None, condition_type: str | None = None
    ) -> list[InsightAlert]:
        statement = select(InsightAlertRow).order_by(InsightAlertRow.last_seen.desc())
        if state:
            statement = statement.where(InsightAlertRow.state == state)
        if condition_type:
            statement = statement.where(InsightAlertRow.condition_type == condition_type)
        with self.database.session() as session:
            rows = session.execute(statement).scalars().all()
        return [_alert_model(row) for row in rows]

    alerts = list_alerts

    def acknowledge_alert(self, alert_id: str) -> InsightAlert:
        return self._transition_alert(alert_id, "acknowledged")

    def resolve_alert(self, alert_id: str) -> InsightAlert:
        with self.database.write_session() as session:
            row = session.get(InsightAlertRow, alert_id)
            if row is None:
                raise ValueError("Insight alert not found")
            previous = row.state
            row.state = "resolved"
            row.resolved_at = utc_now()
            evidence = json.loads(row.evidence_json or "{}")
            row.manual_resolution_fingerprint = _evidence_hash(evidence)
            if previous != "resolved":
                session.add(InsightAlertEventRow(
                    id=str(uuid4()), alert_id=row.id, event_type="manual_resolve",
                    from_state=previous, to_state="resolved",
                    evidence_json=row.evidence_json, created_at=utc_now(),
                ))
        return self.get_alert(alert_id)

    def get_alert(self, alert_id: str) -> InsightAlert:
        with self.database.session() as session:
            row = session.get(InsightAlertRow, alert_id)
        if row is None:
            raise ValueError("Insight alert not found")
        return _alert_model(row)

    def reconcile_alerts(self) -> list[InsightAlert]:
        """Detect conditions and apply the append-only alert lifecycle."""
        candidates = self._alert_candidates()
        now = utc_now()
        with self.database.write_session() as session:
            existing = {
                row.fingerprint: row
                for row in session.execute(select(InsightAlertRow)).scalars().all()
            }
            seen: set[str] = set()
            for candidate in candidates:
                fingerprint = _fingerprint(
                    self.algorithm_version,
                    candidate["condition_type"], candidate["subject_identity"],
                    candidate.get("currency"), candidate["evidence_period"],
                )
                seen.add(fingerprint)
                evidence_json = json_dumps(candidate.get("evidence", {}))
                evidence_hash = _evidence_hash(candidate.get("evidence", {}))
                row = existing.get(fingerprint)
                if row is None:
                    row = InsightAlertRow(
                        id=str(uuid4()), fingerprint=fingerprint,
                        algorithm_version=self.algorithm_version,
                        condition_type=candidate["condition_type"],
                        subject_identity=candidate["subject_identity"],
                        currency=candidate.get("currency"),
                        evidence_period=candidate["evidence_period"], state="open",
                        first_seen=now, last_seen=now, occurrence_count=1,
                        evidence_json=evidence_json,
                    )
                    session.add(row)
                    session.flush()
                    session.add(InsightAlertEventRow(
                        id=str(uuid4()), alert_id=row.id, event_type="opened",
                        from_state=None, to_state="open", evidence_json=evidence_json,
                        created_at=now,
                    ))
                    continue
                previous_state = row.state
                old_evidence = json.loads(row.evidence_json or "{}")
                changed = _evidence_hash(old_evidence) != evidence_hash
                row.last_seen = now
                row.occurrence_count += 1
                row.evidence_json = evidence_json
                if changed and row.state in {"acknowledged", "resolved"}:
                    row.state = "open"
                    row.resolved_at = None
                    row.acknowledged_at = None
                    row.manual_resolution_fingerprint = None
                elif row.state == "resolved" and row.manual_resolution_fingerprint != evidence_hash:
                    row.state = "open"
                    row.resolved_at = None
                if row.state != previous_state:
                    session.add(InsightAlertEventRow(
                        id=str(uuid4()), alert_id=row.id, event_type="reopened" if row.state == "open" else "state_change",
                        from_state=previous_state, to_state=row.state,
                        evidence_json=evidence_json, created_at=now,
                    ))
            for row in existing.values():
                if row.fingerprint in seen:
                    continue
                if row.state == "resolved":
                    # A manually resolved condition is suppressed only while
                    # the exact evidence remains continuously present.  An
                    # absent run clears that suppression so a later return
                    # reopens the same deduplicated alert.
                    row.manual_resolution_fingerprint = None
                    row.resolved_at = now
                    continue
                previous = row.state
                row.state = "resolved"
                row.resolved_at = now
                row.manual_resolution_fingerprint = None
                session.add(InsightAlertEventRow(
                    id=str(uuid4()), alert_id=row.id, event_type="auto_resolve",
                    from_state=previous, to_state="resolved",
                    evidence_json=row.evidence_json, created_at=now,
                ))
        return self.list_alerts()

    def generate_monthly_summary(
        self, month: date | str | None = None, currency: str = "ILS"
    ) -> MonthlySummaryRevision | None:
        target = _month_start(month or _previous_month(datetime.now(UTC).date()))
        currency = currency.upper()
        if target > _previous_month(datetime.now(UTC).date()):
            return None
        metrics = self.metrics.calculate_monthly_metrics(target, currency)
        if not metrics.completeness.complete:
            return None
        anomalies = self.unusual_category_spending(target, target, currency)
        recurring = [
            item.model_dump(mode="json")
            for item in self.potential_recurring_spending(_month_shift(target, -6), target, currency)
        ]
        preferences = self.get_preferences().model_dump(mode="json")
        try:
            net_worth_content = self._latest_net_worth_content()
        except Exception:  # noqa: BLE001
            net_worth_content = {"available": False, "reason": "NET_WORTH_EVIDENCE_UNAVAILABLE"}
        content = {
            "algorithm_version": self.algorithm_version,
            "month": target.isoformat(),
            "currency": currency,
            "headline_cash_flow": {
                "income": metrics.gross_income,
                "net_consumption": metrics.net_consumption,
                "operating_surplus_or_deficit": metrics.operating_surplus_or_deficit,
                "observed_savings_transfers": metrics.net_observed_savings_transfers,
            },
            "mom": metrics.month_over_month_changes,
            "yoy": metrics.year_over_year_changes,
            "category_anomalies": [item.model_dump(mode="json") for item in anomalies],
            "recurring_changes": recurring,
            "primary_preferences": preferences,
            "latest_net_worth": net_worth_content,
            "forecast_comparison": self._forecast_content(preferences),
            "apartment_readiness": self._apartment_content(preferences),
            "data_quality_caveats": list(metrics.completeness.issues),
            "contributor_provenance": {
                metric: metrics.contributors_for(metric)
                for metric in ("gross_income", "net_consumption", "operating_surplus_or_deficit", "net_observed_savings_transfers")
            },
            "classification_policy_version": metrics.classification_policy_version,
        }
        canonical = _canonical(content)
        canonical_json = json_dumps(canonical)
        input_fingerprint = _sha256(canonical_json)
        content_hash = _sha256(canonical_json)
        markdown = _summary_markdown(content)
        with self.database.write_session() as session:
            identity = session.execute(
                select(MonthlySummaryIdentityRow).where(
                    MonthlySummaryIdentityRow.month == target.isoformat(),
                    MonthlySummaryIdentityRow.currency == currency,
                )
            ).scalar_one_or_none()
            if identity is None:
                identity = MonthlySummaryIdentityRow(
                    id=str(uuid4()), month=target.isoformat(), currency=currency,
                    created_at=utc_now(),
                )
                session.add(identity)
                session.flush()
            latest = session.execute(
                select(MonthlySummaryRevisionRow)
                .where(MonthlySummaryRevisionRow.identity_id == identity.id)
                .order_by(MonthlySummaryRevisionRow.revision_number.desc())
                .limit(1)
            ).scalar_one_or_none()
            if latest and latest.input_fingerprint == input_fingerprint:
                return _summary_model(latest)
            revision_number = (latest.revision_number + 1) if latest else 1
            row = MonthlySummaryRevisionRow(
                id=str(uuid4()), identity_id=identity.id, revision_number=revision_number,
                month=target.isoformat(), currency=currency,
                input_fingerprint=input_fingerprint, content_hash=content_hash,
                content_json=canonical_json, markdown=markdown,
                contributor_provenance_json=json_dumps(self._contributors(content)),
                created_at=utc_now(),
            )
            session.add(row)
            session.flush()
        return _summary_model(row)

    def generate_previous_month_summary(self) -> MonthlySummaryRevision | None:
        return self.generate_monthly_summary(_previous_month(datetime.now(UTC).date()))

    def list_summary_revisions(
        self, *, month: date | str | None = None, currency: str = "ILS"
    ) -> list[MonthlySummaryRevision]:
        statement = select(MonthlySummaryRevisionRow).where(
            MonthlySummaryRevisionRow.currency == currency.upper()
        ).order_by(MonthlySummaryRevisionRow.month.desc(), MonthlySummaryRevisionRow.revision_number.desc())
        if month:
            statement = statement.where(MonthlySummaryRevisionRow.month == _month_start(month).isoformat())
        with self.database.session() as session:
            rows = session.execute(statement).scalars().all()
        return [_summary_model(row) for row in rows]

    def summary_markdown(self, revision_id: str) -> str:
        with self.database.session() as session:
            row = session.get(MonthlySummaryRevisionRow, revision_id)
        if row is None:
            raise ValueError("Monthly summary revision not found")
        return row.markdown

    def summary_json(self, revision_id: str) -> str:
        with self.database.session() as session:
            row = session.get(MonthlySummaryRevisionRow, revision_id)
        if row is None:
            raise ValueError("Monthly summary revision not found")
        return row.content_json

    def _transition_alert(self, alert_id: str, target: str) -> InsightAlert:
        if target not in {"acknowledged", "resolved"}:
            raise ValueError(target)
        with self.database.write_session() as session:
            row = session.get(InsightAlertRow, alert_id)
            if row is None:
                raise ValueError("Insight alert not found")
            previous = row.state
            if target == "acknowledged" and previous == "open":
                row.state = target
                row.acknowledged_at = utc_now()
            elif target == "resolved":
                row.state = target
                row.resolved_at = utc_now()
                row.manual_resolution_fingerprint = _evidence_hash(json.loads(row.evidence_json or "{}"))
            if row.state != previous:
                session.add(InsightAlertEventRow(
                    id=str(uuid4()), alert_id=row.id, event_type="manual_" + target,
                    from_state=previous, to_state=row.state,
                    evidence_json=row.evidence_json, created_at=utc_now(),
                ))
        return self.get_alert(alert_id)

    def _alert_candidates(self) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        audit = AuditService(self.database, self.settings).run()
        if not audit.passed:
            candidates.append(_candidate("failed_audit", "database", None, "current", {
                "issue_codes": sorted({code for check in audit.checks for code in check.issue_codes})
            }))
        with self.database.session() as session:
            failed = session.execute(
                select(ImportBatchRow.status).where(ImportBatchRow.status.in_(("rejected", "needs_review")))
            ).all()
        if failed:
            candidates.append(_candidate("failed_imports", "import_pipeline", None, "current", {"count": len(failed)}))
        attention_files = [
            path for path in self.settings.automation_needs_review_root.rglob("*.xlsx")
            if path.is_file() and not path.is_symlink()
        ]
        if attention_files:
            candidates.append(_candidate("attention_files", "automation_inbox", None, "current", {"count": len(attention_files)}))
        open_cases = len(self.repository.open_reconciliation_cases()) if hasattr(self.repository, "open_reconciliation_cases") else len(self.database.open_reconciliation_cases())
        if open_cases:
            candidates.append(_candidate("open_reconciliation", "reconciliation", "ILS", "current", {"count": open_cases}))
        latest_batch = self.repository.latest_batch()
        if latest_batch and latest_batch.get("max_transaction_date"):
            freshness_days = (datetime.now(UTC).date() - date.fromisoformat(str(latest_batch["max_transaction_date"])[:10])).days
            if freshness_days > 31:
                candidates.append(_candidate("stale_import", "latest_import", None, "current", {"freshness_days": freshness_days}))
        preferences = self.get_preferences()
        if preferences.apartment_study_id and not preferences.apartment_alternative_name:
            candidates.append(_candidate("preference_missing_alternative", preferences.apartment_study_id, "ILS", "current", {}))
        elif preferences.apartment_study_id and preferences.apartment_alternative_name:
            try:
                from family_finance.apartment import ApartmentPlanningService

                study_service = ApartmentPlanningService(self.database)
                study = study_service.get_study(preferences.apartment_study_id)
                snapshot = study_service.get_revision(
                    study.study_id,
                    _revision_number("apartment_study_revisions", preferences.apartment_revision_id, self.database),
                )
                if not any(item.name.casefold() == preferences.apartment_alternative_name.casefold().strip() for item in snapshot.alternatives):
                    candidates.append(_candidate("preference_missing_alternative", preferences.apartment_study_id, "ILS", "current", {}))
            except Exception:  # noqa: BLE001
                candidates.append(_candidate("preference_missing_alternative", preferences.apartment_study_id, "ILS", "current", {}))

        dates = self.repository.all_accepted_booking_dates()
        if not dates:
            return candidates
        end = _previous_month(datetime.now(UTC).date())
        start = min(dates).replace(day=1)
        if start > end:
            return candidates
        series = self.metrics.calculate_monthly_series(start, end, "ILS")
        by_month = {item.month: item for item in series}
        for item in series:
            if not item.completeness.complete:
                candidates.append(_candidate("incomplete_month", item.month.isoformat(), "ILS", item.month.isoformat(), {"issues": item.completeness.issues}))
                continue
            if item.unclassified_transaction_count:
                candidates.append(_candidate("unclassified_rows", item.month.isoformat(), "ILS", item.month.isoformat(), {"count": item.unclassified_transaction_count, "amount": item.unclassified_absolute_amount}))
            prior = [by_month.get(_month_shift(item.month, -offset)) for offset in range(1, 7)]
            if len(prior) == 6 and all(previous and previous.completeness.complete for previous in prior):
                income_median = median([previous.gross_income for previous in prior])
                if item.gross_income <= income_median * Decimal("0.85") and income_median - item.gross_income >= Decimal(500):
                    candidates.append(_candidate("income_drop", item.month.isoformat(), "ILS", item.month.isoformat(), {"income": item.gross_income, "median": income_median}))
            if item.operating_surplus_or_deficit <= Decimal(-250):
                candidates.append(_candidate("operating_deficit", item.month.isoformat(), "ILS", item.month.isoformat(), {"deficit": item.operating_surplus_or_deficit}))

        # Optional primary planning selection.  It contributes only its
        # exact saved revision; a missing selection disables this domain.
        preferences = self.get_preferences()
        if preferences.planning_scenario_id and preferences.planning_revision_id:
            try:
                from family_finance.planning import PlanningService

                planning = PlanningService(self.database, metrics=self.metrics, classifier=self.classifier)
                selected_revision = planning.get_revision(
                    preferences.planning_scenario_id,
                    _revision_number("planning_scenario_revisions", preferences.planning_revision_id, self.database),
                )
                actual_plan = planning.compare_actual(
                    preferences.planning_scenario_id, revision_number=selected_revision.revision_number
                )
                for plan_month in actual_plan.months:
                    if not plan_month.complete or not plan_month.expense_variances:
                        continue
                    for category, variance in plan_month.expense_variances.items():
                        planned_amount = plan_month.planned.expenses_by_category.get(category, Decimal(0))
                        if abs(variance) > planned_amount.copy_abs() * Decimal("0.20") and abs(variance) > Decimal(250):
                            candidates.append(_candidate("primary_plan_category_variance", category, "ILS", plan_month.month.isoformat(), {"variance": variance, "planned": planned_amount, "scenario_revision_id": preferences.planning_revision_id}))
            except Exception:  # noqa: BLE001
                candidates.append(_candidate("primary_plan_evidence_unavailable", preferences.planning_revision_id, "ILS", "current", {}))

        # Optional forecast and apartment selections are intentionally read
        # through their existing engines; this layer only turns failures and
        # threshold crossings into explainable conditions.
        if preferences.forecast_id and preferences.forecast_revision_id:
            try:
                from family_finance.net_worth import NetWorthService

                observed = NetWorthService(self.database, self.settings).current_summary()
                comparison = NetWorthService(self.database, self.settings).compare_forecast_actual(
                    preferences.forecast_id,
                    observed.revision_id,
                    _revision_number("savings_forecast_revisions", preferences.forecast_revision_id, self.database),
                    role=preferences.forecast_role or "baseline",
                )
                if abs(comparison.aggregate_delta) > abs(comparison.projected_total) * Decimal("0.10") and abs(comparison.aggregate_delta) > Decimal(1000):
                    candidates.append(_candidate("primary_forecast_actual_variance", preferences.forecast_id, "ILS", str(comparison.observed_snapshot_date), comparison.model_dump(mode="json")))
            except Exception:  # noqa: BLE001
                candidates.append(_candidate("primary_forecast_evidence_unavailable", preferences.forecast_revision_id, "ILS", "current", {}))

        if preferences.apartment_study_id and preferences.apartment_revision_id and preferences.apartment_alternative_name:
            try:
                from family_finance.apartment import ApartmentPlanningService

                apartment = ApartmentPlanningService(self.database)
                study = apartment.get_study(preferences.apartment_study_id)
                revision_number = _revision_number("apartment_study_revisions", preferences.apartment_revision_id, self.database)
                snapshot = apartment.get_revision(study.study_id, revision_number)
                alternative = next(
                    item for item in snapshot.alternatives
                    if item.name.casefold() == preferences.apartment_alternative_name.casefold().strip()
                )
                draft = apartment.project_draft(
                    study.forecast_id, snapshot.alternatives,
                    forecast_revision_number=study.forecast_revision_number,
                    guardrails=snapshot.guardrails,
                )
                projection = next(item for item in draft.projections if item.alternative_name.casefold() == alternative.name.casefold())
                if projection.funding_gap > 0:
                    candidates.append(_candidate("apartment_funding_gap", alternative.name, "ILS", str(revision_number), {"funding_gap": projection.funding_gap}))
                if not projection.readiness.ready:
                    candidates.append(_candidate("apartment_readiness_failure", alternative.name, "ILS", str(revision_number), {"failures": projection.readiness.failures}))
            except StopIteration:
                pass
            except Exception:  # noqa: BLE001
                candidates.append(_candidate("apartment_evidence_unavailable", preferences.apartment_revision_id, "ILS", "current", {}))

        for anomaly in self.unusual_category_spending(start, end, "ILS", series=series):
            candidates.append(_candidate("category_anomaly", anomaly.category, "ILS", anomaly.month.isoformat(), anomaly.model_dump(mode="json")))
        for recurring in self.potential_recurring_spending(_month_shift(end, -12), end, "ILS"):
            if len(recurring.occurrence_months) < 4:
                continue
            rows = self.repository.contributor_rows(recurring.contributor_transaction_ids)
            by_month_amount = {
                date.fromisoformat(str(row["booking_date"])) .replace(day=1): abs(Decimal(str(row["amount"])))
                for row in rows
            }
            latest_month = max(by_month_amount)
            prior_amounts = [amount for month, amount in by_month_amount.items() if month < latest_month]
            latest_amount = by_month_amount[latest_month]
            if len(prior_amounts) >= 3:
                prior_median = Decimal(str(median(prior_amounts)))
                if latest_amount >= prior_median * Decimal("1.20") and latest_amount - prior_median >= Decimal(100):
                    candidates.append(_candidate("recurring_expense_increase", recurring.normalized_description, "ILS", latest_month.isoformat(), {"latest": latest_amount, "prior_median": prior_median, "contributors": recurring.contributor_transaction_ids}))

        try:
            summary = self._latest_net_worth_content()
            for account_key in summary.get("stale_account_keys", []):
                candidates.append(_candidate("stale_net_worth", account_key, "ILS", str(summary.get("snapshot_date", "current")), {"account_key": account_key}))
        except Exception:  # noqa: BLE001
            candidates.append(_candidate("net_worth_evidence_unavailable", "net_worth", "ILS", "current", {}))
        return candidates

    def _latest_net_worth_content(self) -> dict[str, object]:
        from family_finance.net_worth import NetWorthService

        service = NetWorthService(self.database, self.settings)
        summary = service.current_summary()
        return {
            "snapshot_date": summary.snapshot_date,
            "revision_id": summary.revision_id,
            "net_worth": summary.net_worth,
            "total_assets": summary.total_assets,
            "total_liabilities": summary.total_liabilities,
            "stale_account_keys": summary.stale_account_keys,
        }

    def _forecast_content(self, preferences: dict[str, object]) -> dict[str, object]:
        return {"selected_revision_id": preferences.get("forecast_revision_id"), "available": bool(preferences.get("forecast_id"))}

    def _apartment_content(self, preferences: dict[str, object]) -> dict[str, object]:
        return {"selected_revision_id": preferences.get("apartment_revision_id"), "alternative": preferences.get("apartment_alternative_name"), "available": bool(preferences.get("apartment_study_id"))}

    @staticmethod
    def _contributors(content: dict[str, object]) -> dict[str, object]:
        return {
            "algorithm_version": content.get("algorithm_version"),
            "contributors": content.get("contributor_provenance", {}),
            "anomalies": "category_anomalies",
        }

    def potential_recurring_spending(
        self,
        start_month: date | str | None = None,
        end_month: date | str | None = None,
        currency: str | None = None,
    ) -> list[PotentialRecurringSpending]:
        start = date.fromisoformat(f"{start_month}-01") if isinstance(start_month, str) and len(start_month) == 7 else start_month
        end = date.fromisoformat(f"{end_month}-01") if isinstance(end_month, str) and len(end_month) == 7 else end_month
        rows = self.repository.accepted_transactions(currency=currency.upper() if currency else None)
        grouped: dict[tuple[str, str, str, str], list[tuple[date, Decimal, int]]] = defaultdict(list)
        for row in rows:
            booking = date.fromisoformat(str(row["booking_date"]))
            month = booking.replace(day=1)
            if start and month < _month_start(start):
                continue
            if end and month > _month_start(end):
                continue
            classification = self.classifier._classify_row(row)
            if classification.economic_class != EconomicClass.CONSUMPTION or classification.amount >= 0:
                continue
            category = classification.analysis_category or classification.source_category
            key = (
                _normalized_description(str(row["description"])),
                category,
                classification.currency,
                classification.account_kind,
            )
            grouped[key].append((booking, abs(classification.amount), classification.transaction_id))

        results: list[PotentialRecurringSpending] = []
        for (description, category, scoped_currency, account_kind), occurrences in grouped.items():
            by_month: dict[date, list[tuple[date, Decimal, int]]] = defaultdict(list)
            for occurrence in occurrences:
                by_month[occurrence[0].replace(day=1)].append(occurrence)
            if len(by_month) < 3 or any(len(items) != 1 for items in by_month.values()):
                continue
            ordered = sorted(next(iter(items)) for items in by_month.values())
            gaps = [(right[0] - left[0]).days for left, right in pairwise(ordered)]
            if not all(20 <= gap <= 40 for gap in gaps):
                continue
            amounts = [item[1] for item in ordered]
            results.append(
                PotentialRecurringSpending(
                    normalized_description=description,
                    analysis_category=category,
                    currency=scoped_currency,
                    account_kind=account_kind,
                    median_amount=Decimal(str(median(amounts))),
                    minimum_amount=min(amounts),
                    maximum_amount=max(amounts),
                    amount_range=(min(amounts), max(amounts)),
                    occurrence_months=[item[0].replace(day=1) for item in ordered],
                    contributor_transaction_ids=[item[2] for item in ordered],
                )
            )
        return sorted(results, key=lambda item: (item.currency, item.normalized_description))

    def unusual_category_spending(
        self,
        start_month: date | str,
        end_month: date | str,
        currency: str = "ILS",
        *,
        series: list[MonthlyMetrics] | None = None,
    ) -> list[UnusualCategorySpending]:
        start = date.fromisoformat(f"{start_month}-01") if isinstance(start_month, str) and len(start_month) == 7 else start_month
        end = date.fromisoformat(f"{end_month}-01") if isinstance(end_month, str) and len(end_month) == 7 else end_month
        if start is None or end is None or start > end:
            raise ValueError("start_month and end_month must be an ordered range")
        series = series or self.metrics.calculate_monthly_series(start, end, currency.upper())
        by_month = {item.month: item for item in series}
        results: list[UnusualCategorySpending] = []
        for target in series:
            baseline_months = [_month_shift(target.month, -offset) for offset in range(1, 7)]
            baseline_items = [
                by_month.get(month)
                or self.metrics.cached_monthly_metrics(month, currency.upper())
                for month in baseline_months
            ]
            if not target.completeness.complete or any(
                not item.completeness.complete for item in baseline_items
            ):
                continue
            categories = set(target.spending_by_category)
            for item in baseline_items:
                categories.update(item.spending_by_category)
            baseline_total_consumption = median(
                [item.net_consumption for item in baseline_items]
            )
            if baseline_total_consumption <= 0:
                continue
            material_threshold = abs(Decimal(str(baseline_total_consumption))) * Decimal("0.02")
            for category in sorted(categories):
                baseline = Decimal(str(median(
                    [item.spending_by_category.get(category, Decimal(0)) for item in baseline_items]
                )))
                current = target.spending_by_category.get(category, Decimal(0))
                difference = current - baseline
                if baseline == 0:
                    qualifies = current != 0
                else:
                    qualifies = abs(difference) >= abs(baseline) * Decimal("0.50")
                if not qualifies or abs(difference) < material_threshold:
                    continue
                contributor_ids = target.contributors_for(f"spending_by_category:{category}")
                results.append(
                    UnusualCategorySpending(
                        month=target.month,
                        category=category,
                        currency=target.currency,
                        baseline_median=baseline,
                        target_total=current,
                        difference=difference,
                        direction="high" if difference > 0 else "low",
                        rule=(
                            "Complete target month versus the median of six immediately preceding "
                            "complete months; absolute change >= 50% of category baseline and "
                            "materially exceeds 2% of baseline median total consumption."
                        ),
                        contributor_transaction_ids=contributor_ids,
                    )
                )
        return results

    recurring = potential_recurring_spending
    anomalies = unusual_category_spending
    detect_potential_recurring_spending = potential_recurring_spending
    detect_unusual_category_spending = unusual_category_spending


__all__ = ["InsightsService"]


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _month_start(value: date | str) -> date:
    if isinstance(value, str):
        value = date.fromisoformat(value[:10] if len(value) > 7 else f"{value}-01")
    return value.replace(day=1)


def _previous_month(value: date) -> date:
    return date(value.year - 1, 12, 1) if value.month == 1 else date(value.year, value.month - 1, 1)


def _candidate(condition_type, subject_identity, currency, evidence_period, evidence):
    return {
        "condition_type": condition_type,
        "subject_identity": subject_identity,
        "currency": currency,
        "evidence_period": evidence_period,
        "evidence": _canonical(evidence),
    }


def _canonical(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _sha256(value: str | object) -> str:
    payload = value if isinstance(value, str) else json_dumps(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fingerprint(version, condition, subject, currency, period) -> str:
    return _sha256(json_dumps({
        "algorithm_version": version,
        "condition_type": condition,
        "subject_identity": subject,
        "currency": currency,
        "evidence_period": period,
    }))


def _evidence_hash(value) -> str:
    return _sha256(json_dumps(_canonical(value)))


def _revision_number(table: str, revision_id: str, database: Database) -> int:
    allowed = {
        "planning_scenario_revisions": "planning_scenario_revisions",
        "savings_forecast_revisions": "savings_forecast_revisions",
        "apartment_study_revisions": "apartment_study_revisions",
    }
    if table not in allowed:
        raise ValueError("Unsupported revision table")
    with database.connect() as connection:
        row = connection.execute(
            f"SELECT revision_number FROM {allowed[table]} WHERE id = ?",
            (revision_id,),
        ).fetchone()
    if not row:
        raise ValueError("Saved preference revision not found")
    return int(row["revision_number"])


def _alert_model(row: InsightAlertRow) -> InsightAlert:
    return InsightAlert(
        id=row.id,
        fingerprint=row.fingerprint,
        algorithm_version=row.algorithm_version,
        condition_type=row.condition_type,
        subject_identity=row.subject_identity,
        currency=row.currency,
        evidence_period=row.evidence_period,
        state=row.state,
        first_seen=_parse_datetime(row.first_seen),
        last_seen=_parse_datetime(row.last_seen),
        occurrence_count=row.occurrence_count,
        evidence=json.loads(row.evidence_json or "{}"),
        acknowledged_at=_parse_datetime(row.acknowledged_at),
        resolved_at=_parse_datetime(row.resolved_at),
        manual_resolution_fingerprint=row.manual_resolution_fingerprint,
    )


def _summary_model(row: MonthlySummaryRevisionRow) -> MonthlySummaryRevision:
    return MonthlySummaryRevision(
        id=row.id,
        identity_id=row.identity_id,
        revision_number=row.revision_number,
        month=date.fromisoformat(row.month),
        currency=row.currency,
        input_fingerprint=row.input_fingerprint,
        content_hash=row.content_hash,
        content=json.loads(row.content_json),
        markdown=row.markdown,
        contributor_provenance=json.loads(row.contributor_provenance_json or "{}"),
        created_at=_parse_datetime(row.created_at),
    )


def _summary_markdown(content: dict[str, object]) -> str:
    headline = content["headline_cash_flow"]
    return "\n".join([
        f"# Household summary — {content['month']}",
        "",
        "## Headline cash flow",
        f"- Income: {headline['income']} {content['currency']}",
        f"- Net consumption: {headline['net_consumption']} {content['currency']}",
        f"- Operating surplus or deficit: {headline['operating_surplus_or_deficit']} {content['currency']}",
        f"- Observed savings transfers: {headline['observed_savings_transfers']} {content['currency']}",
        "",
        "## Data quality caveats",
        "- " + ("; ".join(content["data_quality_caveats"]) or "None recorded."),
        "",
        "This deterministic summary describes observed records and saved revisions; it does not claim causation or guarantee outcomes.",
    ])
