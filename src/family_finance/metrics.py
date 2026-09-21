"""Monthly financial metrics with explicit completeness and contributors."""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from family_finance.classification import CLASSIFICATION_POLICY_VERSION, ClassificationService
from family_finance.models import (
    ClassificationResult,
    CompletenessAssessment,
    EconomicClass,
    ExpenseBehavior,
    MetricBreakdown,
    MonthlyMetrics,
)
from family_finance.persistence.db import Database
from family_finance.persistence.repositories import FinancialRepository

ZERO = Decimal(0)
_AVERAGE_SCALE = Decimal("0.0001")
_COMPARISON_FIELDS = (
    "gross_income",
    "gross_consumption",
    "refunds",
    "net_consumption",
    "operating_surplus_or_deficit",
    "savings_rate",
    "savings_contributions",
    "savings_withdrawals",
    "net_observed_savings_transfers",
)


def _month_start(value: date | str) -> date:
    if isinstance(value, str):
        value = date.fromisoformat(f"{value}-01" if len(value) == 7 else value[:10])
    return value.replace(day=1)


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _previous_month(value: date) -> date:
    if value.month == 1:
        return date(value.year - 1, 12, 1)
    return date(value.year, value.month - 1, 1)


def _month_end(value: date) -> date:
    return date(value.year, value.month, calendar.monthrange(value.year, value.month)[1])


def _average(values: Iterable[Decimal | None]) -> Decimal | None:
    values = list(values)
    if not values or any(value is None for value in values):
        return None
    return (sum(values, ZERO) / Decimal(len(values))).quantize(
        _AVERAGE_SCALE, rounding=ROUND_HALF_UP
    )


def _union(*ids: Iterable[int]) -> list[int]:
    return list(dict.fromkeys(item for group in ids for item in group))


class MetricsService:
    def __init__(
        self,
        database: Database,
        *,
        classifier: ClassificationService | None = None,
        policy_version: str = CLASSIFICATION_POLICY_VERSION,
        source_coverage: str = "unknown",
    ) -> None:
        self.database = database
        self.repository = FinancialRepository(database)
        self.classifier = classifier or ClassificationService(
            database, policy_version=policy_version
        )
        self.policy_version = policy_version
        self.source_coverage = source_coverage

    def calculate_monthly_metrics(
        self,
        month: date | str,
        currency: str = "ILS",
    ) -> MonthlyMetrics:
        month_start = _month_start(month)
        basic = self._calculate_basic(month_start, currency.upper())

        previous = self._calculate_basic(_previous_month(month_start), currency.upper())
        year_ago = self._calculate_basic(
            date(month_start.year - 1, month_start.month, 1), currency.upper()
        )
        if basic.completeness.complete and previous.completeness.complete:
            mom = {
                field: self._change(getattr(basic, field), getattr(previous, field))
                for field in _COMPARISON_FIELDS
            }
        else:
            mom = {field: None for field in _COMPARISON_FIELDS}
        if basic.completeness.complete and year_ago.completeness.complete:
            yoy = {
                field: self._change(getattr(basic, field), getattr(year_ago, field))
                for field in _COMPARISON_FIELDS
            }
        else:
            yoy = {field: None for field in _COMPARISON_FIELDS}

        historical = self._historical_months(month_start, currency.upper())
        historical_averages = {
            field: _average(getattr(item, field) for item in historical)
            for field in _COMPARISON_FIELDS
        }
        rolling_3 = self._rolling(month_start, currency.upper(), 3)
        rolling_6 = self._rolling(month_start, currency.upper(), 6)
        return basic.model_copy(
            update={
                "historical_monthly_averages": historical_averages,
                "rolling_three_month_averages": rolling_3,
                "rolling_six_month_averages": rolling_6,
                "month_over_month_changes": mom,
                "year_over_year_changes": yoy,
            }
        )

    def monthly_metrics(self, month: date | str, currency: str = "ILS") -> MonthlyMetrics:
        return self.calculate_monthly_metrics(month, currency)

    def calculate(self, month: date | str, currency: str = "ILS") -> MonthlyMetrics:
        return self.calculate_monthly_metrics(month, currency)

    def _calculate_basic(self, month: date, currency: str) -> MonthlyMetrics:
        end = _next_month(month)
        rows = self.repository.accepted_transactions(
            currency=currency, start=month, end=end
        )
        classifications = [self.classifier._classify_row(row) for row in rows]
        source_completeness, completeness = self._assess_completeness(
            month, end, classifications
        )
        unclassified = [
            item for item in classifications if item.economic_class == EconomicClass.UNCLASSIFIED
        ]

        income_ids: list[int] = []
        consumption_ids: list[int] = []
        refund_ids: list[int] = []
        savings_contribution_ids: list[int] = []
        savings_withdrawal_ids: list[int] = []
        fixed_ids: list[int] = []
        variable_ids: list[int] = []
        unknown_ids: list[int] = []
        income = ZERO
        consumption = ZERO
        refunds = ZERO
        contributions = ZERO
        withdrawals = ZERO
        fixed = ZERO
        variable = ZERO
        unknown = ZERO
        spending: dict[str, Decimal] = {}
        spending_ids: dict[str, list[int]] = {}

        for item in classifications:
            amount = item.amount
            magnitude = abs(amount)
            if item.economic_class == EconomicClass.INCOME and amount > 0:
                income += amount
                income_ids.append(item.transaction_id)
            elif item.economic_class == EconomicClass.CONSUMPTION and amount < 0:
                consumption += magnitude
                consumption_ids.append(item.transaction_id)
                category = item.analysis_category or item.source_category
                spending[category] = spending.get(category, ZERO) + magnitude
                spending_ids.setdefault(category, []).append(item.transaction_id)
                if item.expense_behavior == ExpenseBehavior.FIXED:
                    fixed += magnitude
                    fixed_ids.append(item.transaction_id)
                elif item.expense_behavior == ExpenseBehavior.VARIABLE:
                    variable += magnitude
                    variable_ids.append(item.transaction_id)
                else:
                    unknown += magnitude
                    unknown_ids.append(item.transaction_id)
            elif item.economic_class == EconomicClass.REFUND and amount != 0:
                refunds += magnitude
                refund_ids.append(item.transaction_id)
            elif item.economic_class == EconomicClass.SAVINGS_TRANSFER:
                if amount < 0:
                    contributions += magnitude
                    savings_contribution_ids.append(item.transaction_id)
                elif amount > 0:
                    withdrawals += amount
                    savings_withdrawal_ids.append(item.transaction_id)

        net_consumption = consumption - refunds
        surplus = income - net_consumption
        rate = (
            (surplus / income).quantize(_AVERAGE_SCALE, rounding=ROUND_HALF_UP)
            if income > ZERO and completeness.complete
            else None
        )
        net_savings = contributions - withdrawals
        freshness = self._freshness_date()

        contributor_map: dict[str, list[int]] = {
            "gross_income": income_ids,
            "gross_consumption": consumption_ids,
            "refunds": refund_ids,
            "net_consumption": _union(consumption_ids, refund_ids),
            "operating_surplus_or_deficit": _union(
                income_ids, consumption_ids, refund_ids
            ),
            "savings_rate": _union(income_ids, consumption_ids, refund_ids),
            "savings_contributions": savings_contribution_ids,
            "savings_withdrawals": savings_withdrawal_ids,
            "net_observed_savings_transfers": _union(
                savings_contribution_ids, savings_withdrawal_ids
            ),
            "fixed_consumption": fixed_ids,
            "variable_consumption": variable_ids,
            "unknown_behavior_consumption": unknown_ids,
        }
        values: dict[str, Decimal | None] = {
            "gross_income": income,
            "gross_consumption": consumption,
            "refunds": refunds,
            "net_consumption": net_consumption,
            "operating_surplus_or_deficit": surplus,
            "savings_rate": rate,
            "savings_contributions": contributions,
            "savings_withdrawals": withdrawals,
            "net_observed_savings_transfers": net_savings,
            "fixed_consumption": fixed,
            "variable_consumption": variable,
            "unknown_behavior_consumption": unknown,
        }
        breakdowns = {
            name: MetricBreakdown(
                name=name,
                value=values.get(name),
                contributor_transaction_ids=contributor_map.get(name, []),
                currency=currency,
            )
            for name in values
        }
        for category, value in spending.items():
            name = f"spending_by_category:{category}"
            breakdowns[name] = MetricBreakdown(
                name=name,
                value=value,
                contributor_transaction_ids=spending_ids[category],
                currency=currency,
            )

        return MonthlyMetrics(
            month=month,
            currency=currency,
            classification_policy_version=self.policy_version,
            source_period_completeness=source_completeness,
            completeness=completeness,
            unclassified_transaction_count=len(unclassified),
            unclassified_absolute_amount=sum(
                (abs(item.amount) for item in unclassified), ZERO
            ),
            data_freshness_date=freshness,
            gross_income=income,
            gross_consumption=consumption,
            refunds=refunds,
            net_consumption=net_consumption,
            operating_surplus_or_deficit=surplus,
            savings_rate=rate,
            savings_contributions=contributions,
            savings_withdrawals=withdrawals,
            net_observed_savings_transfers=net_savings,
            fixed_consumption=fixed,
            variable_consumption=variable,
            unknown_behavior_consumption=unknown,
            spending_by_category=spending,
            breakdowns=breakdowns,
        )

    def _assess_completeness(
        self,
        month: date,
        end: date,
        classifications: list[ClassificationResult],
    ) -> tuple[CompletenessAssessment, CompletenessAssessment]:
        covering_batches = self.repository.batches_covering(month, _month_end(month))
        open_cases = self.repository.open_cases_in_period(month, end)
        unclassified = [
            item for item in classifications if item.economic_class == EconomicClass.UNCLASSIFIED
        ]
        source_complete = any(
            self._batch_proves_period_complete(batch, month) for batch in covering_batches
        )
        classification_complete = not unclassified
        source_issues: list[str] = []
        if not source_complete:
            source_issues.append("SOURCE_PERIOD_PARTIAL_OR_UNKNOWN")
        if open_cases:
            source_issues.append("OPEN_RECONCILIATION_CASES")
        source_assessment = CompletenessAssessment(
            source_period_complete=source_complete,
            classification_complete=True,
            complete=source_complete and not open_cases,
            source_coverage=self.source_coverage,
            open_reconciliation_count=len(open_cases),
            issues=source_issues,
        )
        issues = list(source_issues)
        if unclassified:
            issues.append("UNCLASSIFIED_TRANSACTIONS")
        classification_assessment = CompletenessAssessment(
            source_period_complete=source_complete,
            classification_complete=classification_complete,
            complete=source_complete and classification_complete and not open_cases,
            source_coverage=self.source_coverage,
            open_reconciliation_count=len(open_cases),
            unclassified_transaction_count=len(unclassified),
            unclassified_absolute_amount=sum((abs(item.amount) for item in unclassified), ZERO),
            issues=issues,
        )
        return source_assessment, classification_assessment

    @staticmethod
    def _batch_proves_period_complete(batch: dict[str, Any], month: date) -> bool:
        """Require freshness evidence for a report's trailing boundary month.

        FamilyBiz's requested report end is not proof that rows were present
        through that date.  When the requested period reaches the month of the
        batch's latest observed transaction, a month remains provisional until
        the observed data reaches its calendar end.
        """

        report_end_value = batch.get("report_end")
        max_transaction_value = batch.get("max_transaction_date")
        if not report_end_value or not max_transaction_value:
            return False
        report_end = date.fromisoformat(str(report_end_value)[:10])
        max_transaction_date = date.fromisoformat(str(max_transaction_value)[:10])
        if month > report_end.replace(day=1):
            return False
        return not (
            month >= max_transaction_date.replace(day=1)
            and max_transaction_date < _month_end(month)
        )

    def _freshness_date(self) -> date | None:
        latest = self.repository.latest_batch()
        if latest and latest.get("max_transaction_date"):
            return date.fromisoformat(str(latest["max_transaction_date"])[:10])
        dates = self.repository.all_accepted_booking_dates()
        return max(dates) if dates else None

    def _historical_months(self, month: date, currency: str) -> list[MonthlyMetrics]:
        dates = self.repository.all_accepted_booking_dates()
        if not dates:
            return []
        first = min(dates).replace(day=1)
        result: list[MonthlyMetrics] = []
        current = first
        while current < month:
            item = self._calculate_basic(current, currency)
            if item.completeness.complete:
                result.append(item)
            current = _next_month(current)
        return result

    def _rolling(self, month: date, currency: str, count: int) -> dict[str, Decimal | None]:
        months = []
        current = month
        for _ in range(count):
            item = self._calculate_basic(current, currency)
            if not item.completeness.complete:
                return {field: None for field in _COMPARISON_FIELDS}
            months.append(item)
            current = _previous_month(current)
        return {
            field: _average(getattr(item, field) for item in months)
            for field in _COMPARISON_FIELDS
        }

    @staticmethod
    def _change(left: Decimal | None, right: Decimal | None) -> Decimal | None:
        if left is None or right is None:
            return None
        return left - right

    def get_metric_contributors(
        self,
        month: date | str,
        metric_name: str,
        currency: str = "ILS",
    ) -> list[dict[str, Any]]:
        metrics = self.calculate_monthly_metrics(month, currency)
        if metric_name in metrics.spending_by_category:
            metric_name = f"spending_by_category:{metric_name}"
        return self.repository.contributor_rows(metrics.contributors_for(metric_name))

    def contributors_for_metric(
        self, month: date | str, metric_name: str, currency: str = "ILS"
    ) -> list[dict[str, Any]]:
        return self.get_metric_contributors(month, metric_name, currency)

    def get_contributing_transactions(
        self, month: date | str, metric_name: str, currency: str = "ILS"
    ) -> list[dict[str, Any]]:
        return self.get_metric_contributors(month, metric_name, currency)


FinancialMetricsService = MetricsService
MetricsEngine = MetricsService


__all__ = ["FinancialMetricsService", "MetricsEngine", "MetricsService"]
