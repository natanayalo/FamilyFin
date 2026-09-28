from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from family_finance.api.auth import SESSION_COOKIE_NAME
from family_finance.audit import AuditService
from family_finance.automation import AutomationService
from family_finance.models import AuditCheck, AuditReport
from family_finance.persistence.models import (
    ActorAuditEventRow,
    ApiSessionRow,
    AutomationRunRow,
    InsightAlertRow,
    TransactionRow,
)
from tests.conftest import make_workbook
from tests.test_api_auth import ApiTestClient, make_api

BASE_URL = "https://testserver"


def sign_in(client, username: str, password: str) -> tuple[str, dict[str, str]]:
    response = client.post(
        "/api/v1/auth/session",
        json={"username": username, "password": password},
        headers={"Origin": BASE_URL},
    )
    assert response.status_code == 200
    return response.json()["data"]["csrf_token"], {"Origin": BASE_URL}


def mutation_headers(csrf: str) -> dict[str, str]:
    return {"Origin": BASE_URL, "X-CSRF-Token": csrf}


def test_operations_and_settings_require_auth_and_dry_run_is_non_mutating(tmp_path):
    settings, database, _, app = make_api(tmp_path)
    settings.ensure_directories()
    (settings.automation_inbox_root / "private-name.xlsx").write_bytes(b"not a workbook")
    with ApiTestClient(app, base_url=BASE_URL) as client:
        for path in (
            "/api/v1/automation/status", "/api/v1/automation/inbox",
            "/api/v1/automation/runs", "/api/v1/operations/audit",
            "/api/v1/operations/backup-readiness", "/api/v1/insights/preferences",
            "/api/v1/insights/alerts", "/api/v1/insights/monthly-summaries",
            "/api/v1/settings", "/api/v1/settings/sessions",
        ):
            assert client.get(path).status_code == 401
        csrf, _ = sign_in(client, "sam", "Long-test-password-One!")
        status = client.get("/api/v1/automation/status")
        assert status.status_code == 200
        assert status.json()["data"]["inbox"] == {"inbox_file_count": 1, "review_file_count": 0}
        assert "private-name.xlsx" not in status.text
        assert str(tmp_path) not in status.text

        dry_run = client.post(
            "/api/v1/automation/runs",
            json={"dry_run": True},
            headers=mutation_headers(csrf),
        )
        assert dry_run.status_code == 200
        assert dry_run.json()["data"]["status"] == "dry_run"
        assert dry_run.json()["data"]["items"] == [{"status": "invalid", "reason_code": "SCHEMA_INVALID"}]
        assert "private-name.xlsx" not in dry_run.text
        assert str(tmp_path) not in dry_run.text
        assert (settings.automation_inbox_root / "private-name.xlsx").is_file()
        with database.session() as session:
            assert session.query(AutomationRunRow).count() == 0
            assert session.query(TransactionRow).count() == 0

        # The request schema rejects arbitrary paths or command-shaped fields.
        rejected = client.post(
            "/api/v1/automation/runs",
            json={"dry_run": True, "backup_destination": "/tmp/override"},
            headers=mutation_headers(csrf),
        )
        assert rejected.status_code == 422


def test_manual_run_blocks_without_readiness_and_before_financial_mutation(tmp_path, monkeypatch):
    settings, database, _, app = make_api(tmp_path)
    settings.ensure_directories()
    inbox_file = settings.automation_inbox_root / "queued.xlsx"
    inbox_file.write_bytes(b"not a workbook")

    with ApiTestClient(app, base_url=BASE_URL) as client:
        csrf, _ = sign_in(client, "sam", "Long-test-password-One!")
        response = client.post(
            "/api/v1/automation/runs", json={"dry_run": False},
            headers=mutation_headers(csrf),
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "AUTOMATION_NOT_READY"
        assert inbox_file.is_file()
        with database.session() as session:
            assert session.query(TransactionRow).count() == 0
            events = session.execute(
                select(ActorAuditEventRow).where(ActorAuditEventRow.event_type == "automation.manual_run")
            ).scalars().all()
            assert events[-1].outcome == "blocked"



def test_manual_run_blocks_when_audit_readiness_fails(tmp_path, monkeypatch):
    root = tmp_path / "automation-backups"
    settings, database, _, app = make_api(tmp_path, automation_backup_root=root)
    settings.ensure_directories()
    inbox_file = settings.automation_inbox_root / "queued.xlsx"
    inbox_file.write_bytes(b"not a workbook")
    monkeypatch.setattr(
        AuditService,
        "run",
        lambda *_args, **_kwargs: AuditReport(
            passed=False,
            checks=[AuditCheck(name="sqlite_integrity", passed=False, issue_codes=["SQLITE_INTEGRITY_ERROR"])],
        ),
    )
    with ApiTestClient(app, base_url=BASE_URL) as client:
        csrf, _ = sign_in(client, "sam", "Long-test-password-One!")
        failed_readiness = client.post(
            "/api/v1/automation/runs", json={"dry_run": False},
            headers=mutation_headers(csrf),
        )
        assert failed_readiness.status_code == 409
        assert failed_readiness.json()["error"]["fields"]["reason"] == ["AUDIT_FAILED"]
        assert inbox_file.is_file()
        with database.session() as session:
            assert session.query(TransactionRow).count() == 0


def test_symlink_backup_destination_is_reported_unavailable_and_blocks(tmp_path):
    backup_root = tmp_path / "configured-backup-root"
    external_target = tmp_path / "external-target"
    settings, _database, _, app = make_api(tmp_path, automation_backup_root=backup_root)
    settings.ensure_directories()
    backup_root.symlink_to(external_target, target_is_directory=True)
    with ApiTestClient(app, base_url=BASE_URL) as client:
        csrf, _ = sign_in(client, "sam", "Long-test-password-One!")
        readiness = client.get("/api/v1/operations/backup-readiness").json()["data"]
        assert readiness["backup"]["status"] == "unavailable"
        assert readiness["run_now_allowed"] is False
        blocked = client.post(
            "/api/v1/automation/runs", json={"dry_run": False},
            headers=mutation_headers(csrf),
        )
        assert blocked.status_code == 409
        assert blocked.json()["error"]["fields"]["reason"] == ["AUTOMATION_BACKUP_DESTINATION_UNAVAILABLE"]
        assert not external_target.exists()


def test_api_failed_backup_blocks_before_import_or_file_move(tmp_path, monkeypatch):
    settings, database, _, app = make_api(
        tmp_path,
        automation_backup_root=tmp_path / "automation-backups",
    )
    settings.ensure_directories()
    inbox_file = settings.automation_inbox_root / "queued.xlsx"
    inbox_file.write_bytes(b"not a workbook")

    def fail_backup(_automation):
        raise OSError("backup volume unavailable")

    monkeypatch.setattr(AutomationService, "_create_backup", fail_backup)
    with ApiTestClient(app, base_url=BASE_URL) as client:
        csrf, _ = sign_in(client, "sam", "Long-test-password-One!")
        result = client.post(
            "/api/v1/automation/runs", json={"dry_run": False},
            headers=mutation_headers(csrf),
        )
        assert result.status_code == 200
        assert result.json()["data"]["status"] == "blocked_backup"
        assert result.json()["data"]["issue_codes"] == ["AUTOMATION_BACKUP_FAILED"]
        assert inbox_file.is_file()
        with database.session() as session:
            assert session.query(TransactionRow).count() == 0


def test_configured_manual_run_creates_verified_pre_import_backup(tmp_path):
    settings, database, _, app = make_api(
        tmp_path,
        automation_backup_root=tmp_path / "automation-backups",
        automation_stability_delay_seconds=0,
    )
    settings.ensure_directories()
    source = settings.automation_inbox_root / "synthetic.xlsx"
    source.write_bytes(
        make_workbook([[
            "19/09/2026", -17.40, "merchant", "19/09/2026", "food",
            "household", "ILS", "ILS", -17.40,
        ]])
    )

    with ApiTestClient(app, base_url=BASE_URL) as client:
        csrf, _ = sign_in(client, "sam", "Long-test-password-One!")
        response = client.post(
            "/api/v1/automation/runs", json={"dry_run": False},
            headers=mutation_headers(csrf),
        )
        assert response.status_code == 200
        result = response.json()["data"]
        assert result["status"] in {"completed", "completed_with_warnings"}
        assert result["backup_created"] is True
        assert not source.exists()
        backups = list(settings.automation_backup_root.iterdir())
        assert len(backups) == 1
        from family_finance.backup import BackupService

        assert BackupService(database, settings).verify(backups[0]).passed
        with database.session() as session:
            assert session.query(TransactionRow).count() == 1


def test_insights_two_user_permissions_preferences_review_and_sessions(tmp_path):
    _settings, database, _, app = make_api(tmp_path)
    now = datetime.now(UTC).isoformat()
    alert_id = str(uuid.uuid4())
    with database.write_session() as session:
        session.add(InsightAlertRow(
            id=alert_id, fingerprint="f" * 64, algorithm_version="test-v1",
            condition_type="stale_import", subject_identity="latest_import", currency=None,
            evidence_period="current", state="open", first_seen=now, last_seen=now,
            occurrence_count=1, evidence_json=json.dumps({"freshness_days": 45}),
            acknowledged_at=None, resolved_at=None, manual_resolution_fingerprint=None,
        ))

    with ApiTestClient(app, base_url=BASE_URL) as client:
        sam_csrf, _ = sign_in(client, "sam", "Long-test-password-One!")
        saved = client.put(
            "/api/v1/settings/preferences",
            json={"default_currency": "eur", "default_months": 24},
            headers=mutation_headers(sam_csrf),
        )
        assert saved.status_code == 200
        assert saved.json()["data"]["default_currency"] == "EUR"
        sam_dashboard = client.get("/api/v1/dashboard/overview").json()["data"]["filters"]
        assert sam_dashboard["currency"] == "EUR"
        assert sam_dashboard["start_month"] == "2024-10-01"
        sam_login_two = client.post(
            "/api/v1/auth/session",
            json={"username": "sam", "password": "Long-test-password-One!"},
            headers={"Origin": BASE_URL},
        )
        sam_csrf_two = sam_login_two.json()["data"]["csrf_token"]
        sam_session_two = client.cookies.get(SESSION_COOKIE_NAME)

        lee_csrf, _ = sign_in(client, "lee", "Long-test-password-Two!")
        lee_settings = client.get("/api/v1/settings").json()["data"]
        assert lee_settings["preferences"]["default_currency"] == "ILS"
        lee_dashboard = client.get("/api/v1/dashboard/overview").json()["data"]["filters"]
        assert lee_dashboard["currency"] == "ILS"
        assert lee_dashboard["start_month"] == "2025-10-01"
        lee_sessions = client.get("/api/v1/settings/sessions").json()["data"]["items"]
        assert len(lee_sessions) == 1 and lee_sessions[0]["current"] is True
        sam_session_hash = hashlib.sha256(sam_session_two.encode()).hexdigest()
        foreign_revoke = client.delete(
            f"/api/v1/settings/sessions/{sam_session_hash}",
            headers=mutation_headers(lee_csrf),
        )
        assert foreign_revoke.status_code == 404

        client.client.cookies.set(SESSION_COOKIE_NAME, sam_session_two, domain="testserver.local", path="/api/v1")
        sam_settings = client.get("/api/v1/settings").json()["data"]
        assert sam_settings["preferences"]["default_currency"] == "EUR"
        sam_sessions = client.get("/api/v1/settings/sessions").json()["data"]["items"]
        assert len(sam_sessions) == 2
        current_session = next(item for item in sam_sessions if item["current"])
        denied_current = client.delete(
            f"/api/v1/settings/sessions/{current_session['id']}",
            headers=mutation_headers(sam_csrf_two),
        )
        assert denied_current.status_code == 409
        other_session = next(item for item in sam_sessions if not item["current"])
        revoked = client.delete(
            f"/api/v1/settings/sessions/{other_session['id']}",
            headers=mutation_headers(sam_csrf_two),
        )
        assert revoked.status_code == 204
        with database.session() as session:
            other = session.get(ApiSessionRow, other_session["id"])
            assert other is not None and other.revoked_at is not None

        # Both household accounts have equal access to shared insight results.
        client.client.cookies.set(SESSION_COOKIE_NAME, sam_session_two, domain="testserver.local", path="/api/v1")
        alerts = client.get("/api/v1/insights/alerts?state=open")
        assert alerts.status_code == 200 and alerts.json()["data"]["items"][0]["id"] == alert_id
        acknowledge = client.post(
            f"/api/v1/insights/alerts/{alert_id}/acknowledge",
            json={}, headers=mutation_headers(sam_csrf_two),
        )
        assert acknowledge.status_code == 200
        assert acknowledge.json()["data"]["state"] == "acknowledged"

        # Restore Lee's cookie and confirm the same review result is visible.
        lee_login = client.post(
            "/api/v1/auth/session",
            json={"username": "lee", "password": "Long-test-password-Two!"},
            headers={"Origin": BASE_URL},
        )
        lee_csrf = lee_login.json()["data"]["csrf_token"]
        assert client.get("/api/v1/insights/alerts?state=acknowledged").status_code == 200
        assert client.get("/api/v1/operations/audit").status_code == 200
        assert client.get("/api/v1/insights/monthly-summaries").status_code == 200
        bad_preferences = client.put(
            "/api/v1/insights/preferences", json={"planning_scenario_id": "missing", "command": "rm -rf /"},
            headers=mutation_headers(lee_csrf),
        )
        assert bad_preferences.status_code == 422
