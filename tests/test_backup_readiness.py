"""Startup delays are bounded; endpoint/release changes must never be retried away."""
import copy
import importlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/docker"))
ready = importlib.import_module("backup_readiness")
backup = importlib.import_module("portable_backup")
CONFIG = {"project": "familyfin-m1-synthetic", "container_image": "sha256:" + "a" * 64}
CONTEXT = [{"Endpoints": {"docker": {"Host": "npipe:////./pipe/dockerDesktopLinuxEngine"}}}]
ENGINE = {"OSType": "linux", "ServerVersion": "29.9.2"}
API = [{"Image": CONFIG["container_image"], "Config": {"Labels": {
    "com.docker.compose.project": CONFIG["project"], "com.docker.compose.service": "api"}},
    "State": {"Running": True, "Health": {"Status": "healthy"}}}]


def response(value=None, code=0):
    return SimpleNamespace(returncode=code, stdout=json.dumps(value))


class Readiness(unittest.TestCase):
    def setUp(self):
        self.time = 0
        self.calls = []
        self.environ = patch.dict("os.environ", {"DOCKER_HOST": "", "DOCKER_CONTEXT": ""})
        self.environ.start()
        self.addCleanup(self.environ.stop)

    def clock(self):
        return self.time

    def sleep(self, seconds):
        self.time += seconds

    def invoke(self, answers, timeout=15):
        answers = iter(answers)
        def run(command, **options):
            self.calls.append(command)
            self.assertLessEqual(options["timeout"], 5)
            result = next(answers)
            if isinstance(result, Exception):
                raise result
            return result
        return ready.wait_ready(CONFIG, runner=run, clock=self.clock, sleep=self.sleep, timeout=timeout)

    def test_delayed_engine_and_api_wait_until_healthy(self):
        starting = copy.deepcopy(API)
        starting[0]["State"]["Health"]["Status"] = "starting"
        result = self.invoke([response(CONTEXT), response(code=1), response(ENGINE), response(starting),
                              response(ENGINE), response(API)])
        self.assertEqual(result, {"status": "READY", "attempts": 3, "elapsed_seconds": 10})

    def test_absent_engine_times_out_without_starting_anything(self):
        with self.assertRaises(TimeoutError):
            self.invoke([response(CONTEXT), response(code=1), response(code=1)], timeout=10)
        self.assertEqual(self.time, 10)
        self.assertTrue(all(c[1] == "context" or c[1:3] == ["--host", ready.ENDPOINT] for c in self.calls))
        self.assertTrue(all(any(verb in c for verb in ("context", "info", "inspect")) for c in self.calls))

    def test_wrong_endpoint_rejected_before_any_engine_probe(self):
        wrong = [{"Endpoints": {"docker": {"Host": "tcp://remote:2375"}}}]
        with self.assertRaises(ValueError):
            self.invoke([response(wrong)])
        self.assertEqual(len(self.calls), 1)

    def test_changed_release_or_missing_container_is_not_retried(self):
        wrong = copy.deepcopy(API)
        wrong[0]["Image"] = "sha256:" + "b" * 64
        for inspected in (response(wrong), response(code=1)):
            with self.subTest(inspected=inspected.returncode), self.assertRaises(ValueError):
                self.invoke([response(CONTEXT), response(ENGINE), inspected])
        self.assertEqual(self.time, 0)

    def test_probe_timeout_is_retried_within_overall_bound(self):
        result = self.invoke([response(CONTEXT), subprocess.TimeoutExpired("docker", 5),
                              response(ENGINE), response(API)])
        self.assertEqual(result["attempts"], 2)

    def test_wrong_engine_and_ambient_overrides_fail_closed(self):
        with self.assertRaises(ValueError):
            self.invoke([response(CONTEXT), response(ENGINE | {"OSType": "windows"})])
        with patch.dict("os.environ", {"DOCKER_HOST": "tcp://remote:2375"}), self.assertRaises(ValueError):
            self.invoke([])

    def test_recent_backup_preserved_after_readiness_skip_but_warning_not_cleared(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            prior = {"status": "PASS", "last_success_at": datetime.now(UTC).isoformat()}
            backup.save_json(state / "last-run.json", prior)
            alert = backup.record_alert(state, {"checked_at": datetime.now(UTC).isoformat(), "failure_type": "RuntimeError"})
            with patch("sys.argv", ["backup", "run", "--config", str(state / "config.json"), "--if-due", "--wait-ready"]), \
                    patch.object(backup, "read_config", return_value=CONFIG), \
                    patch.object(backup, "lock", side_effect=lambda _: __import__('contextlib').nullcontext()), \
                    patch.object(ready, "wait_ready", return_value={"status": "READY"}), \
                    patch.object(backup.manage, "engine"), patch.object(backup, "check_media"), \
                    patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(backup.main(), 0)
            self.assertEqual(json.loads((state / "last-run.json").read_text()), prior)
            self.assertEqual(backup.read_alert(state), alert)

    def test_wait_failure_records_failure_and_never_calls_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            with patch("sys.argv", ["backup", "run", "--config", str(state / "config.json"), "--wait-ready"]), \
                    patch.object(backup, "read_config", return_value=CONFIG), \
                    patch.object(backup, "lock", side_effect=lambda _: __import__('contextlib').nullcontext()), \
                    patch.object(ready, "wait_ready", side_effect=TimeoutError), patch.object(backup, "backup") as job, \
                    patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(backup.main(), 1)
            job.assert_not_called()
            self.assertEqual(json.loads((state / "last-run.json").read_text())["status"], "FAIL")
            self.assertEqual(backup.read_alert(state)["status"], "UNACKNOWLEDGED")


if __name__ == "__main__":
    unittest.main()
