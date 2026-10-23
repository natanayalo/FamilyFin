"""Portable age-encrypted backups. Stdlib host; plaintext stays in Linux volumes.

No scheduler registration, retention deletion, Serve mutation or drive-wide change.
Each archive is decrypted and application-verified before a success is recorded.
"""
import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

import manage

ROOT = Path(__file__).resolve().parent
STREAM = ROOT / "portable_stream.py"
HASHES = {
    "age.exe": "7622988f8cf6eddee87756a826f5690cf8106e555f91a5e56d4ab8303b0f586d",
    "age-keygen.exe": "9d00ea3f4d6f7ce913c11bd400245749e6661d935df83af0beffbf811383c88f",
}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def call(command, *, data=None):
    result = subprocess.run(command, input=data, capture_output=True, check=False)
    if result.returncode:
        # Child errors can contain archive paths or operational data. Keep them
        # out of notifications/task logs; preserve failure class in private status.
        raise RuntimeError("Backup subprocess failed")
    return result.stdout


def media(action, directory, config=None, **extra):
    command = ["powershell.exe", "-NoProfile", "-File", str(ROOT / "portable-media.ps1"),
               "-Action", action, "-Directory", str(directory)]
    if config:
        extra.update(ExpectedVolumeId=config["volume_id"], ExpectedDiskId=config["disk_id"],
                     Token=config["media_token"])
    for key, value in extra.items():
        command += ["-" + key, str(value)]
    output = call(command)
    return json.loads(output.decode("utf-8-sig")) if output.strip() else None


def read_config(path):
    path = Path(path).absolute()
    media("private-check", path.parent)
    if path.is_symlink() or path.is_junction():
        raise ValueError("Redirected configuration forbidden")
    config = json.loads(path.read_text(encoding="utf-8"))
    if (config["format"] != 1 or not re.fullmatch(r"familyfin-m1(?:-[a-z0-9-]+)?", config["project"])
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", config["image"])
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", config["container_image"])
            or not re.fullmatch(r"age1[0-9a-z]{58}", config["recipient"])):
        raise ValueError("Invalid reviewed backup configuration")
    return config


def tool(config, name="age.exe"):
    executable = Path(config["tools"]) / name
    if executable.is_symlink() or digest(executable) != HASHES[name]:
        raise ValueError("Pinned age tool hash mismatch")
    return str(executable)


def identity(config):
    key = Path(config["identity"])
    media("private-check", key.parent)
    media("identity-check", key, ExpectedDiskId=config["disk_id"])
    if key.is_symlink() or key.is_junction() or key.stat().st_size > 4096:
        raise ValueError("Invalid protected identity file")
    recipient = call([tool(config, "age-keygen.exe"), "-y", str(key)]).decode().strip()
    if recipient != config["recipient"]:
        raise ValueError("Recovery key does not match the configured recipient")
    return key


def check_media(config):
    result = media("check", config["directory"], config)
    if result["FreeBytes"] < 8 * 1024**3:
        raise ValueError("Backup media has less than the reserved 8 GiB free")
    return result


def docker(config, mounts, *, entrypoint="python", interactive=False):
    command = ["docker", "run", "--rm", "--pull", "never", "--network", "none",
               "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--user", "10001:10001", "--memory", "768m", "--cpus", "1",
               "--pids-limit", "128", "--log-driver", "none",
               "--tmpfs", "/tmp:size=128m,mode=1777,noexec,nosuid",
               "--env", "FAMILY_FINANCE_DATA_ROOT=/var/lib/familyfin",
               "--label", "familyfin.portable.owner=" + config["media_token"]]
    if interactive:
        command.append("-i")
    for volume, destination, readonly in mounts:
        command += ["--mount", f"type=volume,source={volume},target={destination}" + (",readonly" if readonly else "")]
    return command + ["--entrypoint", entrypoint, config["image"]]


def source(config):
    manage.engine()
    manage.assert_owned(config["project"])
    # Refuse absent volumes: docker run would otherwise silently create them.
    for suffix in ("financial", "backups"):
        volume = json.loads(call(["docker", "volume", "inspect", config["project"] + "_" + suffix]))[0]
        if (volume["Driver"] != "local" or volume.get("Options")
                or volume.get("Labels", {}).get("com.docker.compose.project") != config["project"]):
            raise ValueError("Source volume ownership/storage mismatch")
    image = json.loads(call(["docker", "image", "inspect", config["image"]]))[0]
    if image["Id"] != config["image"]:
        raise ValueError("Reviewed image identity mismatch")
    apis = [i for i in manage.inspect_all() if (i["Config"].get("Labels") or {}).get("com.docker.compose.project") == config["project"]
            and (i["Config"].get("Labels") or {}).get("com.docker.compose.service") == "api"
            and (i["Config"].get("Labels") or {}).get("com.docker.compose.oneoff", "False").lower() == "false"]
    if len(apis) != 1 or apis[0]["Image"] != config["container_image"]:
        raise ValueError("Source release changed; review and reconfigure backups")
    if config.get("synthetic"):
        import mobile
        if config["project"] == mobile.PROJECT:
            mobile.fixture()
        else:
            item = json.loads(call(["docker", "volume", "inspect", config["project"] + "_financial"]))[0]
            labels = item.get("Labels") or {}
            if (not re.fullmatch(r"familyfin-m1-portable-recovery-[a-z0-9-]+", config["project"])
                    or labels.get("familyfin.portable.owner") != config["media_token"]
                    or labels.get("familyfin.portable.synthetic") != "true"):
                raise ValueError("Not an owned synthetic recovery drill source")


def stream_command(config, volume, action, *, token=None, snapshot=None):
    if action != "pack":
        item = json.loads(call(["docker", "volume", "inspect", volume]))[0]
        labels = item.get("Labels") or {}
        if (not re.fullmatch(r"familyfin-m1-portable-stage-[0-9a-f]{32}", volume)
                or labels.get("familyfin.portable.owner") != config["media_token"]
                or labels.get("familyfin.portable.purpose") != "authenticated-staging"):
            raise ValueError("Not an owned disposable staging volume")
    command = docker(config, [(volume, "/backups", action == "pack")], interactive=action == "unpack")
    command += ["-c", STREAM.read_text(encoding="utf-8"), action, "--image", config["image"]]
    if token:
        command += ["--token", token]
    if snapshot:
        command += ["--snapshot", snapshot]
    return command


def encrypt(config, snapshot, target):
    # Exclusive creation; age never gets an output filename it could overwrite.
    with Path(target).open("xb") as output:
        producer = subprocess.Popen(stream_command(config, config["project"] + "_backups", "pack", snapshot=snapshot), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            consumer = subprocess.Popen([tool(config), "-r", config["recipient"]], stdin=producer.stdout, stdout=output, stderr=subprocess.DEVNULL)
            producer.stdout.close()
            try:
                consumer_code = consumer.wait(timeout=3600)
                producer_code = producer.wait(timeout=30)
            except BaseException:
                consumer.kill()
                consumer.wait()
                raise
            if producer_code or consumer_code:
                raise RuntimeError("Encrypted export failed; incomplete output retained")
            output.flush()
            os.fsync(output.fileno())
        finally:
            if producer.poll() is None:
                producer.kill()
                producer.wait()


def new_stage(config):
    name = "familyfin-m1-portable-stage-" + uuid.uuid4().hex
    call(["docker", "volume", "create", "--label", "familyfin.portable.owner=" + config["media_token"],
          "--label", "familyfin.portable.purpose=authenticated-staging", name])
    return name, uuid.uuid4().hex


def stage(config, archive, *, key=None, linux_image=None):
    archive = Path(archive).absolute()
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size > 65 * 1024**3:
        raise ValueError("Invalid encrypted archive")
    # Default verification key is local; recovery can explicitly use an independently
    # copied identity. No DPAPI call or Windows-profile secret exists in this format.
    key = Path(key) if key else identity(config)
    media("private-check", key.parent)
    media("identity-check", key, ExpectedDiskId=config["disk_id"])
    if key.is_symlink() or key.is_junction() or key.stat().st_size > 4096:
        raise ValueError("Identity exceeds size limit")
    volume, token = new_stage(config)
    if linux_image:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", linux_image):
            raise ValueError("Exact Linux age image identity required")
        command = ["docker", "run", "--rm", "--pull", "never", "-i", "--network", "none", "--read-only",
                   "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "10004:10004",
                   "--memory", "128m", "--cpus", "1", "--pids-limit", "32", "--log-driver", "none",
                   "--mount", f"type=bind,source={archive.parent},target=/encrypted,readonly",
                   linux_image, "-d", "-i", "-", "/encrypted/" + archive.name]
    else:
        command = [tool(config), "-d", "-i", str(key), str(archive)]
    decryptor = subprocess.Popen(command, stdin=subprocess.PIPE if linux_image else subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    receiver = None
    try:
        if linux_image:
            decryptor.stdin.write(key.read_bytes())
            decryptor.stdin.close()
        receiver = subprocess.Popen(stream_command(config, volume, "unpack", token=token),
                                    stdin=decryptor.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        decryptor.stdout.close()
        receiver_code = receiver.wait(timeout=3600)
        decryptor_code = decryptor.wait(timeout=30)
        if receiver_code or decryptor_code:
            raise RuntimeError("Decryption/authentication failed; staging remains incomplete")
        result = json.loads(call(stream_command(config, volume, "finalize", token=token)))
        return {"volume": volume, "token": token, "snapshot": result["snapshot"], "image": result["image"]}
    finally:
        for child in (receiver, decryptor):
            if child is not None and child.poll() is None:
                child.kill()
                child.wait()


def restore_stage(config, staged, project):
    if not re.fullmatch(r"familyfin-m1-portable-recovery-[a-z0-9-]+", project):
        raise ValueError("Use a separate explicitly named portable recovery project")
    call(stream_command(config, staged["volume"], "require-verified", token=staged["token"]))
    volume = project + "_financial"
    existing = subprocess.run(["docker", "volume", "inspect", volume], capture_output=True, check=False)
    if existing.returncode == 0:
        raise ValueError("Restore target already exists; refusing to reuse it")
    call(["docker", "volume", "create", "--label", "com.docker.compose.project=" + project,
          "--label", "com.docker.compose.volume=financial", "--label", "familyfin.portable.owner=" + config["media_token"],
          "--label", "familyfin.portable.synthetic=" + str(bool(config.get("synthetic"))).lower(), volume])
    result = call(docker(config, [(volume, "/var/lib/familyfin", False), (staged["volume"], "/backups", True)])
                  + ["/app/deploy/docker/operations.py", "restore", staged["snapshot"]])
    if b"reauthentication required" not in result:
        raise RuntimeError("Restore audit confirmation missing")
    return {"project": project, "financial_volume": volume, "status": "RESTORED_AND_AUDITED_REAUTH_REQUIRED"}


def remove_stage(config, staged):
    # Only this exact labelled disposable volume may be removed, after verification
    # and after every container has released it. Never touches source/recovery data.
    call(stream_command(config, staged["volume"], "require-verified", token=staged["token"]))
    users = call(["docker", "ps", "--all", "--quiet", "--filter", "volume=" + staged["volume"]])
    if users.strip():
        raise ValueError("Staging volume is still in use")
    call(["docker", "volume", "rm", staged["volume"]])


@contextmanager
def lock(path):
    # OS lock is released on process death; an interrupted job cannot leave a
    # stale lock blocking all future scheduled backups.
    import msvcrt
    with Path(path).open("a+b") as handle:
        # Reading a byte held by another Windows process itself raises before
        # locking. Inspect file length without reading the locked region.
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError("Another backup job holds the lock") from exc
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def save_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".next-" + uuid.uuid4().hex)
    with temporary.open("x", encoding="utf-8") as output:
        json.dump(value, output, indent=2)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def recent(status, hours=20, now=None):
    if status.get("status") != "PASS" or not status.get("last_success_at"):
        return False
    stamp = datetime.fromisoformat(status["last_success_at"])
    now = now or datetime.now(UTC)
    return stamp <= now and now - stamp < timedelta(hours=hours)


def recovery_readiness(config, receipt, *, verify_integrity=False):
    """Read-only, current availability checks; never change a success receipt.

    Free-space requirements apply to new exports, not reading existing archives.
    A quick status checks presence, not ciphertext integrity or a full restore.
    """
    result = {"media_identity_valid": False, "archive_available": False,
              "recovery_key_available": False, "archive_integrity_verified": None,
              "integrity_check_requested": verify_integrity}
    failures = {}
    try:
        media("check", config["directory"], config)
        result["media_identity_valid"] = True
    except Exception as exc:  # noqa: BLE001 -- Any probe error makes readiness unavailable.
        failures["media"] = type(exc).__name__
    if result["media_identity_valid"]:
        try:
            name = receipt.get("archive", "")
            if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-familyfin-[0-9a-f]{32}\.tar\.age", name):
                raise ValueError("Invalid saved archive name")
            archive = Path(config["directory"]) / name
            info = archive.lstat()
            if (archive.is_symlink() or archive.is_junction() or not stat.S_ISREG(info.st_mode)
                    or not 0 < info.st_size <= 65 * 1024**3):
                raise ValueError("Invalid encrypted archive")
            # Opening also catches access failures without reading the whole file.
            with archive.open("rb") as source:
                if not source.read(1):
                    raise ValueError("Empty encrypted archive")
            result["archive_available"] = True
            if verify_integrity:
                expected = receipt.get("archive_sha256", "")
                if not re.fullmatch(r"[0-9a-f]{64}", expected) or digest(archive) != expected:
                    raise ValueError("Encrypted archive hash mismatch")
                result["archive_integrity_verified"] = True
        except Exception as exc:  # noqa: BLE001 -- Preserve structured, fail-closed status.
            if verify_integrity:
                result["archive_integrity_verified"] = False
            failures["archive"] = type(exc).__name__
    try:
        identity(config)  # Private ACLs, independent disk, pinned tools, recipient.
        result["recovery_key_available"] = True
    except Exception as exc:  # noqa: BLE001 -- Never expose key/tool failure details.
        failures["recovery_key"] = type(exc).__name__
    result["recovery_media_available"] = result["media_identity_valid"] and result["archive_available"]
    result["recovery_ready"] = (result["recovery_media_available"] and result["recovery_key_available"]
                                and (not verify_integrity or result["archive_integrity_verified"] is True))
    result["failures"] = failures  # Classes only; no key contents or child/path errors.
    return result


def read_alert(state):
    path = state / "backup-alert.json"
    if not path.exists():
        return None
    alert = json.loads(path.read_text(encoding="utf-8"))
    if (alert.get("status") not in ("UNACKNOWLEDGED", "ACKNOWLEDGED")
            or not re.fullmatch(r"[0-9a-f]{32}", alert.get("id", ""))
            or not isinstance(alert.get("failure_count"), int) or alert["failure_count"] < 1
            or not alert.get("first_failure_at") or not alert.get("last_failure_at")):
        raise ValueError("Invalid persistent alert; preserve it and inspect backup history")
    return alert


def record_alert(state, failure):
    previous = read_alert(state) or {}
    unresolved = previous.get("status") == "UNACKNOWLEDGED"
    alert = {"status": "UNACKNOWLEDGED", "id": uuid.uuid4().hex,
             "first_failure_at": previous["first_failure_at"] if unresolved else failure["checked_at"],
             "last_failure_at": failure["checked_at"],
             "failure_count": previous["failure_count"] + 1 if unresolved else 1,
             "failure_type": failure["failure_type"],
             "action": "Review backup history and current status, then explicitly acknowledge this alert ID."}
    # A successful retry must never silently dismiss a missed failure warning.
    save_json(state / "backup-alert.json", alert)
    with (state / "alert-history.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(alert) + "\n")
    return alert


def acknowledge_alert(state, alert_id):
    if not alert_id or not re.fullmatch(r"[0-9a-f]{32}", alert_id):
        raise ValueError("Select the exact alert ID shown by status")
    with lock(state / "backup.lock"):
        alert = read_alert(state)
        if not alert or alert["id"] != alert_id or alert["status"] != "UNACKNOWLEDGED":
            raise ValueError("Alert changed or was already acknowledged; inspect status again")
        alert = alert | {"status": "ACKNOWLEDGED", "acknowledged_at": datetime.now(UTC).isoformat()}
        save_json(state / "backup-alert.json", alert)
        with (state / "alert-history.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(alert) + "\n")
    return alert


def backup(config, state):
    check_media(config)  # Must precede snapshot creation or any external write.
    identity(config)
    source(config)
    financial = config["project"] + "_financial"
    backups = config["project"] + "_backups"
    output = call(docker(config, [(financial, "/var/lib/familyfin", False), (backups, "/backups", False)])
                  + ["/app/deploy/docker/operations.py", "backup"])
    snapshot = output.decode().strip().splitlines()[-1]
    if not re.fullmatch(r"familyfin-[0-9a-f]{32}", snapshot):
        raise ValueError("Invalid snapshot identity")
    check_media(config)  # Recheck immediately before writing to the selected drive.
    target = Path(config["directory"]) / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + snapshot + ".tar.age")
    temporary = target.with_name(target.name + ".partial")
    encrypt(config, snapshot, temporary)
    staged = stage(config, temporary)
    check_media(config)
    if target.exists():
        raise ValueError("Archive name collision; refusing overwrite")
    temporary.rename(target)  # Windows rename refuses an existing destination.
    remove_stage(config, staged)
    receipt = {"status": "PASS", "last_success_at": datetime.now(UTC).isoformat(),
               "archive": target.name, "archive_sha256": digest(target), "snapshot": snapshot,
               "image": config["image"], "verification_staging_removed": True,
               "verification": "age authenticated decryption and full application manifest/schema/invariant audit",
               "synthetic": config.get("synthetic", False)}
    with target.with_name(target.name + ".receipt.json").open("x", encoding="utf-8") as output:
        json.dump({key: value for key, value in receipt.items() if key != "staged_verification"}, output, indent=2)
    return receipt


def schedule_xml(config_path, sid, start, end=None):
    if not re.fullmatch(r"S-1-[0-9-]+", sid) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", start):
        raise ValueError("Explicit SID and local start timestamp required")
    if end and (not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", end) or end <= start):
        raise ValueError("End timestamp must be after the start")
    boundary = "<EndBoundary>" + end + "</EndBoundary>" if end else ""
    args = subprocess.list2cmdline(["-NoProfile", "-WindowStyle", "Hidden", "-File", str(ROOT / "portable-task.ps1"),
                                   "-Python", sys.executable, "-Config", str(Path(config_path).absolute())])
    return f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
<RegistrationInfo><Description>FamilyFin encrypted application backup; reviewed synthetic configuration. Existing external files are never pruned.</Description></RegistrationInfo>
<Triggers><CalendarTrigger><StartBoundary>{start}</StartBoundary>{boundary}<Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger><LogonTrigger>{boundary}<Enabled>true</Enabled><UserId>{sid}</UserId></LogonTrigger></Triggers>
<Principals><Principal id="Operator"><UserId>{sid}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable><ExecutionTimeLimit>PT1H</ExecutionTimeLimit><Enabled>true</Enabled><RestartOnFailure><Interval>PT30M</Interval><Count>3</Count></RestartOnFailure></Settings>
<Actions Context="Operator"><Exec><Command>{escape(str(Path(os.environ.get('SystemRoot','C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'))}</Command><Arguments>{escape(args)}</Arguments><WorkingDirectory>{escape(str(ROOT.parents[1]))}</WorkingDirectory></Exec></Actions>
</Task>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "status", "acknowledge-alert", "stage", "restore", "schedule"))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--if-due", action="store_true")
    parser.add_argument("--wait-ready", action="store_true", help="Wait at most five minutes for local Docker and the reviewed API")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--key", type=Path)
    parser.add_argument("--linux-age-image")
    parser.add_argument("--staged", type=Path)
    parser.add_argument("--project")
    parser.add_argument("--sid")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--alert-id")
    parser.add_argument("--verify-integrity", action="store_true",
                        help="For status, hash the encrypted archive against its saved SHA-256")
    args = parser.parse_args()
    if args.verify_integrity and args.action != "status":
        parser.error("--verify-integrity requires status")
    config = read_config(args.config)
    state = args.config.parent
    status_path = state / "last-run.json"
    if args.action == "status":
        previous = json.loads(status_path.read_text()) if status_path.exists() else {}
        alert = read_alert(state)
        successful = previous.get("status") == "PASS" and bool(previous.get("last_success_at"))
        fresh = recent(previous, 26)
        readiness = recovery_readiness(config, previous, verify_integrity=args.verify_integrity)
        healthy = fresh and readiness["recovery_ready"]
        attention = bool(alert and alert["status"] == "UNACKNOWLEDGED")
        result = ("FAIL_OR_STALE" if not fresh else "RECOVERY_UNAVAILABLE" if not healthy
                  else "ATTENTION_REQUIRED" if attention else "PASS")
        print(json.dumps({"status": result, "backup_healthy": healthy,
                          "last_backup_successful": successful, "last_backup_recent": fresh,
                          **readiness,
                          "unacknowledged_failure": attention, "alert": alert, "last_run": previous}))
        return 0 if healthy and not attention else 1
    if args.action == "acknowledge-alert":
        alert = acknowledge_alert(state, args.alert_id)
        print(json.dumps({"status": alert["status"], "alert_id": alert["id"], "backup_health_unchanged": True}))
        return 0
    if args.action == "schedule":
        if config.get("synthetic") and not args.end:
            raise ValueError("Synthetic trial schedule requires an explicit end timestamp")
        target = state / "proposed-daily-backup.xml"
        with target.open("x", encoding="utf-16") as output:
            output.write(schedule_xml(args.config, args.sid, args.start, args.end))
        print("Prepared only; no scheduled task registered. Interactive logon required; StartWhenAvailable plus logon trigger catch up missed runs.")
        return 0
    if args.action == "stage":
        manage.engine()
        if not args.archive:
            raise ValueError("Select an encrypted archive explicitly")
        result = stage(config, args.archive, key=args.key, linux_image=args.linux_age_image)
        save_json(state / ("staged-" + uuid.uuid4().hex + ".json"), result)
        print(json.dumps(result))
        return 0
    if args.action == "restore":
        manage.engine()
        if not args.staged or not args.project:
            raise ValueError("Select verified staging receipt and a new recovery project")
        print(json.dumps(restore_stage(config, json.loads(args.staged.read_text()), args.project)))
        return 0
    with lock(state / "backup.lock"):
        prior = json.loads(status_path.read_text()) if status_path.exists() else {}
        try:
            if args.wait_ready:
                import backup_readiness
                save_json(status_path, {"status": "RUNNING", "phase": "WAITING_FOR_DOCKER_API",
                                       "started_at": datetime.now(UTC).isoformat(),
                                       "last_success_at": prior.get("last_success_at")})
                try:
                    ready = backup_readiness.wait_ready(config)
                    save_json(state / "last-readiness.json", ready | {"checked_at": datetime.now(UTC).isoformat()})
                except Exception as exc:
                    save_json(state / "last-readiness.json", {"status": "FAIL", "failure_type": type(exc).__name__,
                                                             "checked_at": datetime.now(UTC).isoformat()})
                    raise
            manage.engine()
            if args.if_due and recent(prior):
                check_media(config)
                # A recent receipt permits skipping only while its archive and
                # matching recovery key are still available. Failure goes through
                # the normal persisted-alert path, never a successful skip.
                if not recovery_readiness(config, prior)["recovery_ready"]:
                    raise RuntimeError("Recent backup recovery unavailable; refusing to skip")
                if args.wait_ready:
                    save_json(status_path, prior)
                print("Recent successful backup; no new snapshot needed")
                return 0
            save_json(status_path, {"status": "RUNNING", "started_at": datetime.now(UTC).isoformat(),
                                   "last_success_at": prior.get("last_success_at")})
            result = backup(config, state)
            save_json(status_path, result)
            with (state / "history.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps({k: v for k, v in result.items() if k != "staged_verification"}) + "\n")
            print(json.dumps({k: v for k, v in result.items() if k != "staged_verification"}))
            return 0
        except Exception as exc:  # noqa: BLE001 -- Every backup failure must persist an alert.
            failure = {"status": "FAIL", "checked_at": datetime.now(UTC).isoformat(),
                      "failure_type": type(exc).__name__, "last_success_at": prior.get("last_success_at"),
                      "action": "Check backup media/key/Docker; preserve partial archives and staging. No fallback or pruning."}
            record_alert(state, failure)
            save_json(status_path, failure)
            with (state / "history.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps(failure) + "\n")
            print("Backup FAILED; inspect protected last-run.json. No success or fallback was recorded.", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
