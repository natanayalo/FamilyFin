"""Persist local automation runs, deterministic alerts, and monthly summaries."""

from alembic import op

revision = "0010_automation_and_insights"
down_revision = "0009_phase7_integrity_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS automation_preferences (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            planning_scenario_id TEXT,
            planning_revision_id TEXT,
            forecast_id TEXT,
            forecast_revision_id TEXT,
            forecast_role TEXT,
            apartment_study_id TEXT,
            apartment_revision_id TEXT,
            apartment_alternative_name TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS automation_runs (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            dry_run INTEGER NOT NULL DEFAULT 0 CHECK(dry_run IN (0, 1)),
            audit_passed INTEGER NOT NULL DEFAULT 0 CHECK(audit_passed IN (0, 1)),
            backup_path TEXT,
            counts_json TEXT NOT NULL DEFAULT '{}',
            issue_codes_json TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS automation_file_outcomes (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES automation_runs(id) ON DELETE CASCADE,
            source_path TEXT NOT NULL,
            sha256 TEXT,
            status TEXT NOT NULL,
            reason_code TEXT,
            import_batch_id TEXT REFERENCES import_batches(id),
            managed_path TEXT,
            size_bytes INTEGER,
            created_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS insight_alerts (
            id TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL UNIQUE,
            algorithm_version TEXT NOT NULL,
            condition_type TEXT NOT NULL,
            subject_identity TEXT NOT NULL,
            currency TEXT,
            evidence_period TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('open', 'acknowledged', 'resolved')),
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            occurrence_count INTEGER NOT NULL DEFAULT 1 CHECK(occurrence_count >= 1),
            evidence_json TEXT NOT NULL DEFAULT '{}',
            acknowledged_at TEXT,
            resolved_at TEXT,
            manual_resolution_fingerprint TEXT
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS insight_alert_events (
            id TEXT PRIMARY KEY,
            alert_id TEXT NOT NULL REFERENCES insight_alerts(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            from_state TEXT,
            to_state TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS monthly_summary_identities (
            id TEXT PRIMARY KEY,
            month TEXT NOT NULL,
            currency TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(month, currency)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS monthly_summary_revisions (
            id TEXT PRIMARY KEY,
            identity_id TEXT NOT NULL REFERENCES monthly_summary_identities(id) ON DELETE CASCADE,
            revision_number INTEGER NOT NULL CHECK(revision_number >= 1),
            month TEXT NOT NULL,
            currency TEXT NOT NULL,
            input_fingerprint TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            content_json TEXT NOT NULL,
            markdown TEXT NOT NULL,
            contributor_provenance_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(identity_id, revision_number),
            UNIQUE(identity_id, input_fingerprint)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_automation_outcomes_run ON automation_file_outcomes(run_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_alerts_state ON insight_alerts(state, last_seen)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_alert_events_alert ON insight_alert_events(alert_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_summary_revisions_month ON monthly_summary_revisions(month, currency, revision_number)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS monthly_summary_revisions")
    op.execute("DROP TABLE IF EXISTS monthly_summary_identities")
    op.execute("DROP TABLE IF EXISTS insight_alert_events")
    op.execute("DROP TABLE IF EXISTS insight_alerts")
    op.execute("DROP TABLE IF EXISTS automation_file_outcomes")
    op.execute("DROP TABLE IF EXISTS automation_runs")
    op.execute("DROP TABLE IF EXISTS automation_preferences")
