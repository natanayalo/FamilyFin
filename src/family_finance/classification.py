"""Deterministic, explainable transaction classification services."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Any

from family_finance.models import (
    ClassificationOverride,
    ClassificationResult,
    ClassificationReviewItem,
    ClassificationRule,
    ClassificationSource,
    DataQualityIssue,
    EconomicClass,
    ExpenseBehavior,
)
from family_finance.persistence.db import Database
from family_finance.persistence.repositories import FinancialRepository

CLASSIFICATION_POLICY_VERSION = "classification-v1"
_SPACE_RE = re.compile(r"\s+")


def _text(value: Any) -> str:
    return _SPACE_RE.sub(" ", str(value or "").strip().casefold())


def _has(text: str, *terms: str) -> bool:
    return any(_text(term) in text for term in terms)


def _direction(amount: Decimal) -> str:
    if amount < 0:
        return "debit"
    if amount > 0:
        return "credit"
    return "zero"


def _enum_or(value: Any, enum_type, fallback):
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        return fallback


def _class_sign_issue(economic_class: EconomicClass, amount: Decimal) -> str | None:
    """Return an issue when an effective class cannot have this source sign."""

    positive_only = {EconomicClass.INCOME, EconomicClass.REFUND}
    negative_only = {
        EconomicClass.CONSUMPTION,
        EconomicClass.CREDIT_CARD_SETTLEMENT,
        EconomicClass.DEBT_PRINCIPAL,
    }
    if economic_class in positive_only and amount <= 0:
        return f"{economic_class.value} requires a positive credit amount"
    if economic_class in negative_only and amount >= 0:
        return f"{economic_class.value} requires a negative debit amount"
    if economic_class == EconomicClass.SAVINGS_TRANSFER and amount == 0:
        return "savings_transfer requires a non-zero amount"
    return None


class ClassificationService:
    """Classify accepted normalized transactions using a fixed precedence."""

    def __init__(
        self,
        database: Database,
        *,
        policy_version: str = CLASSIFICATION_POLICY_VERSION,
    ) -> None:
        self.database = database
        self.repository = FinancialRepository(database)
        self.policy_version = policy_version

    def classify_one(self, transaction_id: int) -> ClassificationResult:
        transaction = self.repository.transaction(transaction_id)
        if not transaction:
            raise ValueError(f"Transaction {transaction_id} not found")
        return self._classify_row(transaction)

    def classify_transaction(self, transaction_id: int) -> ClassificationResult:
        return self.classify_one(transaction_id)

    def classify_many(
        self,
        transaction_ids: Iterable[int] | None = None,
        *,
        currency: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[ClassificationResult]:
        if transaction_ids is None:
            rows = self.repository.accepted_transactions(
                currency=currency, start=start, end=end
            )
        else:
            rows = []
            for transaction_id in transaction_ids:
                transaction = self.repository.transaction(int(transaction_id))
                if transaction:
                    rows.append(transaction)
        return [self._classify_row(row) for row in rows]

    def _classify_row(self, row: dict[str, Any]) -> ClassificationResult:
        amount = Decimal(str(row["amount"]))
        source_category = str(row["category"])
        source_movement_type = row.get("movement_type")
        normalized_movement = source_movement_type or ""
        account_kind = str(row.get("account_kind") or "")
        currency = str(row["currency"]).upper()
        direction = _direction(amount)
        issues = self._source_issues(row["id"])
        source_info = self.repository.source_info(row["id"])
        normalized = source_info.get("normalized", {})
        original_amount = normalized.get("original_amount", row.get("original_amount"))

        overrides = self.repository.latest_overrides(row["id"])
        effective_override = {
            item["field_name"]: item for item in overrides if item["value"] is not None
        }
        rule = self.repository.latest_rule(
            account_kind=account_kind,
            direction=direction,
            source_category=source_category,
            source_movement_type=normalized_movement,
            currency=currency,
        )
        builtin_class, builtin_behavior, builtin_category, builtin_explanation = self._builtin(
            row,
            amount=amount,
            original_amount=original_amount,
            account_kind=account_kind,
        )
        active_rule = bool(
            rule
            and int(rule.get("is_active", 0))
            and not int(rule.get("is_tombstone", 0))
        )
        if active_rule:
            base_class = _enum_or(
                rule.get("economic_class"), EconomicClass, EconomicClass.UNCLASSIFIED
            )
            base_behavior = _enum_or(
                rule.get("expense_behavior"), ExpenseBehavior, ExpenseBehavior.UNKNOWN
            )
            base_category = rule.get("analysis_category")
            base_explanation = rule.get("reason") or "Matched the latest active reusable rule."
        else:
            base_class = builtin_class
            base_behavior = builtin_behavior
            base_category = builtin_category
            base_explanation = builtin_explanation

        if effective_override:
            economic_class = _enum_or(
                effective_override.get("economic_class", {}).get("value"),
                EconomicClass,
                base_class,
            )
            behavior = _enum_or(
                effective_override.get("expense_behavior", {}).get("value"),
                ExpenseBehavior,
                base_behavior,
            )
            category_item = effective_override.get("analysis_category")
            analysis_category = (
                category_item["value"] if category_item else base_category
            )
            source = ClassificationSource.OVERRIDE
            explanation = "A transaction-specific override is the effective decision."
            rule_id = int(rule["id"]) if active_rule and rule else None
            override_ids = [int(item["id"]) for item in effective_override.values()]
        elif active_rule:
            economic_class = base_class
            behavior = base_behavior
            analysis_category = base_category
            source = ClassificationSource.REUSABLE_RULE
            explanation = base_explanation
            rule_id = int(rule["id"])
            override_ids = []
        else:
            economic_class = base_class
            behavior = base_behavior
            analysis_category = base_category
            explanation = base_explanation
            source = (
                ClassificationSource.BUILTIN_RULE
                if economic_class != EconomicClass.UNCLASSIFIED
                else ClassificationSource.UNCLASSIFIED
            )
            rule_id = None
            override_ids = []

        # Description-only transfer signals are a conservative guard for the
        # generic built-in purchase fallback.  They must not override a
        # stronger source label, reusable rule, or transaction override, but
        # an otherwise generic bank debit should remain in review rather than
        # inflate consumption.
        description_transfer_signal = (
            not active_rule
            and not effective_override
            and builtin_class == EconomicClass.CONSUMPTION
            and builtin_explanation == "Ordinary negative bank or card purchase."
            and self._description_transfer_signal(row, amount)
        )
        if description_transfer_signal:
            issues.append(
                DataQualityIssue(
                    code="DESCRIPTION_TRANSFER_SIGNAL",
                    message=(
                        "The description suggests a transfer while source labels are generic; "
                        "review the economic destination before counting consumption."
                    ),
                    severity="warning",
                )
            )
            economic_class = EconomicClass.UNCLASSIFIED
            behavior = ExpenseBehavior.NOT_APPLICABLE
            analysis_category = None
            explanation = (
                "A description-only transfer signal requires review because the source labels "
                "do not identify the economic destination."
            )

        # A category is a default only for spending-like classes.  It remains
        # source-backed, while a user can explicitly replace it with an override.
        if (
            analysis_category is None
            and economic_class in {EconomicClass.CONSUMPTION, EconomicClass.REFUND}
        ):
            analysis_category = source_category
        if economic_class in {
            EconomicClass.CONSUMPTION,
            EconomicClass.REFUND,
        } and behavior == ExpenseBehavior.NOT_APPLICABLE:
            behavior = ExpenseBehavior.UNKNOWN

        sign_issue = _class_sign_issue(economic_class, amount)
        if sign_issue:
            issues.append(
                DataQualityIssue(
                    code="INVALID_CLASS_SIGN",
                    message=f"Effective classification is invalid: {sign_issue}.",
                    severity="error",
                )
            )
            economic_class = EconomicClass.UNCLASSIFIED
            behavior = ExpenseBehavior.NOT_APPLICABLE
            analysis_category = None
            explanation = (
                "The effective class conflicts with the transaction direction and was "
                "marked unclassified."
            )

        if economic_class == EconomicClass.UNCLASSIFIED:
            issues.append(
                DataQualityIssue(
                    code="UNCLASSIFIED_TRANSACTION",
                    message="No override, reusable rule, or conservative built-in rule matched",
                    severity="warning",
                )
            )

        return ClassificationResult(
            transaction_id=int(row["id"]),
            booking_date=date.fromisoformat(str(row["booking_date"])),
            amount=amount,
            currency=currency,
            account_kind=account_kind,
            source_category=source_category,
            source_movement_type=source_movement_type,
            economic_class=economic_class,
            expense_behavior=behavior,
            analysis_category=analysis_category,
            source=source,
            policy_version=self.policy_version,
            explanation=explanation,
            issues=issues,
            rule_id=rule_id,
            override_ids=override_ids,
        )

    def _source_issues(self, transaction_id: int) -> list[DataQualityIssue]:
        source_info = self.repository.source_info(transaction_id)
        return [
            DataQualityIssue.model_validate(issue)
            for issue in source_info.get("issues", [])
        ]

    @staticmethod
    def _description_transfer_signal(row: dict[str, Any], amount: Decimal) -> bool:
        if amount >= 0:
            return False
        description = _text(row.get("description"))
        return _has(
            description,
            "transfer",
            "internal transfer",
            "bank transfer",
            "העברה ל",
            "העברה לא",
            "העברה אל",
        )

    @staticmethod
    def _builtin(
        row: dict[str, Any],
        *,
        amount: Decimal,
        original_amount: Any,
        account_kind: str,
    ) -> tuple[EconomicClass, ExpenseBehavior, str | None, str]:
        category = _text(row.get("category"))
        movement = _text(row.get("movement_type"))
        # Economic classification is driven by immutable source labels.  A
        # merchant description can mention a transfer, cash, or refund even
        # when the source category/movement says otherwise; using it as a
        # class-changing signal silently changes cash-flow metrics.
        labels = f"{category} {movement}"
        kind = _text(account_kind)

        if amount == 0 or (
            original_amount not in (None, "", "0", "0.0", 0, Decimal(0))
            and amount == 0
        ):
            return (
                EconomicClass.UNCLASSIFIED,
                ExpenseBehavior.NOT_APPLICABLE,
                None,
                "Zero amount or original-amount anomaly requires review.",
            )
        if _has(labels, "cash withdrawal", "atm", "משיכת מזומן", "כספומט"):
            return (
                EconomicClass.UNCLASSIFIED,
                ExpenseBehavior.NOT_APPLICABLE,
                None,
                "Cash withdrawals have no reliable economic destination in the source.",
            )
        if _has(labels, "loan", "mortgage", "הלווא", "משכנת"):
            if _has(labels, "interest", "ריבית"):
                return (
                    EconomicClass.CONSUMPTION,
                    ExpenseBehavior.UNKNOWN,
                    None,
                    "Loan interest is treated as consumption; behavior remains unknown.",
                )
            if _has(labels, "principal", "קרן"):
                return (
                    EconomicClass.DEBT_PRINCIPAL,
                    ExpenseBehavior.NOT_APPLICABLE,
                    None,
                    "The source explicitly identifies the debt-principal component.",
                )
            return (
                EconomicClass.UNCLASSIFIED,
                ExpenseBehavior.NOT_APPLICABLE,
                None,
                "An unsplit loan payment does not reveal interest versus principal.",
            )
        if _text(kind) == "bank" and _has(
            labels,
            "credit card",
            "card charge",
            "card settlement",
            "אשראי",
            "כרטיס",
        ) and _has(labels, "variable", "משתנה", "משתנות", "חיוב"):
            return (
                EconomicClass.CREDIT_CARD_SETTLEMENT,
                ExpenseBehavior.NOT_APPLICABLE,
                None,
                "A bank row explicitly labeled as a variable credit-card charge is a settlement.",
            )
        if amount > 0 and _text(kind) == "bank" and _has(
            labels,
            "salary",
            "wage",
            "payroll",
            "business income",
            "salary income",
            "משכורת",
            "שכר",
            "הכנסה מעסק",
            "עסק",
        ):
            return (
                EconomicClass.INCOME,
                ExpenseBehavior.NOT_APPLICABLE,
                None,
                "Positive bank salary or business-income category.",
            )
        if amount > 0 and _has(
            labels,
            "refund",
            "rebate",
            "cashback",
            "reversal",
            "החזר",
            "זיכוי",
        ):
            return (
                EconomicClass.REFUND,
                ExpenseBehavior.UNKNOWN,
                None,
                "Positive refund-category row reduces consumption in its booking month.",
            )
        if _has(
            labels,
            "savings",
            "investment",
            "deposit",
            "provident",
            "pension",
            "חיסכון",
            "השקעה",
            "פיקדון",
            "פנסיה",
        ):
            return (
                EconomicClass.SAVINGS_TRANSFER,
                ExpenseBehavior.NOT_APPLICABLE,
                None,
                "The source category explicitly identifies savings or investment activity.",
            )
        if amount > 0 and _text(kind) == "card" and _has(
            labels,
            "business income",
            "income",
            "salary",
            "הכנסה",
            "משכורת",
        ):
            return (
                EconomicClass.UNCLASSIFIED,
                ExpenseBehavior.NOT_APPLICABLE,
                None,
                "Positive card income-like rows are not assumed to be household income.",
            )
        # A card purchase can mention a payment rail such as PayBox in its
        # description while its source category/movement still says ordinary
        # spending. Treat transfers as ambiguous when the source labels the
        # row as a transfer.
        if _has(
            labels,
            "transfer",
            "bank transfer",
            "internal",
            "העברה",
            "העברה בנקאית",
        ):
            return (
                EconomicClass.UNCLASSIFIED,
                ExpenseBehavior.NOT_APPLICABLE,
                None,
                "An unlinked transfer cannot be assigned to an internal or external account.",
            )
        if amount < 0 and _text(kind) in {"bank", "card"}:
            return (
                EconomicClass.CONSUMPTION,
                ExpenseBehavior.UNKNOWN,
                str(row.get("category")),
                "Ordinary negative bank or card purchase.",
            )
        return (
            EconomicClass.UNCLASSIFIED,
            ExpenseBehavior.NOT_APPLICABLE,
            None,
            "Generic positive or otherwise ambiguous source row remains unclassified.",
        )

    def review_queue(
        self,
        *,
        month: date | str | None = None,
        account_kind: str | None = None,
        currency: str | None = None,
        issue: str | None = None,
        economic_class: EconomicClass | str | None = None,
        classification_source: ClassificationSource | str | None = None,
        include_resolved: bool = False,
    ) -> list[ClassificationReviewItem]:
        if isinstance(month, str):
            month = date.fromisoformat(f"{month}-01" if len(month) == 7 else month[:10])
        rows = self.repository.accepted_transactions(currency=currency)
        result: list[ClassificationReviewItem] = []
        for row in rows:
            classification = self._classify_row(row)
            if (
                not include_resolved
                and classification.economic_class != EconomicClass.UNCLASSIFIED
                and not issue
            ):
                continue
            if month and classification.booking_date.replace(day=1) != month.replace(day=1):
                continue
            if account_kind and _text(classification.account_kind) != _text(account_kind):
                continue
            if currency and classification.currency.upper() != currency.upper():
                continue
            economic_filter = (
                economic_class.value
                if isinstance(economic_class, EconomicClass)
                else str(economic_class)
            )
            if economic_class and classification.economic_class.value != economic_filter:
                continue
            source_filter = (
                classification_source.value
                if isinstance(classification_source, ClassificationSource)
                else str(classification_source)
            )
            if classification_source and classification.source.value != source_filter:
                continue
            if issue and not any(issue.casefold() in item.code.casefold() for item in classification.issues):
                continue
            source_info = self.repository.source_info(int(row["id"]))
            result.append(
                ClassificationReviewItem(
                    transaction_id=int(row["id"]),
                    booking_date=classification.booking_date,
                    amount=classification.amount,
                    currency=classification.currency,
                    description=str(row["description"]),
                    account_kind=classification.account_kind,
                    source_category=classification.source_category,
                    source_movement_type=classification.source_movement_type,
                    effective_classification=classification,
                    source_fields={
                        "category": row["category"],
                        "movement_type": row["movement_type"],
                        "normalized": source_info.get("normalized", {}),
                        "raw_payload": source_info.get("raw_payload", {}),
                    },
                    issues=classification.issues,
                )
            )
        return result

    def list_review_queue(self, **filters: Any) -> list[ClassificationReviewItem]:
        return self.review_queue(**filters)

    def preview_override(
        self,
        transaction_id: int,
        override: ClassificationOverride | dict[str, Any],
    ) -> ClassificationResult:
        values = self._override_values(override)
        current = self.classify_one(transaction_id)
        return current.model_copy(
            update={
                "economic_class": values.get("economic_class", current.economic_class),
                "analysis_category": values.get(
                    "analysis_category", current.analysis_category
                ),
                "expense_behavior": values.get(
                    "expense_behavior", current.expense_behavior
                ),
                "source": ClassificationSource.OVERRIDE,
                "explanation": "Preview of the proposed transaction-specific override.",
            }
        )

    def save_override(
        self,
        transaction_id: int,
        override: ClassificationOverride | dict[str, Any] | None = None,
        *,
        economic_class: EconomicClass | str | None = None,
        analysis_category: str | None = None,
        expense_behavior: ExpenseBehavior | str | None = None,
        reason: str = "",
    ) -> ClassificationResult:
        if override is None:
            override = {
                "transaction_id": transaction_id,
                "economic_class": economic_class,
                "analysis_category": analysis_category,
                "expense_behavior": expense_behavior,
                "reason": reason,
            }
        values = self._override_values(override)
        if not values:
            raise ValueError("At least one override value is required")
        serialized = {
            field: (value.value if hasattr(value, "value") else str(value))
            for field, value in values.items()
        }
        self.repository.append_overrides(
            transaction_id,
            serialized,
            self._override_reason(override, reason),
        )
        return self.classify_one(transaction_id)

    def apply_override(self, transaction_id: int, **values: Any) -> ClassificationResult:
        return self.save_override(transaction_id, **values)

    def preview_transaction_override(
        self,
        transaction_id: int,
        override: ClassificationOverride | dict[str, Any],
    ) -> ClassificationResult:
        return self.preview_override(transaction_id, override)

    def save_transaction_override(
        self,
        transaction_id: int,
        override: ClassificationOverride | dict[str, Any] | None = None,
        **values: Any,
    ) -> ClassificationResult:
        return self.save_override(transaction_id, override, **values)

    def clear_override(
        self,
        transaction_id: int,
        fields: Iterable[str] | None = None,
        *,
        reason: str = "Override cleared",
    ) -> ClassificationResult:
        names = list(fields or ("economic_class", "analysis_category", "expense_behavior"))
        self.repository.append_overrides(
            transaction_id, {field: None for field in names}, reason
        )
        return self.classify_one(transaction_id)

    def clear_transaction_override(
        self, transaction_id: int, fields: Iterable[str] | None = None, **kwargs: Any
    ) -> ClassificationResult:
        return self.clear_override(transaction_id, fields, **kwargs)

    def preview_rule(
        self,
        rule: ClassificationRule | dict[str, Any] | None = None,
        **values: Any,
    ) -> dict[str, Any]:
        parsed = self._rule_model(rule if rule is not None else values)
        rows = self.repository.accepted_transactions(
            currency=parsed.currency,
        )
        ids = []
        for row in rows:
            if self._rule_matches(parsed, row):
                ids.append(int(row["id"]))
        return {"count": len(ids), "transaction_count": len(ids), "transaction_ids": ids, "rule": parsed}

    def preview_reusable_rule(
        self, rule: ClassificationRule | dict[str, Any] | None = None, **values: Any
    ) -> dict[str, Any]:
        return self.preview_rule(rule if rule is not None else values)

    def create_rule(
        self,
        rule: ClassificationRule | dict[str, Any] | None = None,
        **values: Any,
    ) -> ClassificationRule:
        return self.repository.save_rule(
            self._rule_model(rule if rule is not None else values)
        )

    def create_reusable_rule(
        self,
        rule: ClassificationRule | dict[str, Any] | None = None,
        **values: Any,
    ) -> ClassificationRule:
        return self.create_rule(rule, **values)

    def save_rule(
        self,
        rule: ClassificationRule | dict[str, Any] | None = None,
        **values: Any,
    ) -> ClassificationRule:
        return self.create_rule(rule, **values)

    def supersede_rule(
        self,
        rule: ClassificationRule | dict[str, Any] | None = None,
        **values: Any,
    ) -> ClassificationRule:
        return self.create_rule(rule, **values)

    def disable_rule(
        self,
        rule: ClassificationRule | dict[str, Any] | int,
        *,
        reason: str = "Reusable rule disabled",
    ) -> ClassificationRule:
        if isinstance(rule, int):
            existing = next(
                (item for item in self.repository.all_rules() if int(item["id"]) == rule), None
            )
            if not existing:
                raise ValueError(f"Rule {rule} not found")
            if not existing["is_current"]:
                raise ValueError("Only the current rule revision can be disabled")
            parsed = self._rule_model(existing)
        else:
            parsed = self._rule_model(rule)
            if parsed.id is not None:
                existing = next(
                    (
                        item
                        for item in self.repository.all_rules()
                        if int(item["id"]) == int(parsed.id)
                    ),
                    None,
                )
                if existing and not existing["is_current"]:
                    raise ValueError("Only the current rule revision can be disabled")
        return self.repository.save_rule(
            parsed.model_copy(update={"active": False, "tombstone": True, "reason": reason})
        )

    def disable_reusable_rule(
        self,
        rule: ClassificationRule | dict[str, Any] | int,
        *,
        reason: str = "Reusable rule disabled",
    ) -> ClassificationRule:
        return self.disable_rule(rule, reason=reason)

    def list_rules(self) -> list[dict[str, Any]]:
        return self.repository.all_rules()

    def _rule_model(self, value: ClassificationRule | dict[str, Any]) -> ClassificationRule:
        if isinstance(value, ClassificationRule):
            return value
        payload = dict(value)
        payload.pop("is_current", None)
        payload.pop("effective_active", None)
        if "is_active" in payload:
            payload.setdefault("active", bool(payload.pop("is_active")))
        if "is_tombstone" in payload:
            payload.setdefault("tombstone", bool(payload.pop("is_tombstone")))
        payload.setdefault("source_movement_type", payload.pop("movement_type", None))
        payload.setdefault("source_category", payload.pop("category", ""))
        payload.setdefault("currency", "ILS")
        payload.setdefault("account_kind", "bank")
        payload.setdefault("direction", "debit")
        payload.setdefault("economic_class", EconomicClass.UNCLASSIFIED)
        if "expense_behavior" not in payload:
            economic_class = _enum_or(
                payload["economic_class"], EconomicClass, EconomicClass.UNCLASSIFIED
            )
            payload["expense_behavior"] = (
                ExpenseBehavior.UNKNOWN
                if economic_class in {EconomicClass.CONSUMPTION, EconomicClass.REFUND}
                else ExpenseBehavior.NOT_APPLICABLE
            )
        return ClassificationRule.model_validate(payload)

    @staticmethod
    def _rule_matches(rule: ClassificationRule, row: dict[str, Any]) -> bool:
        return (
            _text(row.get("account_kind")) == _text(rule.account_kind)
            and _direction(Decimal(str(row["amount"]))) == rule.direction
            and str(row.get("category")) == rule.source_category
            and (row.get("movement_type") or "") == (rule.source_movement_type or "")
            and str(row.get("currency")).upper() == rule.currency.upper()
        )

    @staticmethod
    def _override_values(
        override: ClassificationOverride | dict[str, Any],
    ) -> dict[str, Any]:
        if isinstance(override, ClassificationOverride):
            payload = override.model_dump()
        else:
            payload = dict(override)
        values = {
            field: payload[field]
            for field in ("economic_class", "analysis_category", "expense_behavior")
            if field in payload and payload[field] is not None
        }
        if "economic_class" in values:
            values["economic_class"] = EconomicClass(values["economic_class"])
        if "expense_behavior" in values:
            values["expense_behavior"] = ExpenseBehavior(values["expense_behavior"])
        return values

    @staticmethod
    def _override_reason(override: ClassificationOverride | dict[str, Any], fallback: str) -> str:
        if isinstance(override, ClassificationOverride):
            return override.reason or fallback
        return str(override.get("reason") or fallback)


FinancialClassificationService = ClassificationService
ClassificationEngine = ClassificationService


__all__ = [
    "CLASSIFICATION_POLICY_VERSION",
    "ClassificationEngine",
    "ClassificationService",
    "FinancialClassificationService",
]
