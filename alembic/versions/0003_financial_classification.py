"""Append-only financial classification persistence."""

from alembic import op

revision = "0003_financial_classification"
down_revision = "0002_source_link_invariants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS classification_rules (
            id INTEGER PRIMARY KEY,
            account_kind TEXT NOT NULL,
            direction TEXT NOT NULL,
            source_category TEXT NOT NULL,
            source_movement_type TEXT NOT NULL DEFAULT '',
            currency TEXT NOT NULL,
            economic_class TEXT NOT NULL,
            analysis_category TEXT,
            expense_behavior TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            is_tombstone INTEGER NOT NULL DEFAULT 0,
            revision INTEGER NOT NULL,
            supersedes_rule_id INTEGER REFERENCES classification_rules(id),
            reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_classification_rules_lookup
        ON classification_rules(
            account_kind, direction, source_category, source_movement_type, currency,
            revision, id
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_classification_rules_key_latest
        ON classification_rules(
            account_kind, direction, source_category, source_movement_type, currency, id
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_analysis_overrides_latest
        ON analysis_overrides(transaction_id, field_name, id)
        """
    )


def downgrade() -> None:
    op.drop_index("idx_analysis_overrides_latest", table_name="analysis_overrides")
    op.drop_index("idx_classification_rules_key_latest", table_name="classification_rules")
    op.drop_index("idx_classification_rules_lookup", table_name="classification_rules")
    op.drop_table("classification_rules")
