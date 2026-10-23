"""Exercise persistent alerts with an isolated synthetic configuration.

No scheduler/popup, live config/status, Serve or drive-setting changes. A single
verified synthetic encrypted backup is added to the already approved directory.
"""
import argparse
import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import manage
import mobile
import portable_backup as backup
import validate_portable_backup as recovery
import validate_scheduled_backup as scheduled
from lab_profile import require_lab_python

require_lab_python()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    live = parser.parse_args().config
    config = backup.read_config(live)
    if not config.get("synthetic") or config["project"] != mobile.PROJECT:
        raise ValueError("Only the existing synthetic configuration is allowed")
    if scheduled.task_info(scheduled.TASK)["State"] == "Running":
        raise ValueError("Wait for the active backup job")
    receipt = json.loads((mobile.STATE / "receipt.json").read_text())
    mobile.verify(receipt)
    backup.check_media(config)
    baseline = recovery.full_baseline()
    live_files = {p.name: backup.digest(p) for p in live.parent.iterdir() if p.is_file()}
    task_xml = scheduled.ps("Export-ScheduledTask -TaskName '" + scheduled.TASK + "' -TaskPath '\\'")
    external = Path(config["directory"])
    existing = {p.name: backup.digest(p) for p in external.iterdir() if p.is_file()}
    run_id = uuid.uuid4().hex[:12]
    private = live.parent / ("alert-validation-" + run_id)
    backup.media("private-create", private)
    report = manage.REPORTS / ("backup-alerts-" + run_id + ".json")
    results = []

    def record(name, status="PASS", **evidence):
        results.append({"test": name, "status": status, **evidence})
        backup.save_json(report, {"checked_at": datetime.now(UTC).isoformat(),
                                 "synthetic_only": True, "results": results})
        print(status + " " + name, flush=True)

    def cli(action, expected, *extra):
        result = subprocess.run([sys.executable, str(backup.ROOT / "portable_backup.py"), action,
                                 "--config", str(private / "config.json"), *extra], capture_output=True)
        if result.returncode != expected:
            raise AssertionError("Unexpected backup command result")
        return json.loads(result.stdout) if result.stdout.strip().startswith(b"{") else None

    try:
        missing = external / ("deliberately-unavailable-alert-test-" + run_id)
        assert not missing.exists()
        backup.save_json(private / "config.json", config | {"directory": str(missing)})
        cli("run", 1, "--if-due")
        failed = cli("status", 1)
        assert failed["status"] == "FAIL_OR_STALE" and failed["unacknowledged_failure"]
        alert_id = failed["alert"]["id"]
        assert not missing.exists()
        assert {p.name: backup.digest(p) for p in external.iterdir() if p.is_file()} == existing
        record("missing-folder failure creates durable warning without archive, popup or fallback")
        backup.save_json(private / "config.json", config)
        success = cli("run", 0)
        assert success["status"] == "PASS"
        assert backup.digest(external / success["archive"]) == success["archive_sha256"]
        attention = cli("status", 1)
        assert attention["status"] == "ATTENTION_REQUIRED" and attention["backup_healthy"]
        assert attention["alert"]["id"] == alert_id
        record("real verified encrypted backup recovers; missed failure warning persists",
               archive=success["archive"], sha256=success["archive_sha256"])
        cli("acknowledge-alert", 1, "--alert-id", "0" * 32)
        assert cli("status", 1)["unacknowledged_failure"]
        cli("acknowledge-alert", 0, "--alert-id", alert_id)
        assert cli("status", 0)["status"] == "PASS"
        assert json.loads((private / "last-run.json").read_text()) == success
        record("wrong acknowledgement refused; reviewed test alert acknowledged without changing backup health")
        record("human visibility and unattended delivery", "UNVERIFIED",
               reason="Persistent local state/status tested; no popup or unattended delivery test requested")
    except BaseException as exc:
        record("alert validation failed; evidence retained", "FAIL", failure_type=type(exc).__name__)
        raise
    finally:
        assert manage.baseline_equal(baseline, recovery.full_baseline())
        assert {p.name: backup.digest(p) for p in live.parent.iterdir() if p.is_file()} == live_files
        assert task_xml == scheduled.ps("Export-ScheduledTask -TaskName '" + scheduled.TASK + "' -TaskPath '\\'")
        for name, digest in existing.items():
            assert backup.digest(external / name) == digest
        added = {p.name for p in external.iterdir() if p.is_file()} - existing.keys()
        assert all(name.endswith((".tar.age", ".tar.age.receipt.json", ".tar.age.partial")) for name in added)
        mobile.verify(receipt)
        record("live backup config/status/task, all services, Serve and existing archives preserved")
    print(json.dumps({"report": str(report), "PASS": sum(r["status"] == "PASS" for r in results),
                      "FAIL": sum(r["status"] == "FAIL" for r in results),
                      "UNVERIFIED": sum(r["status"] == "UNVERIFIED" for r in results)}))


if __name__ == "__main__":
    main()
