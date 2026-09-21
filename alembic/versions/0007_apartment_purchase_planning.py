"""Persist immutable apartment purchase studies and alternatives."""

from alembic import op

revision = "0007_apartment_purchase_planning"
down_revision = "0006_savings_forecasting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS apartment_studies (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 200),
            forecast_id TEXT NOT NULL REFERENCES savings_forecasts(id),
            forecast_revision_id TEXT NOT NULL REFERENCES savings_forecast_revisions(id),
            forecast_revision_number INTEGER NOT NULL CHECK(forecast_revision_number >= 1),
            forecast_assumption_hash TEXT NOT NULL CHECK(length(forecast_assumption_hash) = 64),
            currency TEXT NOT NULL CHECK(length(currency) BETWEEN 1 AND 12),
            current_revision_number INTEGER NOT NULL DEFAULT 1 CHECK(current_revision_number >= 1),
            clone_of_study_id TEXT REFERENCES apartment_studies(id),
            archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS apartment_study_revisions (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES apartment_studies(id) ON DELETE CASCADE,
            revision_number INTEGER NOT NULL CHECK(revision_number >= 1),
            forecast_id TEXT NOT NULL REFERENCES savings_forecasts(id),
            forecast_revision_id TEXT NOT NULL REFERENCES savings_forecast_revisions(id),
            forecast_revision_number INTEGER NOT NULL CHECK(forecast_revision_number >= 1),
            forecast_assumption_hash TEXT NOT NULL CHECK(length(forecast_assumption_hash) = 64),
            policy_version TEXT NOT NULL,
            assumption_hash TEXT NOT NULL CHECK(length(assumption_hash) = 64),
            assumptions_json TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            source_quality_acknowledged INTEGER NOT NULL DEFAULT 0 CHECK(source_quality_acknowledged IN (0, 1)),
            created_at TEXT NOT NULL,
            UNIQUE(study_id, revision_number)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS apartment_alternatives (
            id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL REFERENCES apartment_study_revisions(id) ON DELETE CASCADE,
            name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 200),
            forecast_role TEXT NOT NULL CHECK(forecast_role IN ('conservative', 'baseline', 'optimistic')),
            purchase_month INTEGER NOT NULL CHECK(purchase_month BETWEEN 1 AND 36),
            property_price TEXT NOT NULL CHECK(CAST(property_price AS NUMERIC) >= 0),
            family_gift TEXT NOT NULL CHECK(CAST(family_gift AS NUMERIC) >= 0),
            equity_mode TEXT NOT NULL CHECK(equity_mode IN ('percentage', 'amount')),
            equity_value TEXT NOT NULL CHECK(CAST(equity_value AS NUMERIC) >= 0),
            mortgage_principal TEXT NOT NULL CHECK(CAST(mortgage_principal AS NUMERIC) >= 0),
            mortgage_annual_nominal_rate TEXT NOT NULL CHECK(CAST(mortgage_annual_nominal_rate AS NUMERIC) >= 0),
            mortgage_term_months INTEGER NOT NULL CHECK(mortgage_term_months BETWEEN 12 AND 480),
            confirmed INTEGER NOT NULL DEFAULT 0 CHECK(confirmed IN (0, 1)),
            UNIQUE(revision_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS apartment_purchase_costs (
            id TEXT PRIMARY KEY,
            alternative_id TEXT NOT NULL REFERENCES apartment_alternatives(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            amount TEXT NOT NULL CHECK(CAST(amount AS NUMERIC) >= 0),
            UNIQUE(alternative_id, label)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS apartment_pool_draws (
            id TEXT PRIMARY KEY,
            alternative_id TEXT NOT NULL REFERENCES apartment_alternatives(id) ON DELETE CASCADE,
            pool_name TEXT NOT NULL,
            amount TEXT NOT NULL CHECK(CAST(amount AS NUMERIC) >= 0),
            UNIQUE(alternative_id, pool_name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS apartment_stopped_housing_lines (
            id TEXT PRIMARY KEY,
            alternative_id TEXT NOT NULL REFERENCES apartment_alternatives(id) ON DELETE CASCADE,
            source_item_id TEXT NOT NULL REFERENCES planning_items(id),
            UNIQUE(alternative_id, source_item_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS apartment_housing_costs (
            id TEXT PRIMARY KEY,
            alternative_id TEXT NOT NULL REFERENCES apartment_alternatives(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            amount TEXT NOT NULL CHECK(CAST(amount AS NUMERIC) >= 0),
            UNIQUE(alternative_id, label)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_apartment_studies_active ON apartment_studies(archived, updated_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_apartment_revisions_study ON apartment_study_revisions(study_id, revision_number)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_apartment_alternatives_revision ON apartment_alternatives(revision_id, name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_apartment_pool_draws_alt ON apartment_pool_draws(alternative_id, pool_name)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS apartment_housing_costs")
    op.execute("DROP TABLE IF EXISTS apartment_stopped_housing_lines")
    op.execute("DROP TABLE IF EXISTS apartment_pool_draws")
    op.execute("DROP TABLE IF EXISTS apartment_purchase_costs")
    op.execute("DROP TABLE IF EXISTS apartment_alternatives")
    op.execute("DROP TABLE IF EXISTS apartment_study_revisions")
    op.execute("DROP TABLE IF EXISTS apartment_studies")
