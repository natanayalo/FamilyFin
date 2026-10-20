"""Save household decisions about detected recurring spending."""

from alembic import op

revision = "0014_recurring_pattern_reviews"
down_revision = "0013_user_app_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE recurring_pattern_reviews (
            pattern_id TEXT PRIMARY KEY,
            currency TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('approved', 'dismissed', 'stopped', 'pending')),
            pattern_json TEXT NOT NULL,
            updated_by TEXT REFERENCES api_users(user_id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    op.execute("CREATE INDEX ix_recurring_pattern_reviews_currency ON recurring_pattern_reviews(currency)")


def downgrade() -> None:
    op.execute("DROP TABLE recurring_pattern_reviews")
