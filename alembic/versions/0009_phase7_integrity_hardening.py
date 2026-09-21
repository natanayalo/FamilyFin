"""Preserve the account set captured by each immutable net-worth revision."""

from alembic import op

revision = "0009_phase7_integrity_hardening"
down_revision = "0008_household_net_worth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {
        row[1]
        for row in bind.exec_driver_sql(
            "PRAGMA table_info(net_worth_snapshot_revisions)"
        ).fetchall()
    }
    if "active_account_keys_json" not in columns:
        op.execute(
            "ALTER TABLE net_worth_snapshot_revisions "
            "ADD COLUMN active_account_keys_json TEXT NOT NULL DEFAULT '[]'"
        )
    # Existing Phase 7 revisions predate this column.  Their immutable balance
    # rows are the only historical account-set source available, so backfill
    # from those rows rather than consulting the mutable account registry.
    op.execute(
        """
        UPDATE net_worth_snapshot_revisions
        SET active_account_keys_json = COALESCE(
            (
                SELECT json_group_array(account_key)
                FROM (
                    SELECT account_key
                    FROM net_worth_balances
                    WHERE revision_id = net_worth_snapshot_revisions.id
                    ORDER BY account_key
                )
            ),
            '[]'
        )
        """
    )


def downgrade() -> None:
    # The column is part of the 0008 table definition as well, so retaining it
    # keeps a database downgraded to 0008 runnable by the Phase 7 ORM.
    pass
