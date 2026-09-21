"""Deterministic, non-persisted dashboard insight detectors."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from itertools import pairwise
from statistics import median

from family_finance.classification import ClassificationService
from family_finance.metrics import MetricsService
from family_finance.models import (
    EconomicClass,
    MonthlyMetrics,
    PotentialRecurringSpending,
    UnusualCategorySpending,
)
from family_finance.persistence.db import Database
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
    ) -> None:
        self.repository = FinancialRepository(database)
        self.classifier = classifier or ClassificationService(database)
        self.metrics = metrics or MetricsService(database, classifier=self.classifier)

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
