"""Persist account-level household net-worth snapshots and provenance."""

from alembic import op

revision = "0008_household_net_worth"
down_revision = "0007_apartment_purchase_planning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS net_worth_accounts (
            id TEXT PRIMARY KEY,
            account_key TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL CHECK(length(display_name) BETWEEN 1 AND 200),
            side TEXT NOT NULL CHECK(side IN ('asset', 'liability')),
            category TEXT NOT NULL CHECK(category IN (
                'cash', 'savings', 'investment', 'pension', 'training_fund', 'property', 'other',
                'mortgage', 'loan', 'credit'
            )),
            liquidity TEXT CHECK(liquidity IS NULL OR liquidity IN ('liquid', 'restricted', 'illiquid')),
            owner_label TEXT,
            active_from TEXT NOT NULL,
            active_to TEXT,
            stale_after_days INTEGER NOT NULL CHECK(stale_after_days > 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK(active_to IS NULL OR active_to >= active_from),
            CHECK((side = 'liability' AND liquidity IS NULL) OR (side = 'asset' AND liquidity IS NOT NULL)),
            CHECK((side = 'asset' AND category IN ('cash', 'savings', 'investment', 'pension', 'training_fund', 'property', 'other'))
               OR (side = 'liability' AND category IN ('mortgage', 'loan', 'credit', 'other')))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS net_worth_snapshots (
            id TEXT PRIMARY KEY,
            snapshot_date TEXT NOT NULL UNIQUE,
            current_revision_number INTEGER NOT NULL DEFAULT 1 CHECK(current_revision_number >= 1),
            archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS net_worth_source_files (
            id INTEGER PRIMARY KEY,
            sha256 TEXT NOT NULL UNIQUE CHECK(length(sha256) = 64),
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
        CREATE TABLE IF NOT EXISTS net_worth_snapshot_revisions (
            id TEXT PRIMARY KEY,
            snapshot_id TEXT NOT NULL REFERENCES net_worth_snapshots(id) ON DELETE CASCADE,
            revision_number INTEGER NOT NULL CHECK(revision_number >= 1),
            snapshot_date TEXT NOT NULL,
            origin TEXT NOT NULL CHECK(origin IN ('manual', 'csv', 'restored')),
            notes TEXT NOT NULL DEFAULT '',
            quality_issues_json TEXT NOT NULL DEFAULT '[]',
            quality_acknowledged INTEGER NOT NULL DEFAULT 0 CHECK(quality_acknowledged IN (0, 1)),
            content_hash TEXT NOT NULL CHECK(length(content_hash) = 64),
            active_account_keys_json TEXT NOT NULL DEFAULT '[]',
            source_file_id INTEGER REFERENCES net_worth_source_files(id),
            created_at TEXT NOT NULL,
            UNIQUE(snapshot_id, revision_number)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS net_worth_balances (
            id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL REFERENCES net_worth_snapshot_revisions(id) ON DELETE CASCADE,
            account_key TEXT NOT NULL REFERENCES net_worth_accounts(account_key),
            account_name TEXT NOT NULL,
            side TEXT NOT NULL CHECK(side IN ('asset', 'liability')),
            category TEXT NOT NULL,
            liquidity TEXT CHECK(liquidity IS NULL OR liquidity IN ('liquid', 'restricted', 'illiquid')),
            owner_label TEXT,
            stale_after_days INTEGER NOT NULL CHECK(stale_after_days > 0),
            amount_ils TEXT NOT NULL
                CHECK(lower(amount_ils) NOT IN ('nan', 'infinity', '-infinity', 'inf', '-inf'))
                CHECK(CAST(amount_ils AS NUMERIC) >= 0),
            snapshot_date TEXT NOT NULL,
            valuation_date TEXT NOT NULL CHECK(valuation_date <= snapshot_date),
            notes TEXT NOT NULL DEFAULT '',
            UNIQUE(revision_id, account_key)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS net_worth_imports (
            id TEXT PRIMARY KEY,
            source_file_id INTEGER NOT NULL REFERENCES net_worth_source_files(id),
            snapshot_id TEXT NOT NULL REFERENCES net_worth_snapshots(id),
            revision_id TEXT NOT NULL REFERENCES net_worth_snapshot_revisions(id),
            origin TEXT NOT NULL,
            imported_at TEXT NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_net_worth_accounts_active ON net_worth_accounts(active_from, active_to)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_net_worth_snapshots_date ON net_worth_snapshots(snapshot_date, archived)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_net_worth_revisions_date ON net_worth_snapshot_revisions(snapshot_date, revision_number)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_net_worth_balances_account_date ON net_worth_balances(account_key, valuation_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_net_worth_imports_source ON net_worth_imports(source_file_id)")
    op.execute(
        "ALTER TABLE savings_forecast_revisions ADD COLUMN net_worth_snapshot_revision_id TEXT"
    )
    op.execute("ALTER TABLE savings_forecast_pools ADD COLUMN net_worth_account_key TEXT")
    op.execute(
        "ALTER TABLE savings_forecast_pools ADD COLUMN net_worth_snapshot_revision_id TEXT"
    )
    op.execute("ALTER TABLE savings_forecast_pools ADD COLUMN source_valuation_date TEXT")
    op.execute(
        "ALTER TABLE savings_forecast_pools ADD COLUMN source_quality_acknowledged INTEGER NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE savings_forecast_pools DROP COLUMN source_quality_acknowledged")
    op.execute("ALTER TABLE savings_forecast_pools DROP COLUMN source_valuation_date")
    op.execute("ALTER TABLE savings_forecast_pools DROP COLUMN net_worth_snapshot_revision_id")
    op.execute("ALTER TABLE savings_forecast_pools DROP COLUMN net_worth_account_key")
    op.execute("ALTER TABLE savings_forecast_revisions DROP COLUMN net_worth_snapshot_revision_id")
    op.execute("DROP TABLE IF EXISTS net_worth_imports")
    op.execute("DROP TABLE IF EXISTS net_worth_balances")
    op.execute("DROP TABLE IF EXISTS net_worth_snapshot_revisions")
    op.execute("DROP TABLE IF EXISTS net_worth_source_files")
    op.execute("DROP TABLE IF EXISTS net_worth_snapshots")
    op.execute("DROP TABLE IF EXISTS net_worth_accounts")
