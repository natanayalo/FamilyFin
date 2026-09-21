"""Initial local import schema."""

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


# Keep this schema snapshot self-contained. Later migrations must not change
# the meaning of an already-applied initial revision by importing application
# code that may evolve independently.
INITIAL_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS source_files (
        id INTEGER PRIMARY KEY,
        sha256 TEXT NOT NULL UNIQUE,
        original_filename TEXT,
        archived_path TEXT NOT NULL,
        compressed_bytes INTEGER NOT NULL,
        uncompressed_bytes INTEGER NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS import_batches (
        id TEXT PRIMARY KEY,
        source_file_id INTEGER REFERENCES source_files(id),
        parser_version TEXT NOT NULL,
        baseline_batch_id TEXT,
        report_start TEXT,
        report_end TEXT,
        max_transaction_date TEXT,
        freshness_days INTEGER,
        status TEXT NOT NULL,
        statistics_json TEXT NOT NULL,
        error_code TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY,
        provider TEXT NOT NULL,
        account_kind TEXT NOT NULL,
        source_reference_fingerprint TEXT NOT NULL UNIQUE,
        display_label TEXT NOT NULL,
        currency TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY,
        movement_type TEXT NOT NULL DEFAULT '',
        category TEXT NOT NULL,
        UNIQUE(movement_type, category)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_records (
        id INTEGER PRIMARY KEY,
        import_batch_id TEXT NOT NULL REFERENCES import_batches(id),
        account_id INTEGER NOT NULL REFERENCES accounts(id),
        sheet_name TEXT NOT NULL,
        section_index INTEGER NOT NULL,
        source_row_number INTEGER NOT NULL,
        raw_payload_json TEXT NOT NULL,
        normalized_json TEXT NOT NULL,
        row_fingerprint TEXT NOT NULL,
        validation_state TEXT NOT NULL,
        issues_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(import_batch_id, sheet_name, source_row_number)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY,
        account_id INTEGER NOT NULL REFERENCES accounts(id),
        booking_date TEXT NOT NULL,
        allocation_date TEXT NOT NULL,
        amount TEXT NOT NULL,
        currency TEXT NOT NULL,
        original_currency TEXT,
        original_amount TEXT,
        description TEXT NOT NULL,
        movement_type TEXT,
        category TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'accepted',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transaction_sources (
        transaction_id INTEGER NOT NULL REFERENCES transactions(id),
        source_record_id INTEGER NOT NULL REFERENCES source_records(id),
        match_method TEXT NOT NULL,
        linked_at TEXT NOT NULL,
        PRIMARY KEY(transaction_id, source_record_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reconciliation_cases (
        id TEXT PRIMARY KEY,
        import_batch_id TEXT NOT NULL REFERENCES import_batches(id),
        source_record_id INTEGER NOT NULL REFERENCES source_records(id),
        status TEXT NOT NULL DEFAULT 'open',
        reason TEXT NOT NULL,
        candidate_transaction_ids_json TEXT NOT NULL,
        resolution_json TEXT,
        created_at TEXT NOT NULL,
        resolved_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS analysis_overrides (
        id INTEGER PRIMARY KEY,
        transaction_id INTEGER NOT NULL REFERENCES transactions(id),
        field_name TEXT NOT NULL,
        value TEXT,
        reason TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_transactions_identity
        ON transactions(account_id, booking_date, amount, currency)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_transactions_description
        ON transactions(account_id, description, currency)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_source_records_batch
        ON source_records(import_batch_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_reconciliation_open
        ON reconciliation_cases(status)
    """,
)


def upgrade() -> None:
    for statement in INITIAL_SCHEMA_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for table in [
        "analysis_overrides",
        "reconciliation_cases",
        "transaction_sources",
        "transactions",
        "source_records",
        "categories",
        "accounts",
        "import_batches",
        "source_files",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table}")
