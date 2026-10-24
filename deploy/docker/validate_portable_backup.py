"""Synthetic-only external encrypted recovery drill; preserves the live phone trial.

Two temporary, loopback-only recovery stacks prove point-in-time state and old
session rejection without reading/resetting the phone users' chosen passwords.
"""
import argparse
import copy
import json
import secrets
import socket
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import manage
import mobile
import portable_backup as backup
import validate

STATE_CODE = '''
import hashlib,json,sqlite3,sys
from pathlib import Path
root=Path(sys.argv[1])
with sqlite3.connect('file:'+str(root/'family_finance.sqlite3')+'?mode=ro&immutable=1',uri=True) as db:
 tables=sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'"))
 hashes={}
 counts={}
 for table in tables:
  if table.startswith('sqlite_'): continue
  cols=[r[1] for r in db.execute('PRAGMA table_info("'+table+'")') if r[1] not in ('archived_path','managed_path')]
  rows=db.execute('SELECT '+','.join('"'+c+'"' for c in cols)+' FROM "'+table+'"').fetchall()
  counts[table]=len(rows)
  hashes[table]=hashlib.sha256(json.dumps(sorted(rows,key=repr),sort_keys=True,default=str).encode()).hexdigest()
 archives={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('imports','planning-imports','net-worth-imports','automation') for p in (root/folder).rglob('*') if p.is_file()}
key=root/'api-secret.key'
print(json.dumps({'tables':hashes,'counts':counts,'archives':archives,'key_present':key.exists(),'key_sha256':hashlib.sha256(key.read_bytes()).hexdigest() if key.exists() else None}))
'''


def full_baseline():
    projects = manage.PROJECTS
    try:
        manage.PROJECTS = {}
        return manage.baseline()
    finally:
        manage.PROJECTS = projects


def state(config, volume, *, snapshot=None):
    destination = "/backups" if snapshot else "/var/lib/familyfin"
    root = destination + ("/" + snapshot if snapshot else "")
    return json.loads(backup.call(backup.docker(config, [(volume, destination, True)]) + ["-c", STATE_CODE, root]))


def comparable(value):
    return {k: v for k, v in value.items() if not k.startswith("key_")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--linux-age-image", required=True)
    args = parser.parse_args()
    config = backup.read_config(args.config)
    if not config.get("synthetic") or config["project"] != mobile.PROJECT:
        raise ValueError("Only the approved original synthetic fixture may seed this drill")
    backup.source(config)
    mobile.fixture()
    before = full_baseline()
    run_id = uuid.uuid4().hex[:12]
    report_dir = manage.REPORTS / ("portable-backup-" + run_id)
    report_dir.mkdir()
    results = []
    projects = ["familyfin-m1-portable-recovery-seed-" + run_id,
                "familyfin-m1-portable-recovery-final-" + run_id]
    active = []

    def record(name, status="PASS", **evidence):
        results.append({"test": name, "status": status, **evidence})
        backup.save_json(report_dir / "validation.json", {"checked_at": datetime.now(UTC).isoformat(),
                         "synthetic_only": True, "results": results})
        print(status + " " + name, flush=True)

    def start(project, port):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
        manage.PROJECTS[project] = port
        for service, image in json.loads((mobile.REPORT / "reviewed-images.json").read_text()).items():
            actual = json.loads(backup.call(["docker", "image", "inspect", "familyfin-m1-" + service + ":local"]))[0]["Id"]
            assert actual == image
        active.append(project)
        manage.compose(project, "up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "180")
        manage.verify(project)
        # Runtime-only Compose startup doesn't instantiate the operations-profile
        # backup volume. Create this explicitly for our fresh owned drill project;
        # the backup implementation itself must keep refusing missing source media.
        name = project + "_backups"
        absent = subprocess.run(["docker", "volume", "inspect", name], capture_output=True)
        if absent.returncode == 0:
            raise ValueError("Fresh recovery backup volume unexpectedly exists")
        backup.call(["docker", "volume", "create", "--label", "com.docker.compose.project=" + project,
                     "--label", "com.docker.compose.volume=backups", name])

    def reset_copy(project, passwords):
        validate.execute(project, '''
import json,sys
from family_finance.api.auth import AuthService
from family_finance.persistence.db import Database
from family_finance.config import Settings
s=Settings.from_environment();auth=AuthService(Database(s.database_path),s)
for name,password in zip(('qa-one','qa-two'),json.load(sys.stdin),strict=True):
 auth.reset_password(username=name,password=password)
''', passwords)

    try:
        first = backup.backup(config, args.config.parent)
        record("external encrypted export, authenticated decrypt and application verification", archive=first["archive"], sha256=first["archive_sha256"])
        # Separate protected identity copy + Linux age binary; no DPAPI or original
        # Windows profile is used by the recovery decryptor.
        recovery_keys = args.config.parent / ("recovery-key-drill-" + run_id)
        backup.media("private-create", recovery_keys)
        copied_key = recovery_keys / "copied-disposable-identity.txt"
        with copied_key.open("xb") as output:
            output.write(Path(config["identity"]).read_bytes())
        staged = backup.stage(config, Path(config["directory"]) / first["archive"], key=copied_key, linux_image=args.linux_age_image)
        expected = state(config, staged["volume"], snapshot=staged["snapshot"])
        assert not expected["key_present"] and expected["counts"]["api_users"] == 2
        recovery = backup.restore_stage(config, staged, projects[0])
        assert comparable(state(config, recovery["financial_volume"])) == comparable(expected)
        record("Linux decryption with independent key copy and clean restore", image=args.linux_age_image,
               all_table_hashes_archives_users_audit_migrations="equal", old_signing_key="absent")
        start(projects[0], 8094)
        passwords = [secrets.token_urlsafe(32), secrets.token_urlsafe(32)]
        reset_copy(projects[0], passwords)
        old_sessions = [validate.login(projects[0], user, password)
                        for user, password in zip(("qa-one", "qa-two"), passwords, strict=True)]
        assert all(manage.request(8094, "/api/v1/auth/session", cookie=cookie)[0] == 200 for cookie, _ in old_sessions)
        clone = copy.deepcopy(config)
        clone["project"] = projects[0]
        clone_archive = backup.backup(clone, args.config.parent)
        staged2 = backup.stage(clone, Path(clone["directory"]) / clone_archive["archive"], key=copied_key, linux_image=args.linux_age_image)
        expected2 = state(clone, staged2["volume"], snapshot=staged2["snapshot"])
        restored = backup.restore_stage(clone, staged2, projects[1])
        assert comparable(state(clone, restored["financial_volume"])) == comparable(expected2)
        start(projects[1], 8095)
        source_key = validate.status(projects[0])["key"]
        restored_state = validate.status(projects[1])
        assert restored_state["key"] != source_key
        assert all(manage.request(8095, "/api/v1/auth/session", cookie=cookie)[0] == 401 for cookie, _ in old_sessions)
        for user, password in zip(("qa-one", "qa-two"), passwords, strict=True):
            cookie, csrf = validate.login(projects[1], user, password)
            assert manage.request(8095, "/api/v1/net-worth/accounts", cookie=cookie)[0] == 200
            assert manage.request(8095, "/api/v1/auth/session", "DELETE", cookie=cookie, csrf=csrf)[0] == 204
            assert manage.request(8095, "/api/v1/auth/session", cookie=cookie)[0] == 401
        record("restored sessions rejected; both users reauthenticate and logout", password_changes="only isolated restored seed copy; phone credentials untouched", signing_key="new", audits_users_schema="verified before login mutations")
        # Existing target must be refused without changing it.
        unchanged = validate.status(projects[1])
        try:
            backup.restore_stage(clone, staged2, projects[1])
        except ValueError:
            pass
        else:
            raise AssertionError("Existing restore volume was reused")
        assert validate.status(projects[1]) == unchanged
        record("existing restore target refused and preserved")
        # Negative recovery inputs are new ciphertext-only files in our new folder.
        wrong_key = recovery_keys / "wrong-disposable-identity.txt"
        backup.call([backup.tool(config, "age-keygen.exe"), "-o", str(wrong_key)])
        source_archive = Path(config["directory"]) / first["archive"]
        payload = source_archive.read_bytes()
        for kind in ("wrong-key", "corrupt", "truncated"):
            path = Path(config["directory"]) / ("fault-" + run_id + "-" + kind + ".tar.age")
            data = bytearray(payload)
            if kind == "corrupt": data[-40] ^= 1
            if kind == "truncated": del data[-20:]
            with path.open("xb") as output: output.write(data)
            try:
                backup.stage(config, path, key=wrong_key if kind == "wrong-key" else copied_key)
            except RuntimeError:
                pass
            else:
                raise AssertionError("Invalid recovery input was accepted")
            record(kind + " fails authentication; no usable recovery returned")
        partial = Path(config["directory"]) / ("interrupted-" + run_id + ".tar.age.partial")
        # A producer failure must remain .partial even if age successfully encrypts
        # the bytes it received. This models interruption without host shutdown.
        failing = backup.docker(config, []) + ["-c", "import sys;sys.stdout.buffer.write(b'test');sys.stdout.flush();sys.exit(17)"]
        with patch.object(backup, "stream_command", return_value=failing):
            try: backup.encrypt(config, first["snapshot"], partial)
            except RuntimeError: pass
            else: raise AssertionError("Failed producer reported success")
        assert partial.exists() and not partial.with_suffix("").exists()
        record("interrupted export stays partial; no success or final archive")
        # Exercise the actual scheduler entry point, not just mocked conditions.
        for kind in ("missing-media-directory", "wrong-volume"):
            invalid = copy.deepcopy(config)
            if kind == "missing-media-directory": invalid["directory"] = str(Path(config["directory"]) / ("missing-" + run_id))
            else: invalid["volume_id"] += "-WRONG"
            bad = args.config.parent / (kind + "-" + run_id + ".json")
            with bad.open("x", encoding="utf-8") as output: json.dump(invalid, output)
            result = subprocess.run([sys.executable, str(backup.ROOT / "portable_backup.py"), "run", "--config", str(bad), "--if-due"], capture_output=True)
            assert result.returncode != 0
            last = json.loads((args.config.parent / "last-run.json").read_text())
            assert last["status"] == "FAIL"
            assert not Path(invalid["directory"]).exists() if kind == "missing-media-directory" else True
            record(kind + " fails closed with nonzero task exit and private failure status")
        # Simulate a missed run, execute the real if-due path, then ensure an
        # immediate second invocation doesn't create another snapshot.
        backup.save_json(args.config.parent / "last-run.json", {"status": "PASS", "last_success_at": (datetime.now(UTC) - timedelta(days=2)).isoformat()})
        command = [sys.executable, str(backup.ROOT / "portable_backup.py"), "run", "--config", str(args.config), "--if-due"]
        backup.call(command)
        fresh = json.loads((args.config.parent / "last-run.json").read_text())
        assert fresh["status"] == "PASS" and backup.recent(fresh)
        backup.call(command)
        assert json.loads((args.config.parent / "last-run.json").read_text()) == fresh
        record("missed-run catch-up executes; recent-success guard suppresses duplicate backup", archive=fresh["archive"])
        record("actual Windows task trigger, post-reboot scheduling and notification UI", "UNVERIFIED", reason="Schedule prepared only; registration/reboot/key custody need user decisions")
    except BaseException as exc:
        record("drill failure; preserve evidence and owned volumes", "FAIL", failure_type=type(exc).__name__)
        raise
    finally:
        for project in reversed(active):
            manage.assert_owned(project)
            manage.compose(project, "down", "--remove-orphans")
        after = full_baseline()
        assert manage.baseline_equal(before, after), "Protected service or Serve drift"
        mobile.verify(json.loads((mobile.STATE / "receipt.json").read_text()))
        record("all original services, Serve, exact ports and synthetic fixture preserved", state="PASS; only owned recovery containers/networks removed; volumes retained")
    print(json.dumps({"report": str(report_dir / "validation.json"), "PASS": sum(r["status"] == "PASS" for r in results),
                      "FAIL": sum(r["status"] == "FAIL" for r in results), "UNVERIFIED": sum(r["status"] == "UNVERIFIED" for r in results)}))


if __name__ == "__main__":
    main()
