"""Pydantic contracts shared by importers, services, and the UI."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


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


class DashboardFilters(BaseModel):
    """Month-aligned, explicit-currency scope shared by every dashboard page."""

    model_config = ConfigDict(extra="forbid")

    start_month: date
    end_month: date
    currency: str = "ILS"

    @field_validator("start_month", "end_month", mode="before")
    @classmethod
    def parse_month(cls, value: date | str) -> date:
        if isinstance(value, str) and len(value) == 7:
            value = f"{value}-01"
        return date.fromisoformat(value) if isinstance(value, str) else value

    @field_validator("start_month", "end_month")
    @classmethod
    def require_month_start(cls, value: date) -> date:
        if value.day != 1:
            raise ValueError("Dashboard months must be the first day of a calendar month")
        return value

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = str(value).strip().upper()
        if not value or len(value) > 12:
            raise ValueError("Currency must be a non-empty short code")
        return value

    @model_validator(mode="after")
    def require_forward_range(self) -> DashboardFilters:
        if self.start_month > self.end_month:
            raise ValueError("Dashboard start_month cannot be after end_month")
        return self


class MonthlySeriesPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: date
    currency: str
    complete: bool
    issue_codes: list[str] = Field(default_factory=list)
    metrics: MonthlyMetrics


class TransactionContribution(BaseModel):
    """A display-independent transaction row used for every dashboard drill-down."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: int
    booking_date: date
    description: str
    amount: Decimal
    currency: str
    source_category: str
    movement_type: str | None = None
    account_label: str
    account_kind: str
    effective_classification: EconomicClass
    classification_source: ClassificationSource
    analysis_category: str | None = None
    expense_behavior: ExpenseBehavior = ExpenseBehavior.NOT_APPLICABLE
    source_category_original: str | None = None


class DashboardComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    current: Decimal | None
    previous: Decimal | None
    delta: Decimal | None
    available: bool
    reason: str | None = None


class OverviewDashboard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filters: DashboardFilters
    selected_month: MonthlySeriesPoint | None = None
    series: list[MonthlySeriesPoint] = Field(default_factory=list)
    headline: dict[str, Decimal | None] = Field(default_factory=dict)
    comparisons: list[DashboardComparison] = Field(default_factory=list)
    freshness_date: date | None = None
    source_coverage: str = "unknown"
    currency: str


class CategorySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    amount: Decimal
    contributor_transaction_ids: list[int] = Field(default_factory=list)


class ExpenseDashboard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filters: DashboardFilters
    selected_month: MonthlySeriesPoint | None = None
    series: list[MonthlySeriesPoint] = Field(default_factory=list)
    categories: list[CategorySummary] = Field(default_factory=list)
    behavior_totals: dict[str, Decimal] = Field(default_factory=dict)
    category_comparisons: list[DashboardComparison] = Field(default_factory=list)
    potential_recurring_spending: list[PotentialRecurringSpending] = Field(default_factory=list)
    unusual_category_spending: list[UnusualCategorySpending] = Field(default_factory=list)
    currency: str


class DataQualityDashboard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latest_import: dict[str, Any] | None = None
    freshness_date: date | None = None
    covered_start: date | None = None
    covered_end: date | None = None
    currencies: dict[str, int] = Field(default_factory=dict)
    issue_counts: dict[str, int] = Field(default_factory=dict)
    incomplete_months: list[date] = Field(default_factory=list)
    open_reconciliation_cases: int = 0
    unclassified_transaction_count: int = 0
    unclassified_absolute_amount: Decimal = Decimal(0)
    source_coverage: str = "unknown"


class PotentialRecurringSpending(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = "Potential pattern"
    normalized_description: str
    analysis_category: str
    currency: str
    account_kind: str
    median_amount: Decimal
    minimum_amount: Decimal
    maximum_amount: Decimal
    amount_range: tuple[Decimal, Decimal]
    occurrence_months: list[date]
    contributor_transaction_ids: list[int] = Field(default_factory=list)


class UnusualCategorySpending(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = "Potential pattern"
    month: date
    category: str
    currency: str
    baseline_median: Decimal
    target_total: Decimal
    difference: Decimal
    direction: str
    rule: str
    contributor_transaction_ids: list[int] = Field(default_factory=list)


class AuditCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    issue_codes: list[str] = Field(default_factory=list)


class AuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    checks: list[AuditCheck] = Field(default_factory=list)


class BackupManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: int = 1
    created_at: datetime
    schema_revision: str
    files: list[dict[str, Any]] = Field(default_factory=list)


class BackupVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    checks: list[AuditCheck] = Field(default_factory=list)


class PlanningItemKind(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    SAVINGS_CONTRIBUTION = "savings_contribution"
    SAVINGS_WITHDRAWAL = "savings_withdrawal"


class PlanningFrequency(StrEnum):
    MONTHLY = "monthly"
    ONE_TIME = "one_time"


class PlanningSeedOrigin(StrEnum):
    MANUAL = "manual"
    HISTORICAL = "historical"
    CSV = "csv"


def _planning_month(value: date | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, str) and len(value) == 7:
        value = f"{value}-01"
    result = date.fromisoformat(value) if isinstance(value, str) else value
    if result.day != 1:
        raise ValueError("Planning dates must be the first day of a calendar month")
    return result


class PlanningItemInput(BaseModel):
    """A positive-magnitude scheduled planning assumption."""

    model_config = ConfigDict(extra="forbid")

    kind: PlanningItemKind
    label: str = Field(validation_alias=AliasChoices("label", "name", "description"))
    category: str | None = None
    amount: Decimal
    frequency: PlanningFrequency
    start_month: date | None = None
    end_month: date | None = None
    occurrence_month: date | None = Field(
        default=None, validation_alias=AliasChoices("occurrence_month", "month")
    )

    @field_validator("start_month", "end_month", "occurrence_month", mode="before")
    @classmethod
    def parse_planning_month(cls, value):
        return _planning_month(value)

    @field_validator("label")
    @classmethod
    def require_label(cls, value: str) -> str:
        value = str(value).strip()
        if not value or len(value) > 500:
            raise ValueError("Planning item label must be non-empty and at most 500 characters")
        return value

    @field_validator("category")
    @classmethod
    def normalize_category(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    @field_validator("amount")
    @classmethod
    def require_non_negative_amount(cls, value: Decimal) -> Decimal:
        value = Decimal(value)
        if not value.is_finite() or value < 0:
            raise ValueError("Planning item amount must be a finite positive magnitude")
        return value

    @model_validator(mode="after")
    def require_schedule(self) -> PlanningItemInput:
        if self.frequency == PlanningFrequency.MONTHLY:
            if self.start_month is None or self.end_month is None:
                raise ValueError("Monthly planning items require start_month and end_month")
            if self.start_month > self.end_month:
                raise ValueError("Planning item start_month cannot be after end_month")
            if self.occurrence_month is not None:
                raise ValueError("Monthly planning items cannot have occurrence_month")
        elif self.occurrence_month is None:
            raise ValueError("One-time planning items require occurrence_month")
        elif self.start_month is not None or self.end_month is not None:
            raise ValueError("One-time planning items cannot have start_month or end_month")
        return self


class PlanningItem(PlanningItemInput):
    id: str = ""
    origin: str = PlanningSeedOrigin.MANUAL.value
    source_range: str | None = None
    source_row: int | None = None
    policy_version: str = "planning-v1"
    completeness_codes: list[str] = Field(default_factory=list)
    contributor_transaction_ids: list[int] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    notes: list[dict[str, Any]] = Field(default_factory=list)


class PlanningScenarioSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    name: str
    currency: str
    start_month: date
    end_month: date
    current_revision_number: int
    archived: bool = False
    clone_of_scenario_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def id(self) -> str:
        return self.scenario_id


class PlanningRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_id: str
    scenario_id: str
    revision_number: int
    items: list[PlanningItem] = Field(default_factory=list)
    notes: str = ""
    created_at: datetime | None = None
    provisional: bool = False
    issue_codes: list[str] = Field(default_factory=list)
    completeness_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    expense_notes: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def id(self) -> str:
        return self.revision_id

    @property
    def revision(self) -> int:
        return self.revision_number


class PlanningSeedPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_token: str
    origin: PlanningSeedOrigin
    scenario_name: str
    currency: str
    start_month: date
    end_month: date
    items: list[PlanningItemInput] = Field(default_factory=list)
    control_checks: dict[str, Any] = Field(default_factory=dict)
    ignored_sections: list[str] = Field(default_factory=list)
    mappings: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    issue_codes: list[str] = Field(default_factory=list)
    provisional: bool = False
    completeness_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    file_sha256: str | None = None
    filename: str | None = None
    duplicate_scenario_id: str | None = None
    expense_notes: list[dict[str, Any]] = Field(default_factory=list)
    expense_target_count: int = 0
    recurring_income_count: int = 0
    savings_summary_count: int = 0


class ForecastRole(StrEnum):
    """The three explicit, user-authored forecast cases."""

    CONSERVATIVE = "conservative"
    BASELINE = "baseline"
    OPTIMISTIC = "optimistic"


class ForecastPoolType(StrEnum):
    CASH = "cash"
    INVESTMENT = "investment"


class ForecastAdjustmentOperation(StrEnum):
    REPLACEMENT = "replacement"
    FIXED_DELTA = "fixed_delta"
    PERCENTAGE_CHANGE = "percentage_change"


class ForecastTargetType(StrEnum):
    LINE = "line"
    CATEGORY = "category"


class ForecastEventType(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    CONTRIBUTION = "contribution"
    WITHDRAWAL = "withdrawal"


class ForecastPoolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    pool_id: str | None = None
    pool_type: ForecastPoolType
    opening_balance: Decimal
    as_of_date: date

    @field_validator("name")
    @classmethod
    def require_pool_name(cls, value: str) -> str:
        value = str(value).strip()
        if not value or len(value) > 200:
            raise ValueError("Forecast pool name must be non-empty and at most 200 characters")
        return value

    @field_validator("opening_balance")
    @classmethod
    def require_opening_balance(cls, value: Decimal) -> Decimal:
        value = Decimal(value)
        if not value.is_finite() or value < 0:
            raise ValueError("Forecast opening balances must be finite and non-negative")
        return value


class ForecastRoutingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_item_id: str
    pool_name: str | None = None
    pool_id: str | None = None

    @model_validator(mode="after")
    def require_pool_reference(self) -> ForecastRoutingInput:
        if not (self.pool_name or self.pool_id):
            raise ValueError("A forecast route must reference one pool")
        if self.pool_name and self.pool_id:
            raise ValueError("A forecast route must use pool_name or pool_id, not both")
        return self


class ForecastAdjustmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: ForecastTargetType
    target: str
    operation: ForecastAdjustmentOperation
    value: Decimal
    start_month: int = Field(ge=1, le=36)
    end_month: int | None = Field(default=None, ge=1, le=36)

    @field_validator("target")
    @classmethod
    def require_target(cls, value: str) -> str:
        value = str(value).strip()
        if not value:
            raise ValueError("Forecast adjustment target must be non-empty")
        return value

    @field_validator("value")
    @classmethod
    def require_adjustment_value(cls, value: Decimal) -> Decimal:
        value = Decimal(value)
        if not value.is_finite():
            raise ValueError("Forecast adjustment value must be finite")
        return value

    @model_validator(mode="after")
    def validate_months(self) -> ForecastAdjustmentInput:
        if self.end_month is not None and self.end_month < self.start_month:
            raise ValueError("Forecast adjustment end_month cannot precede start_month")
        if self.operation == ForecastAdjustmentOperation.REPLACEMENT and self.value < 0:
            raise ValueError("Forecast replacement values must be non-negative")
        if self.operation == ForecastAdjustmentOperation.PERCENTAGE_CHANGE and self.value <= -1:
            raise ValueError("Forecast percentage changes must be greater than -100 percent")
        return self


class ForecastEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: ForecastEventType
    month: int = Field(ge=1, le=36)
    amount: Decimal
    label: str = "One-time event"
    pool_name: str | None = None
    pool_id: str | None = None

    @field_validator("amount")
    @classmethod
    def require_event_amount(cls, value: Decimal) -> Decimal:
        value = Decimal(value)
        if not value.is_finite() or value < 0:
            raise ValueError("Forecast event amounts must be finite and non-negative")
        return value

    @model_validator(mode="after")
    def validate_event_route(self) -> ForecastEventInput:
        if self.event_type in {ForecastEventType.CONTRIBUTION, ForecastEventType.WITHDRAWAL}:
            if not (self.pool_name or self.pool_id):
                raise ValueError("Forecast savings events must route to one pool")
            if self.pool_name and self.pool_id:
                raise ValueError("A forecast event must use pool_name or pool_id, not both")
        return self


class ForecastCaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ForecastRole
    annual_return_rate: Decimal
    routes: list[ForecastRoutingInput] = Field(default_factory=list)
    sweep_enabled: bool = False
    sweep_pool_name: str | None = None
    sweep_pool_id: str | None = None
    adjustments: list[ForecastAdjustmentInput] = Field(default_factory=list)
    events: list[ForecastEventInput] = Field(default_factory=list)
    confirmed: bool = False

    @field_validator("annual_return_rate")
    @classmethod
    def require_return_rate(cls, value: Decimal) -> Decimal:
        value = Decimal(value)
        if not value.is_finite() or value <= -1:
            raise ValueError("Forecast annual return rates must be finite and greater than -100 percent")
        return value

    @model_validator(mode="after")
    def validate_sweep(self) -> ForecastCaseInput:
        if self.sweep_pool_name and self.sweep_pool_id:
            raise ValueError("A sweep must use sweep_pool_name or sweep_pool_id, not both")
        if self.sweep_enabled and not (self.sweep_pool_name or self.sweep_pool_id):
            raise ValueError("An enabled sweep must select one pool")
        return self


class ForecastRevisionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    forecast_id: str | None = None
    revision_id: str | None = None
    revision_number: int = 1
    assumption_hash: str = ""
    created_at: datetime | None = None
    scenario_id: str
    source_revision_id: str
    source_revision_number: int
    currency: str
    horizon_months: int = 36
    policy_version: str = "savings-forecast-v1"
    provisional_acknowledged: bool = False
    starting_pools: list[ForecastPoolInput] = Field(default_factory=list)
    cases: list[ForecastCaseInput]
    notes: str = ""

    @model_validator(mode="after")
    def require_exact_cases(self) -> ForecastRevisionSnapshot:
        if self.horizon_months != 36:
            raise ValueError("Savings forecasts always use a 36-month horizon")
        roles = [case.role for case in self.cases]
        if set(roles) != set(ForecastRole) or len(roles) != 3:
            raise ValueError("A forecast revision must contain exactly conservative, baseline, and optimistic cases")
        if len({pool.name.casefold() for pool in self.starting_pools}) != len(self.starting_pools):
            raise ValueError("Forecast pool names must be unique")
        if not self.starting_pools:
            raise ValueError("A forecast requires at least one starting pool")
        return self


class ForecastMethodology(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_version: str
    source_plan_revision_id: str
    source_plan_revision_number: int
    calculation_order: list[str] = Field(default_factory=list)
    projection_disclaimer: str = (
        "Projected values are deterministic planning assumptions, not observed balances or guaranteed returns."
    )


class MonthlyPoolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month_number: int
    month: date
    pool_id: str
    pool_name: str
    pool_type: ForecastPoolType
    opening_balance: Decimal
    estimated_return: Decimal
    contributions: Decimal
    swept_surplus: Decimal = Decimal(0)
    requested_withdrawal: Decimal
    fulfilled_withdrawal: Decimal
    unmet_funding_gap: Decimal
    requested_capital_draw: Decimal = Decimal(0)
    fulfilled_capital_draw: Decimal = Decimal(0)
    closing_balance: Decimal


class TotalMonthlyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month_number: int
    month: date
    income: Decimal = Decimal(0)
    expenses: Decimal = Decimal(0)
    contributions: Decimal = Decimal(0)
    requested_withdrawals: Decimal = Decimal(0)
    fulfilled_withdrawals: Decimal = Decimal(0)
    unmet_funding_gap: Decimal = Decimal(0)
    swept_surplus: Decimal = Decimal(0)
    estimated_returns: Decimal = Decimal(0)
    cash_before_sweep: Decimal = Decimal(0)
    cash_after_sweep: Decimal = Decimal(0)
    ending_balance: Decimal = Decimal(0)
    requested_capital_draws: Decimal = Decimal(0)
    fulfilled_capital_draws: Decimal = Decimal(0)
    pools: list[MonthlyPoolResult] = Field(default_factory=list)

    @property
    def funding_gap(self) -> Decimal:
        return self.unmet_funding_gap


class ForecastOverlayExpense(BaseModel):
    """A typed post-event expense applied by the shared forecast engine."""

    model_config = ConfigDict(extra="forbid")

    label: str
    amount: Decimal

    @field_validator("label")
    @classmethod
    def require_overlay_expense_label(cls, value: str) -> str:
        value = str(value).strip()
        if not value:
            raise ValueError("Forecast overlay expense labels must be non-empty")
        return value

    @field_validator("amount")
    @classmethod
    def require_overlay_expense_amount(cls, value: Decimal) -> Decimal:
        value = Decimal(value)
        if not value.is_finite() or value < 0:
            raise ValueError("Forecast overlay expense amounts must be finite and non-negative")
        return value


class ForecastCapitalDraw(BaseModel):
    """A capital-only pool draw made after a selected forecast month closes."""

    model_config = ConfigDict(extra="forbid")

    pool_name: str = Field(validation_alias=AliasChoices("pool_name", "pool", "name"))
    amount: Decimal

    @field_validator("pool_name")
    @classmethod
    def require_capital_draw_pool(cls, value: str) -> str:
        value = str(value).strip()
        if not value:
            raise ValueError("Forecast capital draws must reference a pool")
        return value

    @field_validator("amount")
    @classmethod
    def require_capital_draw_amount(cls, value: Decimal) -> Decimal:
        value = Decimal(value)
        if not value.is_finite() or value < 0:
            raise ValueError("Forecast capital draw amounts must be finite and non-negative")
        return value


class ForecastOverlay(BaseModel):
    """Optional typed additions to :class:`ForecastEngine`'s monthly calculation.

    The overlay deliberately separates capital movements from household income
    and expenses.  It is used by apartment planning and is safe to omit for all
    existing Phase 5 forecasts.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    closing_month: int = Field(
        ge=1, le=36, validation_alias=AliasChoices("closing_month", "purchase_month")
    )
    stopped_source_item_ids: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("stopped_source_item_ids", "stopped_source_line_ids"),
    )
    post_move_expenses: list[ForecastOverlayExpense] = Field(default_factory=list)
    monthly_mortgage_payment: Decimal = Decimal(0)
    mortgage_payments: list[Decimal] = Field(default_factory=list)
    capital_draws: list[ForecastCapitalDraw] = Field(default_factory=list)

    @field_validator("monthly_mortgage_payment")
    @classmethod
    def require_overlay_payment(cls, value: Decimal) -> Decimal:
        value = Decimal(value)
        if not value.is_finite() or value < 0:
            raise ValueError("Forecast overlay mortgage payments must be finite and non-negative")
        return value

    @field_validator("mortgage_payments")
    @classmethod
    def require_overlay_payment_schedule(cls, value: list[Decimal]) -> list[Decimal]:
        normalized = []
        for payment in value:
            payment = Decimal(payment)
            if not payment.is_finite() or payment < 0:
                raise ValueError("Forecast overlay mortgage schedules must be finite and non-negative")
            normalized.append(payment)
        return normalized


class EquityRequirement(BaseModel):
    """The user-authored minimum equity rule for a purchase."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    mode: Literal["percentage", "amount"] = Field(
        default="percentage", validation_alias=AliasChoices("mode", "kind", "type")
    )
    value: Decimal

    @field_validator("value")
    @classmethod
    def require_equity_value(cls, value: Decimal) -> Decimal:
        value = Decimal(value)
        if not value.is_finite() or value < 0:
            raise ValueError("Equity requirements must be finite and non-negative")
        return value

    @model_validator(mode="after")
    def validate_equity_mode(self) -> EquityRequirement:
        if self.mode == "percentage" and self.value > 1:
            raise ValueError("Percentage equity requirements must be fractional values between 0 and 1")
        return self

    @property
    def kind(self) -> str:
        return self.mode

    def minimum_amount(self, purchase_price: Decimal) -> Decimal:
        return purchase_price * self.value if self.mode == "percentage" else self.value


class MortgageAssumption(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    principal: Decimal = Field(
        validation_alias=AliasChoices("principal", "mortgage_principal")
    )
    annual_nominal_rate: Decimal = Field(
        validation_alias=AliasChoices("annual_nominal_rate", "annual_rate", "rate")
    )
    term_months: int = Field(ge=12, le=480)

    @field_validator("principal", "annual_nominal_rate")
    @classmethod
    def validate_mortgage_numbers(cls, value: Decimal) -> Decimal:
        value = Decimal(value)
        if not value.is_finite() or value < 0:
            raise ValueError("Mortgage principal and rate must be finite and non-negative")
        return value

    @property
    def mortgage_principal(self) -> Decimal:
        return self.principal

    @property
    def annual_rate(self) -> Decimal:
        return self.annual_nominal_rate

    @property
    def rate(self) -> Decimal:
        return self.annual_nominal_rate


class PurchaseCostInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    label: str = Field(validation_alias=AliasChoices("label", "name"))
    amount: Decimal = Decimal(0)

    @field_validator("label")
    @classmethod
    def require_purchase_cost_label(cls, value: str) -> str:
        value = str(value).strip()
        if not value:
            raise ValueError("Purchase cost labels must be non-empty")
        return value

    @field_validator("amount")
    @classmethod
    def validate_purchase_cost_amount(cls, value: Decimal) -> Decimal:
        value = Decimal(value)
        if not value.is_finite() or value < 0:
            raise ValueError("Purchase costs must be finite and non-negative")
        return value


class PoolDrawInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    pool_name: str | None = Field(
        default=None, validation_alias=AliasChoices("pool_name", "pool", "name")
    )
    pool_id: str | None = None
    amount: Decimal

    @field_validator("pool_name", "pool_id")
    @classmethod
    def normalize_pool_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    @field_validator("amount")
    @classmethod
    def validate_pool_draw_amount(cls, value: Decimal) -> Decimal:
        value = Decimal(value)
        if not value.is_finite() or value < 0:
            raise ValueError("Pool draws must be finite and non-negative")
        return value

    @model_validator(mode="after")
    def require_pool_reference(self) -> PoolDrawInput:
        if not (self.pool_name or self.pool_id):
            raise ValueError("A pool draw must reference one forecast pool")
        if self.pool_name and self.pool_id:
            raise ValueError("A pool draw must use pool_name or pool_id, not both")
        return self


class HousingCostInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    label: str = Field(validation_alias=AliasChoices("label", "name"))
    amount: Decimal = Decimal(0)

    @field_validator("label")
    @classmethod
    def require_housing_cost_label(cls, value: str) -> str:
        value = str(value).strip()
        if not value:
            raise ValueError("Housing cost labels must be non-empty")
        return value

    @field_validator("amount")
    @classmethod
    def validate_housing_cost_amount(cls, value: Decimal) -> Decimal:
        value = Decimal(value)
        if not value.is_finite() or value < 0:
            raise ValueError("Housing costs must be finite and non-negative")
        return value


class ApartmentGuardrails(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    minimum_remaining_liquidity: Decimal | None = Field(
        default=None, validation_alias=AliasChoices("minimum_remaining_liquidity", "min_remaining_liquidity")
    )
    maximum_housing_cost_to_income_ratio: Decimal | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "maximum_housing_cost_to_income_ratio", "max_housing_cost_to_income_ratio", "maximum_housing_ratio"
        ),
    )

    @field_validator("minimum_remaining_liquidity", "maximum_housing_cost_to_income_ratio")
    @classmethod
    def validate_guardrail(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        value = Decimal(value)
        if not value.is_finite() or value < 0:
            raise ValueError("Apartment guardrails must be finite and non-negative")
        return value

    @property
    def maximum_housing_ratio(self) -> Decimal | None:
        return self.maximum_housing_cost_to_income_ratio


class PurchaseAlternativeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    forecast_role: ForecastRole = Field(
        validation_alias=AliasChoices("forecast_role", "role", "case")
    )
    purchase_month: int = Field(ge=1, le=36)
    property_price: Decimal = Field(
        validation_alias=AliasChoices("property_price", "purchase_price", "price")
    )
    family_gift: Decimal = Decimal(0)
    purchase_costs: list[PurchaseCostInput] = Field(
        default_factory=list,
        validation_alias=AliasChoices("purchase_costs", "purchase_cost_lines", "costs"),
    )
    equity_requirement: EquityRequirement = Field(
        default_factory=lambda: EquityRequirement(mode="amount", value=Decimal(0))
    )
    mortgage: MortgageAssumption = Field(
        default_factory=lambda: MortgageAssumption(principal=Decimal(0), annual_nominal_rate=Decimal(0), term_months=360)
    )
    pool_draws: list[PoolDrawInput] = Field(
        default_factory=list, validation_alias=AliasChoices("pool_draws", "pool_draw_inputs")
    )
    stopped_housing_line_ids: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "stopped_housing_line_ids", "stopped_housing_lines", "stopped_expense_line_ids"
        ),
    )
    housing_costs: list[HousingCostInput] = Field(
        default_factory=list,
        validation_alias=AliasChoices("housing_costs", "ownership_costs", "recurring_ownership_costs"),
    )
    confirmed: bool = False

    @model_validator(mode="before")
    @classmethod
    def expand_flat_assumptions(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "mortgage" not in data and any(
            key in data for key in ("mortgage_principal", "mortgage_rate", "annual_nominal_rate", "mortgage_term_months")
        ):
            data["mortgage"] = {
                "principal": data.pop("mortgage_principal", 0),
                "annual_nominal_rate": data.pop("mortgage_rate", data.pop("annual_nominal_rate", 0)),
                "term_months": data.pop("mortgage_term_months", 360),
            }
        if "equity_requirement" not in data and any(
            key in data for key in ("equity_mode", "equity_kind", "equity_value")
        ):
            data["equity_requirement"] = {
                "mode": data.pop("equity_mode", data.pop("equity_kind", "amount")),
                "value": data.pop("equity_value", 0),
            }
        return data

    @field_validator("name")
    @classmethod
    def require_alternative_name(cls, value: str) -> str:
        value = str(value).strip()
        if not value or len(value) > 200:
            raise ValueError("Apartment alternative names must be non-empty and at most 200 characters")
        return value

    @field_validator("property_price", "family_gift")
    @classmethod
    def validate_purchase_amount(cls, value: Decimal) -> Decimal:
        value = Decimal(value)
        if not value.is_finite() or value < 0:
            raise ValueError("Purchase price and family gift must be finite and non-negative")
        return value

    @model_validator(mode="after")
    def validate_alternative(self) -> PurchaseAlternativeInput:
        if len({item.label.casefold() for item in self.purchase_costs}) != len(self.purchase_costs):
            raise ValueError("Purchase cost labels must be unique within an alternative")
        if len({item.label.casefold() for item in self.housing_costs}) != len(self.housing_costs):
            raise ValueError("Housing cost labels must be unique within an alternative")
        if len({(item.pool_name or item.pool_id or "").casefold() for item in self.pool_draws}) != len(self.pool_draws):
            raise ValueError("Each forecast pool may have at most one apartment draw")
        return self

    @property
    def role(self) -> ForecastRole:
        return self.forecast_role

    @property
    def purchase_price(self) -> Decimal:
        return self.property_price

    @property
    def stopped_housing_lines(self) -> list[str]:
        return self.stopped_housing_line_ids


class ApartmentRevisionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_id: str | None = None
    revision_id: str | None = None
    revision_number: int = 1
    assumption_hash: str = ""
    created_at: datetime | None = None
    forecast_id: str
    forecast_revision_id: str
    forecast_revision_number: int
    forecast_assumption_hash: str
    currency: str
    policy_version: str = "apartment-planning-v1"
    source_quality_acknowledged: bool = False
    guardrails: ApartmentGuardrails = Field(default_factory=ApartmentGuardrails)
    alternatives: list[PurchaseAlternativeInput]
    notes: str = ""

    @model_validator(mode="after")
    def require_alternatives(self) -> ApartmentRevisionSnapshot:
        if not 2 <= len(self.alternatives) <= 4:
            raise ValueError("An apartment study requires between 2 and 4 alternatives")
        names = [item.name.casefold() for item in self.alternatives]
        if len(set(names)) != len(names):
            raise ValueError("Apartment alternative names must be unique")
        return self

    @property
    def source_revision_id(self) -> str:
        return self.forecast_revision_id

    @property
    def source_revision_number(self) -> int:
        return self.forecast_revision_number

    @property
    def source_assumption_hash(self) -> str:
        return self.forecast_assumption_hash


class ApartmentStudySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_id: str
    name: str
    forecast_id: str
    forecast_revision_id: str
    forecast_revision_number: int
    forecast_assumption_hash: str
    currency: str
    current_revision_number: int
    archived: bool = False
    clone_of_study_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def id(self) -> str:
        return self.study_id

    @property
    def source_revision_id(self) -> str:
        return self.forecast_revision_id

    @property
    def source_revision_number(self) -> int:
        return self.forecast_revision_number

    @property
    def source_assumption_hash(self) -> str:
        return self.forecast_assumption_hash


class MortgageScheduleRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: int = Field(ge=1, le=480)
    payment_month: int | None = Field(default=None, ge=1, le=480)
    payment: Decimal
    interest: Decimal
    principal: Decimal
    remaining_principal: Decimal


class PurchaseReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equity_requirement_met: bool
    sources_cover_uses: bool
    mortgage_within_required_equity: bool
    minimum_liquidity_met: bool = True
    housing_ratio_guardrail_met: bool = True
    ready: bool
    failures: list[str] = Field(default_factory=list)


class ApartmentMonthlyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month_number: int = Field(ge=1, le=36)
    month: date
    income: Decimal
    expenses: Decimal
    housing_cost: Decimal = Decimal(0)
    removed_housing_costs: Decimal = Decimal(0)
    net_cash_flow_change: Decimal = Decimal(0)
    cash_after_sweep: Decimal
    ending_balance: Decimal
    pools: dict[str, Decimal] = Field(default_factory=dict)


class PurchaseProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alternative_name: str
    forecast_role: ForecastRole
    purchase_month: int
    purchase_price: Decimal
    purchase_costs: Decimal
    total_uses: Decimal
    proposed_equity: Decimal
    required_equity: Decimal
    mortgage_principal: Decimal
    family_gift: Decimal
    requested_pool_draws: Decimal
    fulfilled_pool_draws: Decimal
    total_sources: Decimal
    funding_gap: Decimal
    available_pool_balances: dict[str, Decimal] = Field(default_factory=dict)
    remaining_liquidity_by_pool: dict[str, Decimal] = Field(default_factory=dict)
    remaining_liquidity: Decimal
    mortgage_schedule: list[MortgageScheduleRow] = Field(default_factory=list)
    total_interest: Decimal
    total_repayment: Decimal
    monthly: list[ApartmentMonthlyResult] = Field(default_factory=list)
    readiness: PurchaseReadiness
    maximum_housing_ratio: Decimal | None = None
    worst_monthly_cash_flow: Decimal
    month_36_balance: Decimal
    source_projection: ForecastProjection

    @property
    def closing_gap(self) -> Decimal:
        return self.funding_gap

    @property
    def month_36_ending_balance(self) -> Decimal:
        return self.month_36_balance

    @property
    def months(self) -> list[ApartmentMonthlyResult]:
        return self.monthly


class ApartmentComparisonRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alternative_name: str
    purchase_month: int
    purchase_price: Decimal
    forecast_role: ForecastRole
    mortgage_payment: Decimal
    total_interest: Decimal
    closing_gap: Decimal
    remaining_liquidity: Decimal
    maximum_housing_ratio: Decimal | None
    worst_monthly_cash_flow: Decimal
    month_36_balance: Decimal


class ApartmentComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str
    alternatives: list[ApartmentComparisonRow] = Field(default_factory=list)

    @property
    def rows(self) -> list[ApartmentComparisonRow]:
        return self.alternatives

    @property
    def results(self) -> list[ApartmentComparisonRow]:
        return self.alternatives


class ApartmentDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projections: list[PurchaseProjection] = Field(default_factory=list)
    comparison: ApartmentComparison | None = None
    assumption_hash: str = ""
    source_quality_warning: bool = False


class ApartmentRevisionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_id: str
    study_id: str
    revision_number: int
    forecast_id: str
    forecast_revision_id: str
    forecast_revision_number: int
    forecast_assumption_hash: str
    policy_version: str
    assumption_hash: str
    created_at: datetime | None = None
    notes: str = ""


class ForecastProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    forecast_id: str | None = None
    scenario_id: str
    source_revision_id: str
    source_revision_number: int
    currency: str
    months: list[TotalMonthlyResult] = Field(default_factory=list)
    provisional: bool = False
    issue_codes: list[str] = Field(default_factory=list)
    first_shortfall_month: int | None = None
    assumption_hash: str = ""
    methodology: ForecastMethodology | None = None

    @property
    def results(self) -> list[TotalMonthlyResult]:
        return self.months


class ForecastComparisonCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    horizon_month: int
    ending_balance: Decimal
    contributions: Decimal
    swept_surplus: Decimal
    withdrawals: Decimal
    estimated_returns: Decimal
    funding_gap: Decimal


class ForecastComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str
    checkpoints: dict[ForecastRole, list[ForecastComparisonCheckpoint]] = Field(default_factory=dict)


class ForecastDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projections: dict[ForecastRole, ForecastProjection] = Field(default_factory=dict)
    comparison: ForecastComparison | None = None
    assumption_hash: str = ""
    validation_errors: list[str] = Field(default_factory=list)

    def __getitem__(self, role: ForecastRole | str) -> ForecastProjection:
        return self.projections[ForecastRole(role)]

    def get(self, role: ForecastRole | str, default=None):
        return self.projections.get(ForecastRole(role), default)


class ForecastRevisionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_id: str
    forecast_id: str
    revision_number: int
    source_revision_id: str
    source_revision_number: int
    policy_version: str
    assumption_hash: str
    created_at: datetime | None = None
    notes: str = ""


class ForecastSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    forecast_id: str
    name: str
    scenario_id: str
    source_revision_id: str
    source_revision_number: int
    currency: str
    horizon_months: int = 36
    current_revision_number: int
    archived: bool = False
    clone_of_forecast_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def id(self) -> str:
        return self.forecast_id


# Short domain-style aliases are useful to callers that do not need to
# distinguish persisted inputs from the snapshot contracts.
ForecastPool = ForecastPoolInput
ForecastCase = ForecastCaseInput
ForecastRouting = ForecastRoutingInput
ForecastAdjustment = ForecastAdjustmentInput
ForecastEvent = ForecastEventInput
ForecastRevision = ForecastRevisionSnapshot
ForecastMonthlyResult = TotalMonthlyResult


class MonthlyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: date
    currency: str
    income: Decimal = Decimal(0)
    expenses: Decimal = Decimal(0)
    savings_contributions: Decimal = Decimal(0)
    savings_withdrawals: Decimal = Decimal(0)
    operating_surplus: Decimal = Decimal(0)
    net_planned_savings: Decimal = Decimal(0)
    cash_remaining_after_savings: Decimal = Decimal(0)
    expenses_by_category: dict[str, Decimal] = Field(default_factory=dict)
    income_by_category: dict[str, Decimal] = Field(default_factory=dict)
    contributor_item_ids: dict[str, list[str]] = Field(default_factory=dict)
    unmapped_expense_categories: list[str] = Field(default_factory=list)

    @property
    def operating_surplus_or_deficit(self) -> Decimal:
        return self.operating_surplus


class PlanningProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    revision_number: int
    currency: str
    months: list[MonthlyPlan] = Field(default_factory=list)
    provisional: bool = False
    issue_codes: list[str] = Field(default_factory=list)

    @property
    def monthly_plans(self) -> list[MonthlyPlan]:
        return self.months


class ScenarioComparisonSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    name: str
    months: list[MonthlyPlan | None] = Field(default_factory=list)


class ScenarioComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str
    months: list[date] = Field(default_factory=list)
    scenarios: list[ScenarioComparisonSeries] = Field(default_factory=list)

    @property
    def results(self) -> list[ScenarioComparisonSeries]:
        return self.scenarios


class ActualPlanMonth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: date
    complete: bool
    issue_codes: list[str] = Field(default_factory=list)
    planned: MonthlyPlan
    actual_income: Decimal | None = None
    actual_expenses: Decimal | None = None
    actual_surplus: Decimal | None = None
    actual_net_savings: Decimal | None = None
    expense_variances: dict[str, Decimal] | None = None
    category_variance_unavailable: list[str] = Field(default_factory=list)
    income_variance: Decimal | None = None
    surplus_variance: Decimal | None = None
    savings_variance: Decimal | None = None
    transaction_ids_by_category: dict[str, list[int]] = Field(default_factory=dict)

    @property
    def formal_variance_available(self) -> bool:
        return self.complete


class ActualPlanComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    revision_number: int
    currency: str
    months: list[ActualPlanMonth] = Field(default_factory=list)

    @property
    def results(self) -> list[ActualPlanMonth]:
        return self.months


# Insight result types are declared after the dashboard container for readability.
ExpenseDashboard.model_rebuild()


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


# ``PurchaseProjection`` refers to ``ForecastProjection``, declared below the
# overlay contracts in the source file.  Resolve that forward reference once
# all model declarations are available.
PurchaseProjection.model_rebuild()


__all__ = [
    "AccountDescriptor",
    "ActualPlanComparison",
    "ActualPlanMonth",
    "ApartmentComparison",
    "ApartmentComparisonRow",
    "ApartmentDraft",
    "ApartmentGuardrails",
    "ApartmentMonthlyResult",
    "ApartmentRevisionSnapshot",
    "ApartmentRevisionSummary",
    "ApartmentStudySummary",
    "AuditCheck",
    "AuditReport",
    "BackupManifest",
    "BackupVerification",
    "CategorySummary",
    "ClassificationOverride",
    "ClassificationResult",
    "ClassificationReviewItem",
    "ClassificationRule",
    "ClassificationSource",
    "CompletenessAssessment",
    "DashboardComparison",
    "DashboardFilters",
    "DataQualityDashboard",
    "DataQualityIssue",
    "EconomicClass",
    "EquityRequirement",
    "ExpenseBehavior",
    "ExpenseDashboard",
    "ForecastAdjustment",
    "ForecastAdjustmentInput",
    "ForecastAdjustmentOperation",
    "ForecastCapitalDraw",
    "ForecastCase",
    "ForecastCaseInput",
    "ForecastComparison",
    "ForecastComparisonCheckpoint",
    "ForecastDraft",
    "ForecastEvent",
    "ForecastEventInput",
    "ForecastEventType",
    "ForecastMethodology",
    "ForecastMonthlyResult",
    "ForecastOverlay",
    "ForecastOverlayExpense",
    "ForecastPool",
    "ForecastPoolInput",
    "ForecastPoolType",
    "ForecastProjection",
    "ForecastRevision",
    "ForecastRevisionSnapshot",
    "ForecastRevisionSummary",
    "ForecastRole",
    "ForecastRouting",
    "ForecastRoutingInput",
    "ForecastSummary",
    "ForecastTargetType",
    "HousingCostInput",
    "ImportInspection",
    "ImportPreview",
    "ImportResult",
    "ImportStatistics",
    "ImportStatus",
    "MatchMethod",
    "MetricBreakdown",
    "MonthlyMetrics",
    "MonthlyPlan",
    "MonthlyPoolResult",
    "MonthlySeriesPoint",
    "MortgageAssumption",
    "MortgageScheduleRow",
    "NormalizedTransactionCandidate",
    "OverviewDashboard",
    "ParsedSourceRecord",
    "PlanningFrequency",
    "PlanningItem",
    "PlanningItemInput",
    "PlanningItemKind",
    "PlanningProjection",
    "PlanningRevision",
    "PlanningScenarioSummary",
    "PlanningSeedOrigin",
    "PlanningSeedPreview",
    "PoolDrawInput",
    "PotentialRecurringSpending",
    "PurchaseAlternativeInput",
    "PurchaseCostInput",
    "PurchaseProjection",
    "PurchaseReadiness",
    "ReconciliationDecision",
    "ScenarioComparison",
    "ScenarioComparisonSeries",
    "TotalMonthlyResult",
    "TransactionContribution",
    "UnusualCategorySpending",
]
