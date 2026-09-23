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
    net_worth_snapshot_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("net_worth_snapshot_revisions.id"), nullable=True
    )
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
    net_worth_account_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    net_worth_snapshot_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("net_worth_snapshot_revisions.id"), nullable=True
    )
    source_valuation_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_quality_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)

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


class ApartmentStudyRow(Base):
    __tablename__ = "apartment_studies"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    forecast_id: Mapped[str] = mapped_column(ForeignKey("savings_forecasts.id"))
    forecast_revision_id: Mapped[str] = mapped_column(
        ForeignKey("savings_forecast_revisions.id")
    )
    forecast_revision_number: Mapped[int] = mapped_column(Integer)
    forecast_assumption_hash: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text)
    current_revision_number: Mapped[int] = mapped_column(Integer, default=1)
    clone_of_study_id: Mapped[str | None] = mapped_column(
        ForeignKey("apartment_studies.id"), nullable=True
    )
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text)


class ApartmentRevisionRow(Base):
    __tablename__ = "apartment_study_revisions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    study_id: Mapped[str] = mapped_column(
        ForeignKey("apartment_studies.id", ondelete="CASCADE")
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    forecast_id: Mapped[str] = mapped_column(ForeignKey("savings_forecasts.id"))
    forecast_revision_id: Mapped[str] = mapped_column(
        ForeignKey("savings_forecast_revisions.id")
    )
    forecast_revision_number: Mapped[int] = mapped_column(Integer)
    forecast_assumption_hash: Mapped[str] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(Text)
    assumption_hash: Mapped[str] = mapped_column(Text)
    assumptions_json: Mapped[str] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text, default="")
    source_quality_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        Index("idx_apartment_revisions_unique", "study_id", "revision_number", unique=True),
    )


class ApartmentAlternativeRow(Base):
    __tablename__ = "apartment_alternatives"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("apartment_study_revisions.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text)
    forecast_role: Mapped[str] = mapped_column(Text)
    purchase_month: Mapped[int] = mapped_column(Integer)
    property_price: Mapped[str] = mapped_column(Text)
    family_gift: Mapped[str] = mapped_column(Text)
    equity_mode: Mapped[str] = mapped_column(Text)
    equity_value: Mapped[str] = mapped_column(Text)
    mortgage_principal: Mapped[str] = mapped_column(Text)
    mortgage_annual_nominal_rate: Mapped[str] = mapped_column(Text)
    mortgage_term_months: Mapped[int] = mapped_column(Integer)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class ApartmentPurchaseCostRow(Base):
    __tablename__ = "apartment_purchase_costs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    alternative_id: Mapped[str] = mapped_column(
        ForeignKey("apartment_alternatives.id", ondelete="CASCADE")
    )
    label: Mapped[str] = mapped_column(Text)
    amount: Mapped[str] = mapped_column(Text)


class ApartmentPoolDrawRow(Base):
    __tablename__ = "apartment_pool_draws"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    alternative_id: Mapped[str] = mapped_column(
        ForeignKey("apartment_alternatives.id", ondelete="CASCADE")
    )
    pool_name: Mapped[str] = mapped_column(Text)
    amount: Mapped[str] = mapped_column(Text)


class ApartmentStoppedHousingLineRow(Base):
    __tablename__ = "apartment_stopped_housing_lines"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    alternative_id: Mapped[str] = mapped_column(
        ForeignKey("apartment_alternatives.id", ondelete="CASCADE")
    )
    source_item_id: Mapped[str] = mapped_column(ForeignKey("planning_items.id"))


class ApartmentHousingCostRow(Base):
    __tablename__ = "apartment_housing_costs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    alternative_id: Mapped[str] = mapped_column(
        ForeignKey("apartment_alternatives.id", ondelete="CASCADE")
    )
    label: Mapped[str] = mapped_column(Text)
    amount: Mapped[str] = mapped_column(Text)


class NetWorthAccountRow(Base):
    __tablename__ = "net_worth_accounts"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_key: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    side: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    liquidity: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_from: Mapped[str] = mapped_column(Text)
    active_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    stale_after_days: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text)


class NetWorthSnapshotRow(Base):
    __tablename__ = "net_worth_snapshots"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    snapshot_date: Mapped[str] = mapped_column(Text, unique=True)
    current_revision_number: Mapped[int] = mapped_column(Integer, default=1)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text)


class NetWorthSnapshotRevisionRow(Base):
    __tablename__ = "net_worth_snapshot_revisions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("net_worth_snapshots.id", ondelete="CASCADE")
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    snapshot_date: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text, default="")
    quality_issues_json: Mapped[str] = mapped_column(Text, default="[]")
    quality_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str] = mapped_column(Text)
    active_account_keys_json: Mapped[str] = mapped_column(Text, default="[]")
    source_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("net_worth_source_files.id"), nullable=True
    )
    created_at: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        Index("idx_net_worth_snapshot_revisions_unique", "snapshot_id", "revision_number", unique=True),
        Index("idx_net_worth_snapshot_revisions_date", "snapshot_date", "revision_number"),
    )


class NetWorthBalanceRow(Base):
    __tablename__ = "net_worth_balances"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("net_worth_snapshot_revisions.id", ondelete="CASCADE")
    )
    account_key: Mapped[str] = mapped_column(
        ForeignKey("net_worth_accounts.account_key")
    )
    account_name: Mapped[str] = mapped_column(Text)
    side: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    liquidity: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    stale_after_days: Mapped[int] = mapped_column(Integer)
    snapshot_date: Mapped[str] = mapped_column(Text)
    amount_ils: Mapped[str] = mapped_column(Text)
    valuation_date: Mapped[str] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (
        Index("idx_net_worth_balances_revision_account", "revision_id", "account_key", unique=True),
        Index("idx_net_worth_balances_account_date", "account_key", "valuation_date"),
    )


class NetWorthSourceFileRow(Base):
    __tablename__ = "net_worth_source_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sha256: Mapped[str] = mapped_column(Text, unique=True)
    original_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_path: Mapped[str] = mapped_column(Text)
    compressed_bytes: Mapped[int] = mapped_column(Integer)
    uncompressed_bytes: Mapped[int] = mapped_column(Integer)
    parser_version: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text)


class NetWorthImportRow(Base):
    __tablename__ = "net_worth_imports"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("net_worth_source_files.id"))
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("net_worth_snapshots.id"))
    revision_id: Mapped[str] = mapped_column(ForeignKey("net_worth_snapshot_revisions.id"))
    origin: Mapped[str] = mapped_column(Text)
    imported_at: Mapped[str] = mapped_column(Text)


class AutomationPreferencesRow(Base):
    __tablename__ = "automation_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    planning_scenario_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    planning_revision_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    forecast_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    forecast_revision_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    forecast_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    apartment_study_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    apartment_revision_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    apartment_alternative_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str] = mapped_column(Text)


class AutomationRunRow(Base):
    __tablename__ = "automation_runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    started_at: Mapped[str] = mapped_column(Text)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    audit_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    backup_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    counts_json: Mapped[str] = mapped_column(Text, default="{}")
    issue_codes_json: Mapped[str] = mapped_column(Text, default="[]")


class AutomationFileOutcomeRow(Base):
    __tablename__ = "automation_file_outcomes"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("automation_runs.id", ondelete="CASCADE"))
    source_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    import_batch_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    managed_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(Text)


class InsightAlertRow(Base):
    __tablename__ = "insight_alerts"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(Text, unique=True)
    algorithm_version: Mapped[str] = mapped_column(Text)
    condition_type: Mapped[str] = mapped_column(Text)
    subject_identity: Mapped[str] = mapped_column(Text)
    currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_period: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    first_seen: Mapped[str] = mapped_column(Text)
    last_seen: Mapped[str] = mapped_column(Text)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    acknowledged_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_resolution_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)


class InsightAlertEventRow(Base):
    __tablename__ = "insight_alert_events"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("insight_alerts.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(Text)
    from_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_state: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text)


class MonthlySummaryIdentityRow(Base):
    __tablename__ = "monthly_summary_identities"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    month: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text)


class MonthlySummaryRevisionRow(Base):
    __tablename__ = "monthly_summary_revisions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    identity_id: Mapped[str] = mapped_column(ForeignKey("monthly_summary_identities.id", ondelete="CASCADE"))
    revision_number: Mapped[int] = mapped_column(Integer)
    month: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text)
    input_fingerprint: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text)
    content_json: Mapped[str] = mapped_column(Text)
    markdown: Mapped[str] = mapped_column(Text)
    contributor_provenance_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text)


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
    "ApartmentAlternativeRow",
    "ApartmentHousingCostRow",
    "ApartmentPoolDrawRow",
    "ApartmentPurchaseCostRow",
    "ApartmentRevisionRow",
    "ApartmentStoppedHousingLineRow",
    "ApartmentStudyRow",
    "AutomationFileOutcomeRow",
    "AutomationPreferencesRow",
    "AutomationRunRow",
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
    "InsightAlertEventRow",
    "InsightAlertRow",
    "MonthlySummaryIdentityRow",
    "MonthlySummaryRevisionRow",
    "NetWorthAccountRow",
    "NetWorthBalanceRow",
    "NetWorthImportRow",
    "NetWorthSnapshotRevisionRow",
    "NetWorthSnapshotRow",
    "NetWorthSourceFileRow",
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
