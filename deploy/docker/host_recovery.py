"""Prepare and verify an approved Windows restart; never initiates a restart.

Preparation creates a verified synthetic backup and private pre-restart receipt.
Verification is read-only apart from saving its report. Original receipts remain
unchanged; no expected configuration or data drift is silently adopted.
"""
import argparse
import copy
import hashlib
import itertools
import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import manage
import mobile
import portable_backup as backup
import validate
import validate_portable_backup as recovery
import validate_scheduled_backup as scheduled


def boot_time():
    return scheduled.ps("(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')")


def task_xml():
    return scheduled.ps("Export-ScheduledTask -TaskName '" + scheduled.TASK + "' -TaskPath '\\'")


def assert_preserved(before, after):
    # Restarts necessarily change StartedAt. Every identity, configuration,
    # mount, port and previous running/stopped state must still match exactly.
    old, new = copy.deepcopy(before), copy.deepcopy(after)
    for snapshot in (old, new):
        for item in snapshot["containers"]:
            item.pop("started_at", None)
    if not manage.baseline_equal(old, new):
        raise ValueError("Container identity/configuration/state/mount/port or Serve drift; inspect before recovery")


def config_fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def reconcile_empty_dns(before, observed, inspected):
    """Permit empty DNS list/null serialization only with a complete old-hash match."""
    result = copy.deepcopy(observed)
    expected = {item["id"]: item for item in before["containers"]}
    raw = {item["Id"]: item for item in inspected}
    evidence = []
    for item in result["containers"]:
        if item["id"] not in expected:
            continue  # Strict identity/state comparison below will reject it.
        old_hash = expected[item["id"]]["configuration_sha256"]
        if item["configuration_sha256"] == old_hash:
            continue
        current = raw[item["id"]]
        value = [current["Config"], current["HostConfig"]]
        if config_fingerprint(value) != item["configuration_sha256"]:
            raise ValueError("Inspect changed during comparison; investigate before recovery")
        fields = [key for key in ("Dns", "DnsOptions", "DnsSearch") if value[1].get(key) == []]
        matched = None
        for count in range(1, len(fields) + 1):
            for group in itertools.combinations(fields, count):
                candidate = copy.deepcopy(value)
                for key in group:
                    candidate[1][key] = None
                if config_fingerprint(candidate) == old_hash:
                    matched = list(group)
                    break
            if matched:
                break
        if not matched:
            raise ValueError("Configuration drift is not empty-DNS serialization; original full hash did not match")
        evidence.append({"container": item["name"], "fields": matched,
                         "observed_sha256": item["configuration_sha256"],
                         "original_sha256": old_hash, "complete_original_hash_matched": True})
        item["configuration_sha256"] = old_hash  # In-memory projection only.
    assert_preserved(before, result)
    return result, evidence


def after_restart_receipt(mobile_receipt, prepared, observed):
    assert_preserved(prepared, observed)
    # The original pre-mobile receipt is retained. Only the in-memory comparison
    # ignores expected StartedAt changes, after strict independent validation.
    result = copy.deepcopy(mobile_receipt)
    current = {c["id"]: c for c in observed["containers"]}
    for item in result["preservation"]["containers"]:
        item["started_at"] = current[item["id"]]["started_at"]
    return result


def prepare():
    config_path = backup.ROOT / ".state/portable-backup-synthetic-20261023/config.json"
    config = backup.read_config(config_path)
    if not config.get("synthetic") or config["project"] != mobile.PROJECT:
        raise ValueError("Only the approved synthetic trial may be prepared")
    if scheduled.task_info(scheduled.TASK)["State"] == "Running":
        raise ValueError("Wait for the active backup job")
    receipt = json.loads((mobile.STATE / "receipt.json").read_text())
    mobile.verify(receipt)
    baseline = recovery.full_baseline()
    previous = validate.status(mobile.PROJECT)
    subprocess.run([sys.executable, str(backup.ROOT / "portable_backup.py"), "run",
                    "--config", str(config_path)], check=True, stdout=subprocess.DEVNULL)
    success = json.loads((config_path.parent / "last-run.json").read_text())
    if not backup.recent(success, 1):
        raise ValueError("Fresh verified backup required")
    if validate.status(mobile.PROJECT) != previous:
        raise ValueError("Application state changed during preparation; review and prepare again")
    assert_preserved(baseline, recovery.full_baseline())
    private = backup.ROOT / ".state" / ("host-recovery-" + uuid.uuid4().hex[:12])
    backup.media("private-create", private)
    prepared = {"format": 1, "prepared_at": datetime.now(UTC).isoformat(),
                "synthetic_only": True, "restart_approved": False,
                "boot_time": boot_time(), "baseline": baseline, "financial": previous,
                "mobile_receipt_sha256": backup.digest(mobile.STATE / "receipt.json"),
                "config_path": str(config_path), "config_sha256": backup.digest(config_path),
                "task_xml": task_xml(), "backup": success}
    backup.save_json(private / "receipt.json", prepared)
    backup.save_json(backup.ROOT / "reports/host-recovery-preparation.json",
                     {"status": "PREPARED_AWAITING_APPROVAL", "prepared_at": prepared["prepared_at"],
                      "receipt": str(private / "receipt.json"), "verified_backup": success["archive"],
                      "restart_executed": False, "windows_restart_recovery": "UNVERIFIED"})
    print("Prepared: fresh verified synthetic backup and protected service/state/Serve/task baseline.")
    print("No restart performed. Receipt: " + str(private / "receipt.json"))


def verify(path):
    path = Path(path).absolute()
    backup.media("private-check", path.parent)
    prepared = json.loads(path.read_text())
    if prepared.get("format") != 1 or prepared.get("synthetic_only") is not True:
        raise ValueError("Expected protected synthetic pre-restart receipt")
    if boot_time() == prepared["boot_time"]:
        raise ValueError("Windows has not restarted; cannot attest to restart recovery")
    age = datetime.now(UTC) - datetime.fromisoformat(prepared["prepared_at"])
    if not timedelta(0) <= age <= timedelta(days=2):
        raise ValueError("Pre-restart receipt is outside its two-day evidence window")
    config_path = Path(prepared["config_path"])
    if backup.digest(config_path) != prepared["config_sha256"]:
        raise ValueError("Backup configuration changed")
    config = backup.read_config(config_path)
    if not config.get("synthetic") or config["project"] != mobile.PROJECT:
        raise ValueError("Expected approved synthetic configuration")
    mobile_path = mobile.STATE / "receipt.json"
    if backup.digest(mobile_path) != prepared["mobile_receipt_sha256"]:
        raise ValueError("Mobile preparation receipt changed")
    if task_xml() != prepared["task_xml"]:
        raise ValueError("Registered backup task changed")
    observed = recovery.full_baseline()
    observed, normalization = reconcile_empty_dns(prepared["baseline"], observed, manage.inspect_all())
    temporary = after_restart_receipt(json.loads(mobile_path.read_text()), prepared["baseline"], observed)
    mobile.verify(temporary, reviewed_preservation=temporary["preservation"])
    current = validate.status(mobile.PROJECT)
    # Legitimate login can append audit/session records. Compare financial rows,
    # archives, migrations, user count and persistent signing-key fingerprint.
    expected = prepared["financial"]
    for field in ("financial_sha256", "archives", "migrations", "key"):
        if current[field] != expected[field]:
            raise ValueError("Application persistence mismatch")
    if current["counts"]["api_users"] != expected["counts"]["api_users"]:
        raise ValueError("Application user count changed")
    backup.check_media(config)
    archive = Path(config["directory"]) / prepared["backup"]["archive"]
    if backup.digest(archive) != prepared["backup"]["archive_sha256"]:
        raise ValueError("Pre-restart encrypted backup changed or is unavailable")
    checked = subprocess.run([sys.executable, str(backup.ROOT / "portable_backup.py"),
                              "status", "--config", str(config_path)], capture_output=True, check=False)
    status = json.loads(checked.stdout)
    if not status.get("backup_healthy") or checked.returncode not in (0, 1):
        raise ValueError("Backup is failed or stale; preserve evidence and recover before passing")
    attention = status.get("unacknowledged_failure", False)
    result = {"status": "PASS_WITH_BACKUP_ALERT" if attention else "PASS", "checked_at": datetime.now(UTC).isoformat(),
              "scope": "Windows restart observed; exact configuration, health, persistence, ports, Serve and media verified",
              "backup_status": status["status"], "task_info": scheduled.task_info(scheduled.TASK),
              "inspect_normalization": normalization,
              "unacknowledged_backup_failure": attention,
              "limits": ["Human must record whether login/manual Docker startup was needed",
                         "Does not attest to unattended, lock, sleep/resume, phone or LAN peer access",
                         "Fresh backup may cause login catch-up to skip by its 20-hour duplicate guard"]}
    backup.save_json(path.parent / "post-restart.json", result)
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify"))
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    manage.engine()
    if args.action == "prepare":
        prepare()
    elif args.receipt:
        verify(args.receipt)
    else:
        parser.error("verify requires the protected pre-restart --receipt")


if __name__ == "__main__":
    main()
