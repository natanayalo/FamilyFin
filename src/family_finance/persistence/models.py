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
    "ImportBatchRow",
    "ReconciliationCaseRow",
    "SourceFileRow",
    "SourceRecordRow",
    "Transaction",
    "TransactionModel",
    "TransactionRow",
    "TransactionSourceRow",
]
