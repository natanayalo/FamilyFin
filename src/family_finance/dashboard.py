"""Typed dashboard read models backed by the domain metrics service."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from family_finance.classification import ClassificationService
from family_finance.insights import InsightsService
from family_finance.metrics import MetricsService
from family_finance.models import (
    CategorySummary,
    DashboardComparison,
    DashboardFilters,
    DataQualityDashboard,
    ExpenseBehavior,
    ExpenseDashboard,
    MonthlyMetrics,
        MonthlySeriesPoint,
    OverviewDashboard,
        TransactionContribution,
    )
from family_finance.persistence.db import Database
from family_finance.persistence.repositories import FinancialRepository


def _previous_month(month: date) -> date:
    return date(month.year - 1, 12, 1) if month.month == 1 else date(month.year, month.month - 1, 1)


def _month_shift(month: date, offset: int) -> date:
    year = month.year + (month.month - 1 + offset) // 12
    month_number = (month.month - 1 + offset) % 12 + 1
    return date(year, month_number, 1)


class DashboardService:
    """Application-facing dashboard facade; Streamlit never aggregates transactions."""

    def __init__(
        self,
        database: Database,
        *,
        metrics: MetricsService | None = None,
        classifier: ClassificationService | None = None,
        insights: InsightsService | None = None,
    ) -> None:
        self.database = database
        self.repository = FinancialRepository(database)
        self.classifier = classifier or ClassificationService(database)
        self.metrics = metrics or MetricsService(database, classifier=self.classifier)
        self.insights = insights or InsightsService(
            database, classifier=self.classifier, metrics=self.metrics
        )

    def default_filters(self, currency: str = "ILS") -> DashboardFilters:
        dates = self.repository.all_accepted_booking_dates()
        end = max(dates).replace(day=1) if dates else datetime.now(UTC).date().replace(day=1)
        return DashboardFilters(
            start_month=_month_shift(end, -11), end_month=end, currency=currency
        )

    @staticmethod
    def _filters(filters: DashboardFilters | dict[str, Any]) -> DashboardFilters:
        return filters if isinstance(filters, DashboardFilters) else DashboardFilters.model_validate(filters)

    @staticmethod
    def _point(metrics: MonthlyMetrics) -> MonthlySeriesPoint:
        issues = list(dict.fromkeys(metrics.completeness.issues + metrics.source_period_completeness.issues))
        return MonthlySeriesPoint(
            month=metrics.month,
            currency=metrics.currency,
            complete=metrics.completeness.complete,
            issue_codes=issues,
            metrics=metrics,
        )

    @staticmethod
    def _unavailable_reason(current: MonthlyMetrics, comparison: MonthlyMetrics | None) -> str:
        if not current.completeness.complete:
            return "The selected month is provisional: " + ", ".join(current.completeness.issues)
        if comparison is None:
            return "The comparison month is outside the selected range."
        if not comparison.completeness.complete:
            return "The comparison month is provisional: " + ", ".join(comparison.completeness.issues)
        return "The metrics policy withheld this comparison."

    def _comparison(
        self,
        metric: str,
        current: MonthlyMetrics,
        comparison: MonthlyMetrics | None,
        *,
        change: Decimal | None,
    ) -> DashboardComparison:
        value_metric = metric.split(":", 1)[0]
        current_value = getattr(current, value_metric)
        previous_value = getattr(comparison, value_metric) if comparison else None
        available = change is not None
        return DashboardComparison(
            metric=metric,
            current=current_value,
            previous=previous_value,
            delta=change,
            available=available,
            reason=None if available else self._unavailable_reason(current, comparison),
        )

    def overview(self, filters: DashboardFilters | dict[str, Any]) -> OverviewDashboard:
        selected_filters = self._filters(filters)
        series_metrics = self.metrics.calculate_monthly_series(
            selected_filters.start_month,
            selected_filters.end_month,
            selected_filters.currency,
        )
        points = [self._point(item) for item in series_metrics]
        selected = series_metrics[-1] if series_metrics else None
        previous = (
            self.metrics.cached_monthly_metrics(_previous_month(selected.month), selected.currency)
            if selected
            else None
        )
        year_ago = (
            self.metrics.cached_monthly_metrics(
                date(selected.month.year - 1, selected.month.month, 1), selected.currency
            )
            if selected
            else None
        )
        comparisons: list[DashboardComparison] = []
        if selected:
            for metric in (
                "gross_income",
                "net_consumption",
                "operating_surplus_or_deficit",
                "savings_rate",
                "net_observed_savings_transfers",
            ):
                comparisons.append(
                    self._comparison(
                        metric,
                        selected,
                        previous,
                        change=selected.month_over_month_changes.get(metric),
                    )
                )
                comparisons.append(
                    self._comparison(
                        f"{metric}:yoy",
                        selected,
                        year_ago,
                        change=selected.year_over_year_changes.get(metric),
                    )
                )
        headline = (
            {
                "income": selected.gross_income,
                "net_consumption": selected.net_consumption,
                "operating_surplus_or_deficit": selected.operating_surplus_or_deficit,
                "savings_rate": selected.savings_rate,
                "net_observed_savings_transfers": selected.net_observed_savings_transfers,
            }
            if selected
            else {}
        )
        return OverviewDashboard(
            filters=selected_filters,
            selected_month=self._point(selected) if selected else None,
            series=points,
            headline=headline,
            comparisons=comparisons,
            freshness_date=selected.data_freshness_date if selected else None,
            source_coverage=selected.completeness.source_coverage if selected else "unknown",
            currency=selected_filters.currency,
        )

    def expenses(self, filters: DashboardFilters | dict[str, Any]) -> ExpenseDashboard:
        selected_filters = self._filters(filters)
        raw_series = self.metrics.calculate_monthly_series(
            selected_filters.start_month,
            selected_filters.end_month,
            selected_filters.currency,
        )
        points = [self._point(item) for item in raw_series]
        selected = raw_series[-1] if raw_series else None
        categories = (
            [
                CategorySummary(
                    category=category,
                    amount=amount,
                    contributor_transaction_ids=selected.contributors_for(
                        f"spending_by_category:{category}"
                    ),
                )
                for category, amount in sorted(
                    selected.spending_by_category.items(), key=lambda item: (-item[1], item[0])
                )
            ]
            if selected
            else []
        )
        behavior_totals = (
            {
                ExpenseBehavior.FIXED.value: selected.fixed_consumption,
                ExpenseBehavior.VARIABLE.value: selected.variable_consumption,
                ExpenseBehavior.UNKNOWN.value: selected.unknown_behavior_consumption,
            }
            if selected
            else {}
        )
        previous = (
            self.metrics.cached_monthly_metrics(_previous_month(selected.month), selected.currency)
            if selected
            else None
        )
        year_ago = (
            self.metrics.cached_monthly_metrics(
                date(selected.month.year - 1, selected.month.month, 1), selected.currency
            )
            if selected
            else None
        )
        category_comparisons: list[DashboardComparison] = []
        if selected:
            for summary in categories:
                for suffix, comparison in (("mom", previous), ("yoy", year_ago)):
                    current_value = selected.spending_by_category.get(summary.category, Decimal(0))
                    previous_value = (
                        comparison.spending_by_category.get(summary.category, Decimal(0))
                        if comparison
                        else None
                    )
                    complete = (
                        selected.completeness.complete
                        and comparison is not None
                        and comparison.completeness.complete
                    )
                    category_comparisons.append(
                        DashboardComparison(
                            metric=f"{summary.category}:{suffix}",
                            current=current_value,
                            previous=previous_value,
                            delta=current_value - previous_value if complete and previous_value is not None else None,
                            available=complete,
                            reason=None if complete else self._unavailable_reason(selected, comparison),
                        )
                    )
        recurring = self.insights.potential_recurring_spending(
            selected_filters.start_month,
            selected_filters.end_month,
            selected_filters.currency,
        )
        anomalies = self.insights.unusual_category_spending(
            selected_filters.start_month,
            selected_filters.end_month,
            selected_filters.currency,
            series=raw_series,
        )
        return ExpenseDashboard(
            filters=selected_filters,
            selected_month=self._point(selected) if selected else None,
            series=points,
            categories=categories,
            behavior_totals=behavior_totals,
            category_comparisons=category_comparisons,
            potential_recurring_spending=recurring,
            unusual_category_spending=anomalies,
            currency=selected_filters.currency,
        )

    def contributors(self, transaction_ids: list[int] | tuple[int, ...]) -> list[TransactionContribution]:
        rows = self.repository.contributor_rows(transaction_ids)
        result: list[TransactionContribution] = []
        for row in rows:
            classification = self.classifier.classify_one(int(row["id"]))
            result.append(
                TransactionContribution(
                    transaction_id=int(row["id"]),
                    booking_date=date.fromisoformat(str(row["booking_date"])),
                    description=str(row["description"]),
                    amount=Decimal(str(row["amount"])),
                    currency=str(row["currency"]).upper(),
                    source_category=str(row["category"]),
                    movement_type=row.get("movement_type"),
                    account_label=str(row.get("account_label") or ""),
                    account_kind=str(row.get("account_kind") or ""),
                    effective_classification=classification.economic_class,
                    classification_source=classification.source,
                    analysis_category=classification.analysis_category,
                    expense_behavior=classification.expense_behavior,
                )
            )
        return result

    def data_quality(
        self,
        filters: DashboardFilters | dict[str, Any] | None = None,
    ) -> DataQualityDashboard:
        selected_filters = self._filters(filters) if filters else self.default_filters()
        end_exclusive = _month_shift(selected_filters.end_month, 1)
        scoped_rows = self.repository.accepted_transactions(
            start=selected_filters.start_month,
            end=end_exclusive,
        )
        transactions = [
            row
            for row in scoped_rows
            if str(row["currency"]).upper() == selected_filters.currency
        ]
        issue_counts: Counter[str] = Counter()
        currencies: Counter[str] = Counter()
        for row in scoped_rows:
            currencies[str(row["currency"]).upper()] += 1
            source_issues = self.repository.source_info(int(row["id"])).get("issues", [])
            source_codes = {str(issue.get("code", "UNKNOWN")) for issue in source_issues}
            issue_counts.update(source_codes)
            classification = self.classifier._classify_row(row)
            issue_counts.update(
                issue.code for issue in classification.issues if issue.code not in source_codes
            )
        classifications = [self.classifier._classify_row(row) for row in transactions]
        unclassified = [item for item in classifications if item.economic_class.value == "unclassified"]
        metrics = self.metrics.calculate_monthly_series(
            selected_filters.start_month,
            selected_filters.end_month,
            selected_filters.currency,
        )
        latest = self.repository.latest_batch()
        scoped_dates = [date.fromisoformat(str(row["booking_date"])) for row in scoped_rows]
        return DataQualityDashboard(
            latest_import=latest,
            freshness_date=max(scoped_dates) if scoped_dates else None,
            covered_start=min(scoped_dates) if scoped_dates else None,
            covered_end=max(scoped_dates) if scoped_dates else None,
            currencies=dict(currencies),
            issue_counts=dict(issue_counts),
            incomplete_months=[item.month for item in metrics if not item.completeness.complete],
            open_reconciliation_cases=len(
                self.repository.open_cases_in_period(selected_filters.start_month, end_exclusive)
            ),
            unclassified_transaction_count=len(unclassified),
            unclassified_absolute_amount=sum((abs(item.amount) for item in unclassified), Decimal(0)),
            source_coverage=metrics[-1].completeness.source_coverage if metrics else "unknown",
        )


__all__ = ["DashboardService"]
