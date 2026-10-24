"""Archive attacks and scheduler failures must never become usable recoveries."""
import importlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/docker"))
stream = importlib.import_module("portable_stream")
host = importlib.import_module("portable_backup")
IMAGE = "sha256:" + "a" * 64
NAME = "familyfin-" + "b" * 32


def archive(extra=(), *, metadata=None):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as tar:
        items = [("bundle.json", json.dumps(metadata or {"format": 1, "snapshot": NAME, "image": IMAGE}).encode()),
                 ("snapshot/manifest.json", b"{}"), ("snapshot/family_finance.sqlite3", b"test")]
        for name, data in items + list(extra):
            info = tarfile.TarInfo(name)
            if data is None:
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                tar.addfile(info)
            else:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    output.seek(0)
    return output


class ArchiveGuards(unittest.TestCase):
    def test_unsafe_paths_and_keys_are_rejected(self):
        for name in ("/x", "../x", "snapshot/../x", "snapshot//x", "snapshot/./x",
                     "snapshot\\x", "C:/x", "snapshot/api-secret.key", "snapshot/.synthetic-lab"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                stream.safe_name(name)

    def test_valid_archive_stays_incomplete_until_correct_finalize(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            stream.unpack(root, IMAGE, "token", archive())
            self.assertEqual((root / NAME / "family_finance.sqlite3").read_bytes(), b"test")
            self.assertTrue((root / ".incomplete").exists())
            with self.assertRaises(ValueError):
                stream.finalize(root, IMAGE, "other-token")
            with patch.object(stream, "verify") as verify, patch("sys.stdout", new_callable=io.StringIO):
                stream.finalize(root, IMAGE, "token")
                verify.assert_called_once_with(root / NAME)
            self.assertFalse((root / ".incomplete").exists())
            self.assertEqual((root / ".verified").read_text(), "token")

    def test_failed_application_verification_never_finalizes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            stream.unpack(root, IMAGE, "token", archive())
            with patch.object(stream, "verify", side_effect=ValueError("corrupt")), self.assertRaises(ValueError):
                stream.finalize(root, IMAGE, "token")
            self.assertTrue((root / ".incomplete").exists())
            self.assertFalse((root / ".verified").exists())

    def test_wrong_release_and_source_identity_rejected(self):
        for change in ({"image": "other"}, {"snapshot": "../source"}, {"format": 2}):
            metadata = {"format": 1, "snapshot": NAME, "image": IMAGE} | change
            with tempfile.TemporaryDirectory() as folder, self.subTest(change=change), self.assertRaises(ValueError):
                stream.unpack(Path(folder), IMAGE, "token", archive(metadata=metadata))

    def test_links_duplicate_paths_and_traversal_leave_only_incomplete_staging(self):
        for extra in (("snapshot/link", None), ("snapshot/manifest.json", b"new"),
                      ("snapshot/../../escape", b"bad"), ("snapshot/api-secret.key", b"secret")):
            with tempfile.TemporaryDirectory() as folder, self.subTest(extra=extra), self.assertRaises(ValueError):
                stream.unpack(Path(folder), IMAGE, "token", archive([extra]))

    def test_nonempty_staging_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "keep").write_text("original")
            with self.assertRaises(ValueError):
                stream.unpack(root, IMAGE, "token", archive())
            self.assertEqual((root / "keep").read_text(), "original")

    def test_file_and_byte_limits(self):
        for limit, value in (("MAX_FILES", 1), ("MAX_BYTES", 10)):
            with tempfile.TemporaryDirectory() as folder, patch.object(stream, limit, value), self.assertRaises(ValueError):
                stream.unpack(Path(folder), IMAGE, "token", archive())

    def test_truncated_tar_never_finalizes(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaises((tarfile.TarError, ValueError)):
            stream.unpack(Path(folder), IMAGE, "token", io.BytesIO(archive().getvalue()[:550]))


class HostGuards(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows byte-range lock semantics")
    def test_concurrent_lock_refused_and_crash_releases_it(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "worker.lock"
            code = "import sys;sys.path.insert(0,sys.argv[1]);import portable_backup as b;from pathlib import Path\nwith b.lock(Path(sys.argv[2])):\n print('ready',flush=True);sys.stdin.read()"
            with subprocess.Popen([sys.executable, "-c", code, str(host.ROOT), str(target)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as child:
                try:
                    self.assertEqual(child.stdout.readline().strip(), "ready")
                    with self.assertRaises(RuntimeError), host.lock(target):
                        self.fail("Concurrent lock acquired")
                    child.terminate()
                    child.wait(timeout=10)
                    with host.lock(target):
                        pass
                finally:
                    if child.poll() is None:
                        child.terminate()
                        child.wait(timeout=10)

    def test_recent_success_failed_future_and_stale_states(self):
        now = datetime.now(UTC)
        good = {"status": "PASS", "last_success_at": (now - timedelta(hours=1)).isoformat()}
        self.assertTrue(host.recent(good, now=now))
        for value in ({}, good | {"status": "FAIL"}, good | {"status": "RUNNING"}, good | {"last_success_at": (now - timedelta(days=2)).isoformat()},
                      good | {"last_success_at": (now + timedelta(days=1)).isoformat()}):
            self.assertFalse(host.recent(value, now=now))

    def test_media_failure_precedes_snapshot_or_key_access(self):
        with patch.object(host, "check_media", side_effect=ValueError("wrong disk")), \
                patch.object(host, "source") as source, patch.object(host, "identity") as identity, self.assertRaises(ValueError):
            host.backup({}, Path("unused"))
        source.assert_not_called()
        identity.assert_not_called()

    def test_helpers_have_no_network_or_logs_or_host_financial_mounts(self):
        command = host.docker({"image": IMAGE, "media_token": "test"}, [("owned", "/backups", True)])
        self.assertIn("none", command)
        self.assertIn("--read-only", command)
        self.assertEqual(command[command.index("--log-driver") + 1], "none")
        self.assertNotIn("--privileged", command)
        self.assertNotIn("docker.sock", " ".join(command))
        self.assertIn("type=volume,source=owned,target=/backups,readonly", command)

    def test_restore_refuses_non_recovery_names_before_docker(self):
        with patch.object(host, "call") as call:
            for name in ("familyfin-m1-synthetic", "familyfin-m1-restore", "../../other"):
                with self.assertRaises(ValueError):
                    host.restore_stage({}, {}, name)
            call.assert_not_called()

    def test_proposed_schedule_has_catchup_least_privilege_and_no_password(self):
        xml = host.schedule_xml(Path("config.json"), "S-1-5-21-123", "2026-10-24T03:00:00")
        root = ElementTree.fromstring(xml)
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        self.assertEqual(root.find("t:Settings/t:StartWhenAvailable", ns).text, "true")
        self.assertEqual(root.find("t:Principals/t:Principal/t:LogonType", ns).text, "InteractiveToken")
        self.assertEqual(root.find("t:Principals/t:Principal/t:RunLevel", ns).text, "LeastPrivilege")
        self.assertIsNotNone(root.find("t:Triggers/t:LogonTrigger", ns))
        self.assertIsNotNone(root.find("t:Settings/t:RestartOnFailure", ns))
        self.assertIn("portable-task.ps1", xml)
        self.assertNotIn("Register-ScheduledTask", xml)

    def test_bounded_schedule_stops_both_daily_and_logon_triggers(self):
        xml = host.schedule_xml(Path("config.json"), "S-1-5-21-123", "2026-10-24T03:00:00", "2026-10-31T00:00:00")
        self.assertEqual(xml.count("<EndBoundary>2026-10-31T00:00:00</EndBoundary>"), 2)
        with self.assertRaises(ValueError):
            host.schedule_xml(Path("config.json"), "S-1-5-21-123", "2026-10-24T03:00:00", "2026-10-23T00:00:00")

    def test_recent_success_does_not_hide_missing_media_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            status = root / "last-run.json"
            prior = {"status": "PASS", "last_success_at": datetime.now(UTC).isoformat()}
            status.write_text(json.dumps(prior))
            with patch("sys.argv", ["backup", "run", "--config", str(root / "config.json"), "--if-due"]), \
                    patch.object(host, "read_config", return_value={}), patch.object(host, "lock", return_value=nullcontext()), \
                    patch.object(host.manage, "engine"), patch.object(host, "check_media", side_effect=ValueError("missing")), \
                    patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(host.main(), 1)
            result = json.loads(status.read_text())
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["last_success_at"], prior["last_success_at"])

    def recent_skip_with_unavailable_recovery(self, missing):
        for wait_ready in (False, True):
            with self.subTest(wait_ready=wait_ready), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                ciphertext = root / ("20261023T120000Z-" + NAME + ".tar.age")
                ciphertext.write_bytes(b"disposable encrypted archive")
                key = root / "disposable-key"
                key.write_bytes(b"disposable identity fixture")
                prior = {"status": "PASS", "last_success_at": datetime.now(UTC).isoformat(),
                         "archive": ciphertext.name, "archive_sha256": host.digest(ciphertext)}
                host.save_json(root / "last-run.json", prior)
                (ciphertext if missing == "archive" else key).unlink()
                config = {"directory": str(root)}
                extra = ["--wait-ready"] if wait_ready else []

                def identity(_, candidate=key):
                    candidate.read_bytes()  # Real missing-file failure, not a readiness stub.
                    return candidate

                native_lock = (nullcontext() if sys.platform == "win32" else
                               patch.object(host, "lock", side_effect=lambda _: nullcontext()))
                ready = importlib.import_module("backup_readiness")
                with patch("sys.argv", ["backup", "run", "--config", str(root / "config.json"), "--if-due", *extra]), \
                        patch.object(host, "read_config", return_value=config), native_lock, \
                        patch.object(host.manage, "engine"), \
                        patch.object(host, "media", return_value={"FreeBytes": 16 * 1024**3}), \
                        patch.object(host, "identity", side_effect=identity), \
                        patch.object(ready, "wait_ready", return_value={"status": "READY"}), \
                        patch.object(host, "backup") as create_backup, \
                        patch.object(host, "recovery_readiness", wraps=host.recovery_readiness) as readiness, \
                        patch("sys.stderr", new_callable=io.StringIO), \
                        patch("sys.stdout", new_callable=io.StringIO) as output:
                    self.assertEqual(host.main(), 1)
                    readiness.assert_called_once_with(config, prior)
                    create_backup.assert_not_called()
                self.assertNotIn("no new snapshot needed", output.getvalue())
                failure = json.loads((root / "last-run.json").read_text())
                self.assertEqual(failure["status"], "FAIL")
                self.assertEqual(failure["last_success_at"], prior["last_success_at"])
                self.assertEqual(host.read_alert(root)["status"], "UNACKNOWLEDGED")
                history = [json.loads(line) for line in (root / "history.jsonl").read_text().splitlines()]
                self.assertEqual(history, [failure])
                self.assertFalse((ciphertext if missing == "archive" else key).exists())

    def test_recent_skip_fails_and_alerts_when_ciphertext_is_missing(self):
        self.recent_skip_with_unavailable_recovery("archive")

    def test_recent_skip_fails_and_alerts_when_identity_is_unavailable(self):
        self.recent_skip_with_unavailable_recovery("key")


class PersistentAlerts(unittest.TestCase):
    def setUp(self):
        if sys.platform != "win32":
            # These tests cover alert transitions; native Windows lock behavior
            # has its own regression test. Production host tooling is Windows-only.
            mocked = patch.object(host, "lock", side_effect=lambda _: nullcontext())
            mocked.start()
            self.addCleanup(mocked.stop)

    def invoke(self, root, action, *extra):
        with patch("sys.argv", ["backup", action, "--config", str(root / "config.json"), *extra]), \
                patch.object(host, "read_config", return_value={}), \
                patch.object(host, "recovery_readiness", return_value={"recovery_ready": True}), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            code = host.main()
        return code, json.loads(output.getvalue())

    def failure(self):
        return {"checked_at": datetime.now(UTC).isoformat(), "failure_type": "ValueError"}

    def test_successful_retry_keeps_warning_until_explicit_acknowledgement(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            alert = host.record_alert(root, self.failure())
            success = {"status": "PASS", "last_success_at": datetime.now(UTC).isoformat()}
            with patch("sys.argv", ["backup", "run", "--config", str(root / "config.json")]), \
                    patch.object(host, "read_config", return_value={}), patch.object(host.manage, "engine"), \
                    patch.object(host, "backup", return_value=success), patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(host.main(), 0)
            code, status = self.invoke(root, "status")
            self.assertEqual(code, 1)
            self.assertEqual(status["status"], "ATTENTION_REQUIRED")
            self.assertTrue(status["backup_healthy"])
            self.assertEqual(status["alert"]["id"], alert["id"])
            self.assertEqual(self.invoke(root, "acknowledge-alert", "--alert-id", alert["id"])[0], 0)
            self.assertEqual(self.invoke(root, "status")[0], 0)
            self.assertEqual(json.loads((root / "last-run.json").read_text()), success)

    def test_new_failure_invalidates_old_acknowledgement_id(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = host.record_alert(root, self.failure())
            second = host.record_alert(root, self.failure())
            self.assertEqual(second["first_failure_at"], first["first_failure_at"])
            self.assertEqual(second["failure_count"], 2)
            with self.assertRaises(ValueError):
                host.acknowledge_alert(root, first["id"])
            self.assertEqual(host.read_alert(root)["status"], "UNACKNOWLEDGED")

    def test_acknowledgement_never_converts_failed_backup_to_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            alert = host.record_alert(root, self.failure())
            failed = {"status": "FAIL", "last_success_at": datetime.now(UTC).isoformat()}
            host.save_json(root / "last-run.json", failed)
            host.acknowledge_alert(root, alert["id"])
            code, result = self.invoke(root, "status")
            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "FAIL_OR_STALE")
            self.assertFalse(result["backup_healthy"])
            self.assertFalse(result["unacknowledged_failure"])
            self.assertEqual(result["last_run"], failed)

    def test_repeated_acknowledgement_refused_and_new_incident_reopens(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = host.record_alert(root, self.failure())
            host.acknowledge_alert(root, first["id"])
            with self.assertRaises(ValueError):
                host.acknowledge_alert(root, first["id"])
            second = host.record_alert(root, self.failure())
            self.assertEqual(second["failure_count"], 1)
            self.assertNotEqual(second["id"], first["id"])
            self.assertEqual(host.read_alert(root)["status"], "UNACKNOWLEDGED")
            self.assertEqual(len((root / "alert-history.jsonl").read_text().splitlines()), 3)

    def test_malformed_acknowledgement_refused_without_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for token in (None, "", "../other", "a" * 31, "A" * 32):
                with self.subTest(token=token), self.assertRaises(ValueError):
                    host.acknowledge_alert(root, token)
            self.assertEqual(list(root.iterdir()), [])

    def test_damaged_alert_cannot_report_a_healthy_backup_as_clear(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            host.save_json(root / "last-run.json", {"status": "PASS", "last_success_at": datetime.now(UTC).isoformat()})
            host.save_json(root / "backup-alert.json", {"status": "UNKNOWN"})
            with self.assertRaises(ValueError):
                self.invoke(root, "status")
            self.assertEqual(json.loads((root / "backup-alert.json").read_text()), {"status": "UNKNOWN"})


if __name__ == "__main__":
    unittest.main()
