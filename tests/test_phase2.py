from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from family_finance.classification import ClassificationService
from family_finance.config import Settings
from family_finance.metrics import MetricsService
from family_finance.models import EconomicClass, ExpenseBehavior
from family_finance.services import ImportService

from .conftest import make_workbook


def _import(tmp_path, rows):
    app = ImportService(Settings(data_root=tmp_path / "local"))
    workbook = make_workbook(rows, provider="בנק", reference="bank-reference")
    preview = app.preview_import(workbook, "phase2.xlsx")
    app.commit_import(workbook, preview.preview_token, "phase2.xlsx")
    return app


def test_classification_precedence_and_append_only_clearing(tmp_path):
    app = _import(
        tmp_path,
        [["01/09/2026", -100, "shop", "01/09/2026", "purchase", "food", "ILS", "ILS", -100]],
    )
    classifier = ClassificationService(app.database)

    classifier.create_rule(
        {
            "account_kind": "bank",
            "direction": "debit",
            "source_category": "food",
            "source_movement_type": "purchase",
            "currency": "ILS",
            "economic_class": "consumption",
            "analysis_category": "groceries",
            "expense_behavior": "fixed",
        }
    )
    assert classifier.classify_one(1).analysis_category == "groceries"

    classifier.save_override(1, economic_class="debt_principal", reason="review")
    overridden = classifier.classify_one(1)
    assert overridden.economic_class == EconomicClass.DEBT_PRINCIPAL
    assert overridden.source.value == "override"

    classifier.clear_override(1, fields=["economic_class"])
    restored = classifier.classify_one(1)
    assert restored.economic_class == EconomicClass.CONSUMPTION
    assert restored.expense_behavior == ExpenseBehavior.FIXED
    assert app.database.count("analysis_overrides") == 2


def test_metrics_signs_and_contributor_reconciliation(tmp_path):
    app = _import(
        tmp_path,
        [
            ["01/09/2026", 1000, "salary", "01/09/2026", "credit", "salary", "ILS", "ILS", 1000],
            ["02/09/2026", -250, "shop", "02/09/2026", "debit", "food", "ILS", "ILS", -250],
            ["03/09/2026", 50, "shop", "03/09/2026", "credit", "refund", "ILS", "ILS", 50],
            ["04/09/2026", -100, "broker", "04/09/2026", "debit", "savings", "ILS", "ILS", -100],
            ["30/09/2026", 1, "salary", "30/09/2026", "credit", "salary", "ILS", "ILS", 1],
        ],
    )
    metrics = MetricsService(app.database).calculate_monthly_metrics("2026-09")

    assert metrics.gross_income == Decimal(1001)
    assert metrics.gross_consumption == Decimal(250)
    assert metrics.refunds == Decimal(50)
    assert metrics.net_consumption == Decimal(200)
    assert metrics.operating_surplus_or_deficit == Decimal(801)
    assert metrics.savings_contributions == Decimal(100)
    assert metrics.net_observed_savings_transfers == Decimal(100)
    assert metrics.contributors_for("gross_consumption") == [2]
    assert metrics.completeness.complete


def test_structural_labels_beat_description_heuristics(tmp_path):
    app = _import(
        tmp_path,
        [
            [
                "01/09/2026",
                -400,
                "cash description",
                "01/09/2026",
                "כרטיסי אשראי משתנות",
                "שונות",
                "ILS",
                "ILS",
                -400,
            ],
            [
                "02/09/2026",
                100,
                "זיכוי transfer description",
                "02/09/2026",
                None,
                "העברה מחשבון אחר",
                "ILS",
                "ILS",
                100,
            ],
            [
                "03/09/2026",
                100,
                "refund description",
                "03/09/2026",
                None,
                "אחר",
                "ILS",
                "ILS",
                100,
            ],
            [
                "04/09/2026",
                100,
                "transfer description",
                "04/09/2026",
                None,
                "החזרים",
                "ILS",
                "ILS",
                100,
            ],
            [
                "05/09/2026",
                -1850,
                "העברה לאפרת מיכל",
                "05/09/2026",
                "שונות חד פעמי",
                "שונות",
                "ILS",
                "ILS",
                -1850,
            ],
        ],
    )
    results = ClassificationService(app.database).classify_many()

    assert results[0].economic_class == EconomicClass.CREDIT_CARD_SETTLEMENT
    assert results[1].economic_class == EconomicClass.UNCLASSIFIED
    assert results[2].economic_class == EconomicClass.UNCLASSIFIED
    assert results[3].economic_class == EconomicClass.REFUND
    assert results[4].economic_class == EconomicClass.UNCLASSIFIED
    assert any(issue.code == "DESCRIPTION_TRANSFER_SIGNAL" for issue in results[4].issues)


def test_invalid_class_sign_is_unclassified_and_incomplete(tmp_path):
    app = _import(
        tmp_path,
        [["01/09/2026", -100, "shop", "01/09/2026", "purchase", "food", "ILS", "ILS", -100]],
    )
    classifier = ClassificationService(app.database)
    classifier.create_rule(
        {
            "account_kind": "bank",
            "direction": "debit",
            "source_category": "food",
            "source_movement_type": "purchase",
            "currency": "ILS",
            "economic_class": "income",
            "expense_behavior": "not_applicable",
        }
    )

    rule_result = classifier.classify_one(1)
    assert rule_result.economic_class == EconomicClass.UNCLASSIFIED
    assert any(issue.code == "INVALID_CLASS_SIGN" for issue in rule_result.issues)

    classifier.save_override(1, economic_class="income", reason="invalid test")

    result = classifier.classify_one(1)
    assert result.economic_class == EconomicClass.UNCLASSIFIED
    assert any(issue.code == "INVALID_CLASS_SIGN" for issue in result.issues)

    metrics = MetricsService(app.database).calculate_monthly_metrics("2026-09")
    assert metrics.unclassified_transaction_count == 1
    assert not metrics.completeness.classification_complete
    assert metrics.savings_rate is None


def test_partial_trailing_month_does_not_use_report_end_as_evidence(tmp_path):
    app = _import(
        tmp_path,
        [
            ["01/09/2026", 1000, "salary", "01/09/2026", "credit", "salary", "ILS", "ILS", 1000],
            ["19/09/2026", -100, "shop", "19/09/2026", "debit", "food", "ILS", "ILS", -100],
        ],
    )
    metrics = MetricsService(app.database).calculate_monthly_metrics("2026-09")

    assert not metrics.source_period_completeness.source_period_complete
    assert "SOURCE_PERIOD_PARTIAL_OR_UNKNOWN" in metrics.completeness.issues
    assert metrics.savings_rate is None


def test_rule_supersession_and_current_revision_only_disable(tmp_path):
    app = _import(
        tmp_path,
        [["01/09/2026", -100, "shop", "01/09/2026", "purchase", "food", "ILS", "ILS", -100]],
    )
    classifier = ClassificationService(app.database)
    payload = {
        "account_kind": "bank",
        "direction": "debit",
        "source_category": "food",
        "source_movement_type": "purchase",
        "currency": "ILS",
        "economic_class": "consumption",
        "expense_behavior": "fixed",
    }
    first = classifier.create_rule(payload)
    second = classifier.create_rule({**payload, "expense_behavior": "variable"})

    rules = classifier.list_rules()
    assert next(rule for rule in rules if rule["id"] == first.id)["is_current"] is False
    assert next(rule for rule in rules if rule["id"] == second.id)["effective_active"] is True
    with pytest.raises(ValueError, match="current rule revision"):
        classifier.disable_rule(first.id)

    classifier.disable_rule(second.id)
    assert classifier.classify_one(1).source.value == "builtin_rule"


def test_non_ils_rows_are_visible_but_excluded_from_default_metrics(tmp_path):
    app = _import(
        tmp_path,
        [["01/09/2026", -50, "shop", "01/09/2026", "purchase", "food", "USD", "USD", -50]],
    )
    classifier = ClassificationService(app.database)
    assert classifier.classify_one(1).currency == "USD"

    ils = MetricsService(app.database).calculate_monthly_metrics("2026-09")
    usd = MetricsService(app.database).calculate_monthly_metrics("2026-09", "USD")
    assert ils.gross_consumption == Decimal(0)
    assert usd.gross_consumption == Decimal(50)


def test_complete_month_comparisons_and_rolling_values(tmp_path):
    app = _import(
        tmp_path,
        [
            ["01/12/2025", 1000, "salary", "01/12/2025", "credit", "salary", "ILS", "ILS", 1000],
            ["02/12/2025", -100, "shop", "02/12/2025", "debit", "food", "ILS", "ILS", -100],
            ["01/01/2026", 1200, "salary", "01/01/2026", "credit", "salary", "ILS", "ILS", 1200],
            ["02/01/2026", -200, "shop", "02/01/2026", "debit", "food", "ILS", "ILS", -200],
            ["01/02/2026", 1500, "salary", "01/02/2026", "credit", "salary", "ILS", "ILS", 1500],
            ["02/02/2026", -300, "shop", "02/02/2026", "debit", "food", "ILS", "ILS", -300],
            ["19/09/2026", 1, "salary", "19/09/2026", "credit", "salary", "ILS", "ILS", 1],
        ],
    )
    metrics = MetricsService(app.database).calculate_monthly_metrics("2026-02")

    assert metrics.completeness.complete
    assert metrics.month_over_month_changes["gross_income"] == Decimal(300)
    assert metrics.year_over_year_changes["gross_income"] is None
    assert metrics.rolling_three_month_averages["gross_consumption"] == Decimal("200.0000")


@pytest.mark.skipif(
    not Path("data/familybiz report 21-09-26.xlsx").exists(),
    reason="supplied local workbook is not present",
)
def test_supplied_workbook_policy_counts_and_trailing_completeness(tmp_path):
    app = ImportService(Settings(data_root=tmp_path / "local"))
    workbook_path = Path("data/familybiz report 21-09-26.xlsx")
    workbook = workbook_path.read_bytes()
    preview = app.preview_import(workbook, workbook_path.name)
    app.commit_import(workbook, preview.preview_token, workbook_path.name)
    classifier = ClassificationService(app.database)
    results = classifier.classify_many()

    assert sum(result.economic_class != EconomicClass.UNCLASSIFIED for result in results) == 1398
    assert len(classifier.review_queue()) == 54
    assert sum(result.currency != "ILS" for result in results) == 14
    september = MetricsService(app.database).calculate_monthly_metrics("2026-09")
    assert not september.completeness.complete
    assert september.savings_rate is None
