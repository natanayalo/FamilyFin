"""Store completed API responses inside participating write transactions."""

from alembic import op

revision = "0011_api_idempotency"
down_revision = "0010_automation_and_insights"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE api_idempotency_records (
            id TEXT PRIMARY KEY,
            actor_id TEXT NOT NULL,
            http_method TEXT NOT NULL,
            canonical_route TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            response_status INTEGER NOT NULL CHECK(response_status BETWEEN 100 AND 599),
            response_body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            CONSTRAINT uq_api_idempotency_scope_key
                UNIQUE(actor_id, http_method, canonical_route, idempotency_key)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE api_idempotency_records")
