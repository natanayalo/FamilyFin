"""Validate the explicitly approved synthetic Windows task, preserving host data.

Creates one uniquely named, temporary time-trigger probe with the same approved
action. Removes that probe after testing. The approved daily task remains active.
No logoff/reboot, media disconnection, drive-setting change or Serve mutation.
"""
import argparse
import copy
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import manage
import mobile
import portable_backup as backup
import validate
import validate_portable_backup as recovery
from lab_profile import require_lab_python

require_lab_python()

TASK = "FamilyFin-M1-SyntheticBackup"


def ps(code):
    prefix = "$ErrorActionPreference='Stop';$env:PSModulePath=Join-Path $env:SystemRoot 'System32\\WindowsPowerShell\\v1.0\\Modules';"
    return backup.call(["powershell.exe", "-NoProfile", "-Command", prefix + code]).decode("utf-8-sig").strip()


def task_info(name):
    if not name.startswith(TASK) or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" for c in name):
        raise ValueError("Unexpected task identity")
    return json.loads(ps("$t=Get-ScheduledTask -TaskName '" + name + "' -TaskPath '\\';"
                        "$i=Get-ScheduledTaskInfo -TaskName '" + name + "' -TaskPath '\\';"
                        "[pscustomobject]@{State=[string]$t.State;LastTaskResult=[long]$i.LastTaskResult;LastRunUtc=$i.LastRunTime.ToUniversalTime().ToString('o');NextRunUtc=$(if($i.NextRunTime){$i.NextRunTime.ToUniversalTime().ToString('o')}else{$null})}|ConvertTo-Json -Compress"))


def wait_run(name, before, timeout=240):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = task_info(name)
        if current["LastRunUtc"] != before["LastRunUtc"] and current["State"] != "Running" and current["LastTaskResult"] != 267009:
            return current
        time.sleep(2)
    raise RuntimeError("Task did not finish within the bounded validation window")


def run_task(name):
    before = task_info(name)
    ps("Start-ScheduledTask -TaskName '" + name + "' -TaskPath '\\'")
    return wait_run(name, before)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    config_path = parser.parse_args().config
    config = backup.read_config(config_path)
    if not config.get("synthetic") or config["project"] != mobile.PROJECT:
        raise ValueError("Only the approved synthetic task may be exercised")
    registered = json.loads((config_path.parent / "registration.json").read_text(encoding="utf-8-sig"))
    assert registered["TaskName"] == TASK
    assert task_info(TASK)["State"] != "Running"
    assert backup.digest(config_path.parent / "proposed-daily-backup.xml") == registered["XmlSha256"]
    backup.source(config)
    mobile.verify(json.loads((mobile.STATE / "receipt.json").read_text()))
    baseline = recovery.full_baseline()
    original = copy.deepcopy(config)
    run_id = uuid.uuid4().hex[:12]
    private = config_path.parent / ("scheduled-validation-" + run_id)
    backup.media("private-create", private)
    backup.save_json(private / "original-config.json", original)
    backup.save_json(private / "original-last-run.json", json.loads((config_path.parent / "last-run.json").read_text()))
    report_dir = manage.REPORTS / ("scheduled-backup-" + run_id)
    report_dir.mkdir()
    results = []
    probe = TASK + "-TriggerTest-" + run_id
    probe_created = False
    project = "familyfin-m1-portable-recovery-scheduled-" + run_id
    stack_started = False

    def record(name, status="PASS", **evidence):
        results.append({"test": name, "status": status, **evidence})
        backup.save_json(report_dir / "validation.json", {"checked_at": datetime.now(UTC).isoformat(),
                         "synthetic_only": True, "task": TASK, "results": results})
        print(status + " " + name, flush=True)

    try:
        # Preserve the task's registered XML. Only the temporary probe is assigned
        # a one-time trigger; the permanent approved 03:00/logon schedule is untouched.
        xml = ps("Export-ScheduledTask -TaskName '" + TASK + "' -TaskPath '\\'")
        (private / "registered-daily-task.xml").write_text(xml, encoding="utf-16")
        old = json.loads((config_path.parent / "last-run.json").read_text())
        backup.save_json(config_path.parent / "last-run.json", {"status": "PASS",
                         "last_success_at": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
                         "test_note": "Intentional stale-state simulation; original receipt preserved"})
        # A real clock trigger proves the scheduled action executes without this
        # process invoking Start-ScheduledTask. Task registration is non-overwriting.
        ps("$s=New-Object -ComObject Schedule.Service;$s.Connect();$d=$s.NewTask(0);"
           "$d.XmlText=Export-ScheduledTask -TaskName '" + TASK + "' -TaskPath '\\';"
           "$d.Triggers.Clear();$trigger=$d.Triggers.Create(1);"
           "$trigger.StartBoundary=(Get-Date).AddSeconds(45).ToString('yyyy-MM-ddTHH:mm:ss');"
           "$trigger.EndBoundary=(Get-Date).AddMinutes(10).ToString('yyyy-MM-ddTHH:mm:ss');"
           "$trigger.Enabled=$true;$d.RegistrationInfo.Description='Disposable approved FamilyFin synthetic time-trigger validation';"
           "Register-ScheduledTask -TaskName '" + probe + "' -TaskPath '\\' -Xml $d.XmlText|Out-Null")
        probe_created = True
        initial = task_info(probe)
        print("Waiting for the actual one-time Windows trigger (about 45 seconds).", flush=True)
        completed = wait_run(probe, initial)
        assert completed["LastTaskResult"] == 0, "Scheduled backup process failed"
        success = json.loads((config_path.parent / "last-run.json").read_text())
        assert success["status"] == "PASS" and success["archive"] != old["archive"]
        archive = Path(config["directory"]) / success["archive"]
        assert backup.digest(archive) == success["archive_sha256"]
        record("actual clock-triggered task creates verified external encrypted snapshot",
               task_result=completed, archive=archive.name, sha256=success["archive_sha256"], stale_state="simulated; actual clock trigger executed")
        linux_image = "sha256:5ae6c16707d27c738f9b1b3c33e3ddd4a7c2f9fcf3ebc0e170a44a2a36819e25"
        staged = backup.stage(config, archive, linux_image=linux_image)
        expected = recovery.state(config, staged["volume"], snapshot=staged["snapshot"])
        restored = backup.restore_stage(config, staged, project)
        assert recovery.comparable(recovery.state(config, restored["financial_volume"])) == recovery.comparable(expected)
        manage.PROJECTS[project] = 8094
        # Mark before starting so partial startup is also cleaned up.
        stack_started = True
        manage.compose(project, "up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "180")
        manage.verify(project)
        current = validate.status(project)
        assert current["key"] != validate.status(mobile.PROJECT)["key"]
        assert current["counts"]["api_users"] == 2
        assert manage.request(8094, "/api/v1/auth/session")[0] == 401
        record("time-triggered snapshot decrypted in Linux and clean-restored",
               tables_archives_users_audit_migrations="equal before startup", health_and_migrations="PASS", signing_key="new; signed-out session denied")
        # A fresh successful receipt must suppress an on-demand duplicate while
        # still exercising the actual registered daily task action.
        duplicate = run_task(TASK)
        assert duplicate["LastTaskResult"] == 0
        assert json.loads((config_path.parent / "last-run.json").read_text()) == success
        record("registered daily task action suppresses an immediate duplicate", task_result=duplicate)
        # Deliberately choose a missing child in our new directory. Never unmount,
        # rename, disconnect or alter the physical drive or any existing file.
        bad = copy.deepcopy(original)
        missing = Path(config["directory"]) / ("deliberately-unavailable-test-" + run_id)
        assert not missing.exists()
        bad["directory"] = str(missing)
        archives_before = sorted(p.name for p in Path(config["directory"]).iterdir())
        backup.save_json(config_path, bad)
        print("Starting intentional unavailable-folder failure; a local warning may appear for up to 15 seconds.", flush=True)
        failed = run_task(TASK)
        assert failed["LastTaskResult"] != 0
        status = json.loads((config_path.parent / "last-run.json").read_text())
        assert status["status"] == "FAIL" and status["last_success_at"] == success["last_success_at"]
        assert sorted(p.name for p in Path(config["directory"]).iterdir()) == archives_before
        assert not missing.exists()
        alert_path = config_path.parent / "last-alert.json"
        alert = json.loads(alert_path.read_text(encoding="utf-8-sig")) if alert_path.exists() else {"Status": "MISSING"}
        record("registered task fails closed for unavailable folder with nonzero result",
               task_result=failed, private_status="FAIL; earlier success retained as history", no_new_archive_or_fallback=True)
        record("local failure popup dispatch", "PASS" if alert.get("Status") == "POPUP_RETURNED" else "FAIL", alert=alert)
        record("operator saw local failure popup", "PASS" if alert.get("Response") == 1 else "UNVERIFIED",
               reason="OK response observed" if alert.get("Response") == 1 else "Popup return alone does not certify human visibility; user confirmation pending")
        backup.save_json(config_path, original)
        recovered = run_task(TASK)
        assert recovered["LastTaskResult"] == 0
        fresh = json.loads((config_path.parent / "last-run.json").read_text())
        assert fresh["status"] == "PASS" and fresh["archive"] != success["archive"]
        assert backup.digest(Path(config["directory"]) / fresh["archive"]) == fresh["archive_sha256"]
        record("original configuration restored; registered task recovers to verified success",
               task_result=recovered, archive=fresh["archive"])
        record("actual future 03:00/logon catch-up and Windows reboot", "UNVERIFIED",
               reason="Time-trigger/action tested; future daily/logon events and a reboot were not executed")
    except BaseException as exc:
        record("scheduled validation failed; preserve evidence", "FAIL", failure_type=type(exc).__name__)
        raise
    finally:
        backup.save_json(config_path, original)
        if probe_created:
            if task_info(probe)["State"] == "Running":
                ps("Stop-ScheduledTask -TaskName '" + probe + "' -TaskPath '\\'")
            ps("Unregister-ScheduledTask -TaskName '" + probe + "' -TaskPath '\\' -Confirm:$false")
        if task_info(TASK)["State"] == "Running":
            ps("Stop-ScheduledTask -TaskName '" + TASK + "' -TaskPath '\\'")
        if stack_started:
            manage.assert_owned(project)
            manage.compose(project, "down", "--remove-orphans")
        assert manage.baseline_equal(baseline, recovery.full_baseline())
        assert json.loads(config_path.read_text()) == original
        mobile.verify(json.loads((mobile.STATE / "receipt.json").read_text()))
        record("all original Docker services, Serve, fixture and backup configuration preserved",
               daily_task="retained as approved", temporary_task_and_recovery_stack="removed; recovery data retained")
    print(json.dumps({"report": str(report_dir / "validation.json"), "PASS": sum(r["status"] == "PASS" for r in results),
                      "FAIL": sum(r["status"] == "FAIL" for r in results), "UNVERIFIED": sum(r["status"] == "UNVERIFIED" for r in results)}))


if __name__ == "__main__":
    main()
