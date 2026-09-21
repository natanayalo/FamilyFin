"""Immutable local budget-planning scenarios and seed provenance."""

from alembic import op

revision = "0004_budget_planning"
down_revision = "0003_financial_classification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS planning_scenarios (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            currency TEXT NOT NULL,
            start_month TEXT NOT NULL,
            end_month TEXT NOT NULL,
            current_revision_number INTEGER NOT NULL DEFAULT 1 CHECK(current_revision_number >= 1),
            clone_of_scenario_id TEXT REFERENCES planning_scenarios(id),
            archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK(length(currency) BETWEEN 1 AND 12),
            CHECK(start_month <= end_month)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS planning_scenario_revisions (
            id TEXT PRIMARY KEY,
            scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
            revision_number INTEGER NOT NULL CHECK(revision_number >= 1),
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(scenario_id, revision_number)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS planning_items (
            id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL REFERENCES planning_scenario_revisions(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(kind IN ('income', 'expense', 'savings_contribution', 'savings_withdrawal')),
            category TEXT,
            label TEXT NOT NULL,
            amount TEXT NOT NULL,
            frequency TEXT NOT NULL CHECK(frequency IN ('monthly', 'one_time')),
            start_month TEXT,
            end_month TEXT,
            occurrence_month TEXT,
            origin TEXT NOT NULL DEFAULT 'manual',
            source_range TEXT,
            source_row INTEGER,
            policy_version TEXT NOT NULL DEFAULT 'planning-v1',
            completeness_codes_json TEXT NOT NULL DEFAULT '[]',
            contributor_transaction_ids_json TEXT NOT NULL DEFAULT '[]',
            provenance_json TEXT NOT NULL DEFAULT '{}',
            CHECK(CAST(amount AS NUMERIC) >= 0),
            CHECK(
                (frequency = 'monthly' AND start_month IS NOT NULL AND end_month IS NOT NULL AND occurrence_month IS NULL)
                OR (frequency = 'one_time' AND occurrence_month IS NOT NULL AND start_month IS NULL AND end_month IS NULL)
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS planning_source_files (
            id INTEGER PRIMARY KEY,
            sha256 TEXT NOT NULL UNIQUE,
            original_filename TEXT,
            archived_path TEXT NOT NULL,
            compressed_bytes INTEGER NOT NULL,
            uncompressed_bytes INTEGER NOT NULL,
            parser_version TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS planning_seed_imports (
            id TEXT PRIMARY KEY,
            source_file_id INTEGER NOT NULL REFERENCES planning_source_files(id),
            scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id),
            revision_id TEXT NOT NULL REFERENCES planning_scenario_revisions(id),
            origin TEXT NOT NULL,
            parser_version TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            UNIQUE(source_file_id, scenario_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_planning_scenarios_active
        ON planning_scenarios(archived, updated_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_planning_revisions_scenario
        ON planning_scenario_revisions(scenario_id, revision_number)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_planning_items_revision
        ON planning_items(revision_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS planning_seed_imports")
    op.execute("DROP TABLE IF EXISTS planning_source_files")
    op.execute("DROP TABLE IF EXISTS planning_items")
    op.execute("DROP TABLE IF EXISTS planning_scenario_revisions")
    op.execute("DROP TABLE IF EXISTS planning_scenarios")
