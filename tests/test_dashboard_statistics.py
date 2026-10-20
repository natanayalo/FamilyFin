from datetime import date
from decimal import Decimal

import pytest

from family_finance.dashboard import _monthly_distribution, _period_statistics
from family_finance.models import CompletenessAssessment, MonthlyMetrics


@pytest.mark.parametrize(("values", "expected"), [
    ([], (None, None, None, None)),
    (["0"], ("0", "0", "0", "0")),
    (["30", "0", "20", "10"], ("15", "7.5", "15", "22.5")),
    (["-10", "-2", "4"], ("-2.6667", "-6", "-2", "1")),
    (["1", "1", "1", "101"], ("26", "1", "1", "26")),
])
def test_monthly_amount_distribution(values, expected):
    result = _monthly_distribution([Decimal(value) for value in values])
    assert (result.mean, result.p25, result.median, result.p75) == tuple(
        Decimal(value) if value is not None else None for value in expected
    )


def test_distribution_preserves_large_exact_decimals():
    # Values well beyond both JavaScript integers and the default Decimal precision.
    low = Decimal("9007199254740993123456789012345678.1234")
    high = Decimal("9007199254740993123456789012345680.1234")
    result = _monthly_distribution([high, low])
    assert result.mean == Decimal("9007199254740993123456789012345679.1234")
    assert result.median == result.mean
    assert result.p25 == Decimal("9007199254740993123456789012345678.6234")
    assert result.p75 == Decimal("9007199254740993123456789012345679.6234")


def test_statistics_populations_exclude_missing_keep_verified_zero_and_separate_partial():
    def monthly(month, amount, *, count=1, covered=True, complete=True):
        assessment = CompletenessAssessment(
            source_period_complete=covered, classification_complete=complete,
            complete=complete,
        )
        return MonthlyMetrics(
            month=date(2026, month, 1), currency="ILS", classification_policy_version="fixture",
            accepted_transaction_count=count, source_period_completeness=assessment,
            completeness=assessment, gross_income=Decimal(amount),
        )

    series = [
        monthly(4, "0", count=0, covered=False, complete=False),
        monthly(3, "30", complete=False),
        monthly(1, "10"), monthly(2, "0", count=0),
    ]
    result = _period_statistics(series)
    observed, complete = result["observed"], result["complete"]
    assert observed.included_months == [date(2026, month, 1) for month in (1, 2, 3)]
    assert observed.sample_count == 3
    assert observed.partial_months == [date(2026, 3, 1)]
    assert observed.excluded_months == [date(2026, 4, 1)]
    assert observed.metrics["gross_income"].mean == Decimal("13.3333")
    assert complete.included_months == [date(2026, month, 1) for month in (1, 2)]
    assert complete.sample_count == 2
    assert complete.metrics["gross_income"].mean == Decimal("5.0000")
    assert complete.partial_months == []
    assert complete.excluded_months == [date(2026, month, 1) for month in (3, 4)]
    # An observed transaction need not be a financial-metric contributor.
    settlements_only = monthly(5, "0", count=2, covered=False, complete=False)
    assert _period_statistics([settlements_only])["observed"].sample_count == 1
