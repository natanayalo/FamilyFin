"""Persist planning seed quality, snapshots, and item notes."""

from alembic import op
from sqlalchemy import CheckConstraint

revision = "0005_planning_quality"
down_revision = "0004_budget_planning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE planning_scenario_revisions "
        "ADD COLUMN provisional INTEGER NOT NULL DEFAULT 0 "
        "CHECK(provisional IN (0, 1))"
    )
    op.execute(
        "ALTER TABLE planning_scenario_revisions "
        "ADD COLUMN issue_codes_json TEXT NOT NULL DEFAULT '[]'"
    )
    op.execute(
        "ALTER TABLE planning_scenario_revisions "
        "ADD COLUMN completeness_snapshot_json TEXT NOT NULL DEFAULT '[]'"
    )
    op.execute(
        "ALTER TABLE planning_scenario_revisions "
        "ADD COLUMN expense_notes_json TEXT NOT NULL DEFAULT '[]'"
    )
    op.execute(
        "ALTER TABLE planning_items "
        "ADD COLUMN notes_json TEXT NOT NULL DEFAULT '[]'"
    )


def downgrade() -> None:
    # ``0004`` created these checks without names.  Alembic's batch mode does
    # not carry unnamed reflected checks into its temporary table, so pass the
    # original invariants explicitly when removing the Phase 4 columns.
    with op.batch_alter_table(
        "planning_items",
        table_args=(
            CheckConstraint(
                "kind IN ('income', 'expense', 'savings_contribution', 'savings_withdrawal')",
                name="ck_planning_items_kind",
            ),
            CheckConstraint(
                "frequency IN ('monthly', 'one_time')",
                name="ck_planning_items_frequency",
            ),
            CheckConstraint(
                "CAST(amount AS NUMERIC) >= 0",
                name="ck_planning_items_amount_nonnegative",
            ),
            CheckConstraint(
                "(frequency = 'monthly' AND start_month IS NOT NULL AND end_month IS NOT NULL AND occurrence_month IS NULL)"
                " OR (frequency = 'one_time' AND occurrence_month IS NOT NULL AND start_month IS NULL AND end_month IS NULL)",
                name="ck_planning_items_schedule",
            ),
        ),
    ) as batch:
        batch.drop_column("notes_json")
    with op.batch_alter_table(
        "planning_scenario_revisions",
        table_args=(CheckConstraint("revision_number >= 1", name="ck_planning_revision_number"),),
    ) as batch:
        batch.drop_column("expense_notes_json")
        batch.drop_column("completeness_snapshot_json")
        batch.drop_column("issue_codes_json")
        batch.drop_column("provisional")
