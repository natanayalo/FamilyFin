"""SQLAlchemy 2.0 mappings for the local financial store.

The first two migrations remain SQL snapshots for compatibility.  These
mappings are the runtime model for new persistence code and deliberately keep
money as text, matching the existing schema's canonical Decimal representation.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AccountRow(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_kind: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    source_reference_fingerprint: Mapped[str] = mapped_column(Text, unique=True)
    display_label: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text)


class CategoryRow(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    movement_type: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(Text)

    __table_args__ = (Index("idx_categories_unique", "movement_type", "category", unique=True),)


class TransactionRow(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    booking_date: Mapped[str] = mapped_column(Text)
    allocation_date: Mapped[str] = mapped_column(Text)
    amount: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text)
    original_currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_amount: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text)
    movement_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text, default="accepted")
    created_at: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text)


class SourceRecordRow(Base):
    __tablename__ = "source_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    sheet_name: Mapped[str] = mapped_column(Text)
    section_index: Mapped[int] = mapped_column(Integer)
    source_row_number: Mapped[int] = mapped_column(Integer)
    raw_payload_json: Mapped[str] = mapped_column(Text)
    normalized_json: Mapped[str] = mapped_column(Text)
    row_fingerprint: Mapped[str] = mapped_column(Text)
    validation_state: Mapped[str] = mapped_column(Text)
    issues_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text)


class TransactionSourceRow(Base):
    __tablename__ = "transaction_sources"

    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id"), primary_key=True
    )
    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("source_records.id"), primary_key=True
    )
    match_method: Mapped[str] = mapped_column(Text)
    linked_at: Mapped[str] = mapped_column(Text)


class ReconciliationCaseRow(Base):
    __tablename__ = "reconciliation_cases"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    import_batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"))
    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_records.id"))
    status: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    candidate_transaction_ids_json: Mapped[str] = mapped_column(Text)
    resolution_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text)
    resolved_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class ImportBatchRow(Base):
    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_files.id"), nullable=True
    )
    parser_version: Mapped[str] = mapped_column(Text)
    baseline_batch_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_start: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_end: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_transaction_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    freshness_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(Text)
    statistics_json: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text)


class SourceFileRow(Base):
    __tablename__ = "source_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sha256: Mapped[str] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_path: Mapped[str] = mapped_column(Text)
    compressed_bytes: Mapped[int] = mapped_column(Integer)
    uncompressed_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(Text)


class ClassificationRuleRow(Base):
    __tablename__ = "classification_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_kind: Mapped[str] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(Text)
    source_category: Mapped[str] = mapped_column(Text)
    source_movement_type: Mapped[str] = mapped_column(Text, default="")
    currency: Mapped[str] = mapped_column(Text)
    economic_class: Mapped[str] = mapped_column(Text)
    analysis_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    expense_behavior: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_tombstone: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer)
    supersedes_rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("classification_rules.id"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        Index(
            "idx_classification_rules_lookup",
            "account_kind",
            "direction",
            "source_category",
            "source_movement_type",
            "currency",
            "revision",
            "id",
        ),
    )


class AnalysisOverrideRow(Base):
    __tablename__ = "analysis_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    field_name: Mapped[str] = mapped_column(Text)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        Index("idx_analysis_overrides_latest", "transaction_id", "field_name", "id"),
    )


class PlanningScenarioRow(Base):
    __tablename__ = "planning_scenarios"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text)
    start_month: Mapped[str] = mapped_column(Text)
    end_month: Mapped[str] = mapped_column(Text)
    current_revision_number: Mapped[int] = mapped_column(Integer, default=1)
    clone_of_scenario_id: Mapped[str | None] = mapped_column(
        ForeignKey("planning_scenarios.id"), nullable=True
    )
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text)


class PlanningScenarioRevisionRow(Base):
    __tablename__ = "planning_scenario_revisions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    scenario_id: Mapped[str] = mapped_column(
        ForeignKey("planning_scenarios.id", ondelete="CASCADE")
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str] = mapped_column(Text, default="")
    provisional: Mapped[bool] = mapped_column(Boolean, default=False)
    issue_codes_json: Mapped[str] = mapped_column(Text, default="[]")
    completeness_snapshot_json: Mapped[str] = mapped_column(Text, default="[]")
    expense_notes_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        Index("idx_planning_revisions_unique", "scenario_id", "revision_number", unique=True),
        Index("idx_planning_revisions_scenario", "scenario_id", "revision_number"),
    )


class PlanningItemRow(Base):
    __tablename__ = "planning_items"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("planning_scenario_revisions.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str] = mapped_column(Text)
    amount: Mapped[str] = mapped_column(Text)
    frequency: Mapped[str] = mapped_column(Text)
    start_month: Mapped[str | None] = mapped_column(Text, nullable=True)
    end_month: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurrence_month: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[str] = mapped_column(Text, default="manual")
    source_range: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    policy_version: Mapped[str] = mapped_column(Text, default="planning-v1")
    completeness_codes_json: Mapped[str] = mapped_column(Text, default="[]")
    contributor_transaction_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    provenance_json: Mapped[str] = mapped_column(Text, default="{}")
    notes_json: Mapped[str] = mapped_column(Text, default="[]")

    __table_args__ = (Index("idx_planning_items_revision", "revision_id"),)


class PlanningSourceFileRow(Base):
    __tablename__ = "planning_source_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sha256: Mapped[str] = mapped_column(Text, unique=True)
    original_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_path: Mapped[str] = mapped_column(Text)
    compressed_bytes: Mapped[int] = mapped_column(Integer)
    uncompressed_bytes: Mapped[int] = mapped_column(Integer)
    parser_version: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text)


class PlanningSeedImportRow(Base):
    __tablename__ = "planning_seed_imports"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("planning_source_files.id"))
    scenario_id: Mapped[str] = mapped_column(ForeignKey("planning_scenarios.id"))
    revision_id: Mapped[str] = mapped_column(ForeignKey("planning_scenario_revisions.id"))
    origin: Mapped[str] = mapped_column(Text)
    parser_version: Mapped[str] = mapped_column(Text)
    imported_at: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        Index("idx_planning_seed_source_scenario", "source_file_id", "scenario_id", unique=True),
    )


class ForecastRow(Base):
    """Stable identity for a saved savings forecast."""

    __tablename__ = "savings_forecasts"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("planning_scenarios.id"))
    source_revision_id: Mapped[str] = mapped_column(ForeignKey("planning_scenario_revisions.id"))
    source_revision_number: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(Text)
    horizon_months: Mapped[int] = mapped_column(Integer, default=36)
    current_revision_number: Mapped[int] = mapped_column(Integer, default=1)
    clone_of_forecast_id: Mapped[str | None] = mapped_column(
        ForeignKey("savings_forecasts.id"), nullable=True
    )
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text)


class ForecastRevisionRow(Base):
    __tablename__ = "savings_forecast_revisions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    forecast_id: Mapped[str] = mapped_column(
        ForeignKey("savings_forecasts.id", ondelete="CASCADE")
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    source_revision_id: Mapped[str] = mapped_column(ForeignKey("planning_scenario_revisions.id"))
    source_revision_number: Mapped[int] = mapped_column(Integer)
    policy_version: Mapped[str] = mapped_column(Text)
    assumption_hash: Mapped[str] = mapped_column(Text)
    assumptions_json: Mapped[str] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        Index("idx_savings_forecast_revisions_unique", "forecast_id", "revision_number", unique=True),
        Index("idx_savings_forecast_revisions_forecast", "forecast_id", "revision_number"),
    )


class ForecastCaseRow(Base):
    __tablename__ = "savings_forecast_cases"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("savings_forecast_revisions.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(Text)
    annual_return_rate: Mapped[str] = mapped_column(Text)
    sweep_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Deliberately not a SQL FK: pools point back to cases, so making this
    # optional reference an FK would introduce a migration-time cycle.
    # Forecast validation and the integrity audit enforce membership.
    sweep_pool_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("idx_savings_forecast_cases_unique", "revision_id", "role", unique=True),
    )


class ForecastPoolRow(Base):
    __tablename__ = "savings_forecast_pools"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("savings_forecast_cases.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text)
    pool_type: Mapped[str] = mapped_column(Text)
    opening_balance: Mapped[str] = mapped_column(Text)
    as_of_date: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        Index("idx_savings_forecast_pools_unique", "case_id", "name", unique=True),
    )


class ForecastRoutingRow(Base):
    __tablename__ = "savings_forecast_routings"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("savings_forecast_cases.id", ondelete="CASCADE")
    )
    source_item_id: Mapped[str] = mapped_column(ForeignKey("planning_items.id"))
    pool_id: Mapped[str] = mapped_column(
        ForeignKey("savings_forecast_pools.id", ondelete="CASCADE")
    )

    __table_args__ = (
        Index("idx_savings_forecast_routing_unique", "case_id", "source_item_id", unique=True),
    )


class ForecastAdjustmentRow(Base):
    __tablename__ = "savings_forecast_adjustments"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("savings_forecast_cases.id", ondelete="CASCADE")
    )
    target_type: Mapped[str] = mapped_column(Text)
    target: Mapped[str] = mapped_column(Text)
    operation: Mapped[str] = mapped_column(Text)
    value: Mapped[str] = mapped_column(Text)
    start_month: Mapped[int] = mapped_column(Integer)
    end_month: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ForecastEventRow(Base):
    __tablename__ = "savings_forecast_events"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("savings_forecast_cases.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(Text)
    month: Mapped[int] = mapped_column(Integer)
    amount: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text)
    pool_id: Mapped[str | None] = mapped_column(
        ForeignKey("savings_forecast_pools.id", ondelete="CASCADE"), nullable=True
    )


# Readable aliases for repository consumers that prefer domain-style names.
Account = AccountRow
Transaction = TransactionRow
ClassificationRule = ClassificationRuleRow
AnalysisOverride = AnalysisOverrideRow
AccountModel = AccountRow
TransactionModel = TransactionRow
ClassificationRuleModel = ClassificationRuleRow
AnalysisOverrideModel = AnalysisOverrideRow


__all__ = [
    "Account",
    "AccountModel",
    "AccountRow",
    "AnalysisOverride",
    "AnalysisOverrideModel",
    "AnalysisOverrideRow",
    "Base",
    "CategoryRow",
    "ClassificationRule",
    "ClassificationRuleModel",
    "ClassificationRuleRow",
    "ForecastAdjustmentRow",
    "ForecastCaseRow",
    "ForecastEventRow",
    "ForecastPoolRow",
    "ForecastRevisionRow",
    "ForecastRoutingRow",
    "ForecastRow",
    "ImportBatchRow",
    "PlanningItemRow",
    "PlanningScenarioRevisionRow",
    "PlanningScenarioRow",
    "PlanningSeedImportRow",
    "PlanningSourceFileRow",
    "ReconciliationCaseRow",
    "SourceFileRow",
    "SourceRecordRow",
    "Transaction",
    "TransactionModel",
    "TransactionRow",
    "TransactionSourceRow",
]
