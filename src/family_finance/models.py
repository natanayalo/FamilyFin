"""Pydantic contracts shared by importers, services, and the UI."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class IssueSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ImportStatus(StrEnum):
    PREVIEW = "preview"
    COMMITTED = "committed"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


class MatchMethod(StrEnum):
    INSERTED = "inserted"
    EXACT_UNCHANGED = "exact_unchanged"
    UNIQUE_UPDATE = "unique_update"
    RECONCILIATION = "reconciliation"


class DataQualityIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    severity: IssueSeverity = IssueSeverity.WARNING
    source_row: int | None = None
    section_index: int | None = None


class AccountDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    kind: str
    display_label: str
    source_reference_fingerprint: str
    currency: str


class ParsedSourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sheet_name: str
    section_index: int
    source_row_number: int
    account: AccountDescriptor
    booking_date: date
    amount: Decimal
    description: str
    allocation_date: date
    movement_type: str | None = None
    category: str
    currency: str
    original_currency: str | None = None
    original_amount: Decimal | None = None
    raw_payload: dict[str, Any]
    row_fingerprint: str
    validation_state: str = "accepted"
    issues: list[DataQualityIssue] = Field(default_factory=list)

    @property
    def non_ils(self) -> bool:
        return self.currency.upper() != "ILS"


class NormalizedTransactionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_record: ParsedSourceRecord
    booking_date: date
    allocation_date: date
    amount: Decimal
    currency: str
    description: str
    movement_type: str | None = None
    category: str
    original_currency: str | None = None
    original_amount: Decimal | None = None


class ImportInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parser_version: str
    file_sha256: str
    filename: str | None = None
    compressed_bytes: int
    uncompressed_bytes: int
    sheet_names: list[str]
    section_count: int
    transaction_count: int
    report_start: date | None = None
    report_end: date | None = None
    min_booking_date: date | None = None
    max_booking_date: date | None = None
    currencies: dict[str, int] = Field(default_factory=dict)
    account_kinds: dict[str, int] = Field(default_factory=dict)
    issue_counts: dict[str, int] = Field(default_factory=dict)
    freshness_as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))
    preview_rows: list[dict[str, Any]] = Field(default_factory=list)


class ImportPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_token: str
    inspection: ImportInspection
    parser_version: str
    file_sha256: str
    baseline_batch_id: str | None = None
    candidate_count: int
    warning_count: int
    rejected_count: int
    issue_counts: dict[str, int] = Field(default_factory=dict)
    preview_rows: list[dict[str, Any]] = Field(default_factory=list)


class ReconciliationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    resolution: str
    transaction_id: int | None = None
    note: str | None = None


class ImportStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_records: int = 0
    inserted: int = 0
    unchanged: int = 0
    updated: int = 0
    rejected: int = 0
    ambiguous: int = 0
    unresolved: int = 0
    duplicate_file: bool = False
    non_ils_records: int = 0


class ImportResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str
    status: ImportStatus
    statistics: ImportStatistics
    issues: list[DataQualityIssue] = Field(default_factory=list)


class EconomicClass(StrEnum):
    INCOME = "income"
    CONSUMPTION = "consumption"
    REFUND = "refund"
    INTERNAL_TRANSFER = "internal_transfer"
    SAVINGS_TRANSFER = "savings_transfer"
    CREDIT_CARD_SETTLEMENT = "credit_card_settlement"
    DEBT_PRINCIPAL = "debt_principal"
    UNCLASSIFIED = "unclassified"


class ExpenseBehavior(StrEnum):
    FIXED = "fixed"
    VARIABLE = "variable"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class ClassificationSource(StrEnum):
    OVERRIDE = "override"
    REUSABLE_RULE = "reusable_rule"
    BUILTIN_RULE = "builtin_rule"
    UNCLASSIFIED = "unclassified"


class ClassificationRule(BaseModel):
    """One append-only exact-match rule revision."""

    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    account_kind: str
    direction: str
    source_category: str = Field(
        validation_alias=AliasChoices("source_category", "category")
    )
    source_movement_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices("source_movement_type", "movement_type"),
    )
    currency: str
    economic_class: EconomicClass
    analysis_category: str | None = None
    expense_behavior: ExpenseBehavior = ExpenseBehavior.NOT_APPLICABLE
    active: bool = True
    tombstone: bool = False
    revision: int = 1
    supersedes_rule_id: int | None = None
    reason: str = ""
    created_at: datetime | None = None


class ClassificationOverride(BaseModel):
    """Transaction-specific append-only decisions.

    ``None`` means no value was supplied when creating an override.  A clear is
    represented in persistence by a separate tombstone row and is exposed by
    the service's ``clear_override`` method.
    """

    model_config = ConfigDict(extra="forbid")

    transaction_id: int
    economic_class: EconomicClass | None = None
    analysis_category: str | None = None
    expense_behavior: ExpenseBehavior | None = None
    reason: str = ""
    created_at: datetime | None = None


class ClassificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: int
    booking_date: date
    amount: Decimal
    currency: str
    account_kind: str
    source_category: str
    source_movement_type: str | None = None
    economic_class: EconomicClass
    expense_behavior: ExpenseBehavior
    analysis_category: str | None = None
    source: ClassificationSource
    policy_version: str
    explanation: str
    issues: list[DataQualityIssue] = Field(default_factory=list)
    rule_id: int | None = None
    override_ids: list[int] = Field(default_factory=list)

    @property
    def is_review_required(self) -> bool:
        return self.economic_class == EconomicClass.UNCLASSIFIED or bool(self.issues)

    @property
    def classification_source(self) -> ClassificationSource:
        return self.source

    @property
    def effective_analysis_category(self) -> str | None:
        return self.analysis_category


class CompletenessAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_period_complete: bool
    classification_complete: bool
    complete: bool
    source_coverage: str = "unknown"
    open_reconciliation_count: int = 0
    unclassified_transaction_count: int = 0
    unclassified_absolute_amount: Decimal = Decimal(0)
    issues: list[str] = Field(default_factory=list)


class MetricBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: Decimal | None
    contributor_transaction_ids: list[int] = Field(default_factory=list)
    currency: str | None = None


class MonthlyMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: date
    currency: str
    classification_policy_version: str
    source_period_completeness: CompletenessAssessment
    completeness: CompletenessAssessment
    unclassified_transaction_count: int = 0
    unclassified_absolute_amount: Decimal = Decimal(0)
    data_freshness_date: date | None = None
    gross_income: Decimal = Decimal(0)
    gross_consumption: Decimal = Decimal(0)
    refunds: Decimal = Decimal(0)
    net_consumption: Decimal = Decimal(0)
    operating_surplus_or_deficit: Decimal = Decimal(0)
    savings_rate: Decimal | None = None
    savings_contributions: Decimal = Decimal(0)
    savings_withdrawals: Decimal = Decimal(0)
    net_observed_savings_transfers: Decimal = Decimal(0)
    fixed_consumption: Decimal = Decimal(0)
    variable_consumption: Decimal = Decimal(0)
    unknown_behavior_consumption: Decimal = Decimal(0)
    spending_by_category: dict[str, Decimal] = Field(default_factory=dict)
    historical_monthly_averages: dict[str, Decimal | None] = Field(default_factory=dict)
    rolling_three_month_averages: dict[str, Decimal | None] = Field(default_factory=dict)
    rolling_six_month_averages: dict[str, Decimal | None] = Field(default_factory=dict)
    month_over_month_changes: dict[str, Decimal | None] = Field(default_factory=dict)
    year_over_year_changes: dict[str, Decimal | None] = Field(default_factory=dict)
    breakdowns: dict[str, MetricBreakdown] = Field(default_factory=dict)

    @property
    def policy_version(self) -> str:
        return self.classification_policy_version

    @property
    def rolling_3_month_averages(self) -> dict[str, Decimal | None]:
        return self.rolling_three_month_averages

    @property
    def rolling_6_month_averages(self) -> dict[str, Decimal | None]:
        return self.rolling_six_month_averages

    @property
    def historical_averages(self) -> dict[str, Decimal | None]:
        return self.historical_monthly_averages

    @property
    def operating_surplus(self) -> Decimal:
        return self.operating_surplus_or_deficit

    @property
    def net_savings_transfers(self) -> Decimal:
        return self.net_observed_savings_transfers

    @property
    def unknown_consumption(self) -> Decimal:
        return self.unknown_behavior_consumption

    def contributors_for(self, metric_name: str) -> list[int]:
        breakdown = self.breakdowns.get(metric_name)
        return list(breakdown.contributor_transaction_ids) if breakdown else []


class ClassificationReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: int
    booking_date: date
    amount: Decimal
    currency: str
    description: str
    account_kind: str
    source_category: str
    source_movement_type: str | None = None
    effective_classification: ClassificationResult
    source_fields: dict[str, Any] = Field(default_factory=dict)
    issues: list[DataQualityIssue] = Field(default_factory=list)


__all__ = [
    "AccountDescriptor",
    "ClassificationOverride",
    "ClassificationResult",
    "ClassificationReviewItem",
    "ClassificationRule",
    "ClassificationSource",
    "CompletenessAssessment",
    "DataQualityIssue",
    "EconomicClass",
    "ExpenseBehavior",
    "ImportInspection",
    "ImportPreview",
    "ImportResult",
    "ImportStatistics",
    "ImportStatus",
    "MatchMethod",
    "MetricBreakdown",
    "MonthlyMetrics",
    "NormalizedTransactionCandidate",
    "ParsedSourceRecord",
    "ReconciliationDecision",
]
