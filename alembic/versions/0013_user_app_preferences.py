"""Persist validated display defaults for each household login."""

from alembic import op

revision = "0013_user_app_preferences"
down_revision = "0012_api_authentication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE user_app_preferences (
            user_id TEXT PRIMARY KEY REFERENCES api_users(user_id) ON DELETE CASCADE,
            default_currency TEXT NOT NULL DEFAULT 'ILS'
                CHECK(length(default_currency) = 3 AND default_currency = upper(default_currency)),
            default_months INTEGER NOT NULL DEFAULT 12 CHECK(default_months BETWEEN 1 AND 60),
            updated_at TEXT NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE user_app_preferences")
