"""Add household API identities, revocable sessions, throttling, and actor audit."""

from alembic import op

revision = "0012_api_authentication"
down_revision = "0011_api_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE api_users (
            user_id TEXT PRIMARY KEY,
            username TEXT NOT NULL COLLATE NOCASE UNIQUE,
            display_name TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TRIGGER api_users_max_two_accounts
        BEFORE INSERT ON api_users
        WHEN (SELECT COUNT(*) FROM api_users) >= 2
        BEGIN
            SELECT RAISE(ABORT, 'exactly two household accounts are supported');
        END
        """
    )
    op.execute(
        """
        CREATE TABLE api_sessions (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES api_users(user_id) ON DELETE CASCADE,
            csrf_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT
        )
        """
    )
    op.execute("CREATE INDEX idx_api_sessions_user ON api_sessions(user_id, expires_at)")
    op.execute(
        """
        CREATE TABLE api_login_throttles (
            throttle_key_hash TEXT PRIMARY KEY,
            failure_count INTEGER NOT NULL CHECK(failure_count >= 0),
            window_started_at TEXT NOT NULL,
            blocked_until TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE actor_audit_events (
            id TEXT PRIMARY KEY,
            actor_id TEXT REFERENCES api_users(user_id) ON DELETE SET NULL,
            event_type TEXT NOT NULL,
            request_id TEXT NOT NULL,
            target_type TEXT,
            outcome TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX idx_actor_audit_events_created ON actor_audit_events(created_at)")
    op.execute(
        """
        CREATE TRIGGER actor_audit_events_no_update
        BEFORE UPDATE ON actor_audit_events
        BEGIN
            SELECT RAISE(ABORT, 'actor audit events are append-only');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER actor_audit_events_no_delete
        BEFORE DELETE ON actor_audit_events
        BEGIN
            SELECT RAISE(ABORT, 'actor audit events are append-only');
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER actor_audit_events_no_delete")
    op.execute("DROP TRIGGER actor_audit_events_no_update")
    op.execute("DROP TABLE actor_audit_events")
    op.execute("DROP TABLE api_login_throttles")
    op.execute("DROP TABLE api_sessions")
    op.execute("DROP TRIGGER api_users_max_two_accounts")
    op.execute("DROP TABLE api_users")
