"""Persist local-only savings forecasts and their immutable assumptions."""

from alembic import op

revision = "0006_savings_forecasting"
down_revision = "0005_planning_quality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS savings_forecasts (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 200),
            scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id),
            source_revision_id TEXT NOT NULL REFERENCES planning_scenario_revisions(id),
            source_revision_number INTEGER NOT NULL CHECK(source_revision_number >= 1),
            currency TEXT NOT NULL CHECK(length(currency) BETWEEN 1 AND 12),
            horizon_months INTEGER NOT NULL DEFAULT 36 CHECK(horizon_months = 36),
            current_revision_number INTEGER NOT NULL DEFAULT 1 CHECK(current_revision_number >= 1),
            clone_of_forecast_id TEXT REFERENCES savings_forecasts(id),
            archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS savings_forecast_revisions (
            id TEXT PRIMARY KEY,
            forecast_id TEXT NOT NULL REFERENCES savings_forecasts(id) ON DELETE CASCADE,
            revision_number INTEGER NOT NULL CHECK(revision_number >= 1),
            source_revision_id TEXT NOT NULL REFERENCES planning_scenario_revisions(id),
            source_revision_number INTEGER NOT NULL CHECK(source_revision_number >= 1),
            policy_version TEXT NOT NULL,
            assumption_hash TEXT NOT NULL CHECK(length(assumption_hash) = 64),
            assumptions_json TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(forecast_id, revision_number)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS savings_forecast_cases (
            id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL REFERENCES savings_forecast_revisions(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK(role IN ('conservative', 'baseline', 'optimistic')),
            annual_return_rate TEXT NOT NULL
                CHECK(lower(annual_return_rate) NOT IN ('nan', 'infinity', '-infinity', 'inf', '-inf'))
                CHECK(CAST(annual_return_rate AS REAL) > -1),
            sweep_enabled INTEGER NOT NULL DEFAULT 0 CHECK(sweep_enabled IN (0, 1)),
            -- Pools are created after cases because pools also reference their
            -- owning case.  The service and integrity audit validate this
            -- optional cross-table reference.
            sweep_pool_id TEXT,
            confirmed INTEGER NOT NULL DEFAULT 0 CHECK(confirmed IN (0, 1)),
            UNIQUE(revision_id, role)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS savings_forecast_pools (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL REFERENCES savings_forecast_cases(id) ON DELETE CASCADE,
            name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 200),
            pool_type TEXT NOT NULL CHECK(pool_type IN ('cash', 'investment')),
            opening_balance TEXT NOT NULL
                CHECK(lower(opening_balance) NOT IN ('nan', 'infinity', '-infinity', 'inf', '-inf'))
                CHECK(CAST(opening_balance AS NUMERIC) >= 0),
            as_of_date TEXT NOT NULL,
            UNIQUE(case_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS savings_forecast_routings (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL REFERENCES savings_forecast_cases(id) ON DELETE CASCADE,
            source_item_id TEXT NOT NULL REFERENCES planning_items(id),
            pool_id TEXT NOT NULL REFERENCES savings_forecast_pools(id) ON DELETE CASCADE,
            UNIQUE(case_id, source_item_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS savings_forecast_adjustments (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL REFERENCES savings_forecast_cases(id) ON DELETE CASCADE,
            target_type TEXT NOT NULL CHECK(target_type IN ('line', 'category')),
            target TEXT NOT NULL,
            operation TEXT NOT NULL CHECK(operation IN ('replacement', 'fixed_delta', 'percentage_change')),
            value TEXT NOT NULL CHECK(lower(value) NOT IN ('nan', 'infinity', '-infinity', 'inf', '-inf')),
            start_month INTEGER NOT NULL CHECK(start_month BETWEEN 1 AND 36),
            end_month INTEGER CHECK(end_month IS NULL OR end_month BETWEEN 1 AND 36),
            CHECK(end_month IS NULL OR end_month >= start_month)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS savings_forecast_events (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL REFERENCES savings_forecast_cases(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL CHECK(event_type IN ('income', 'expense', 'contribution', 'withdrawal')),
            month INTEGER NOT NULL CHECK(month BETWEEN 1 AND 36),
            amount TEXT NOT NULL
                CHECK(lower(amount) NOT IN ('nan', 'infinity', '-infinity', 'inf', '-inf'))
                CHECK(CAST(amount AS NUMERIC) >= 0),
            label TEXT NOT NULL,
            pool_id TEXT REFERENCES savings_forecast_pools(id) ON DELETE CASCADE,
            CHECK(event_type NOT IN ('contribution', 'withdrawal') OR pool_id IS NOT NULL)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_savings_forecasts_active ON savings_forecasts(archived, updated_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_savings_forecast_cases_revision ON savings_forecast_cases(revision_id, role)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_savings_forecast_pools_case ON savings_forecast_pools(case_id, name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_savings_forecast_adjustments_case ON savings_forecast_adjustments(case_id, target, start_month)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_savings_forecast_events_case ON savings_forecast_events(case_id, month)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS savings_forecast_events")
    op.execute("DROP TABLE IF EXISTS savings_forecast_adjustments")
    op.execute("DROP TABLE IF EXISTS savings_forecast_routings")
    op.execute("DROP TABLE IF EXISTS savings_forecast_pools")
    op.execute("DROP TABLE IF EXISTS savings_forecast_cases")
    op.execute("DROP TABLE IF EXISTS savings_forecast_revisions")
    op.execute("DROP TABLE IF EXISTS savings_forecasts")
