"""Enforce one transaction link and one reconciliation case per source row."""

from alembic import op

revision = "0002_source_link_invariants"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_transaction_sources_source_record",
        "transaction_sources",
        ["source_record_id"],
        unique=True,
    )
    op.create_index(
        "uq_reconciliation_cases_source_record",
        "reconciliation_cases",
        ["source_record_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_reconciliation_cases_source_record",
        table_name="reconciliation_cases",
    )
    op.drop_index(
        "uq_transaction_sources_source_record",
        table_name="transaction_sources",
    )
