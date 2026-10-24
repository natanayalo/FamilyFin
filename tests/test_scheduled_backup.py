"""Task monitoring must survive completed one-shot triggers and running results."""
import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/docker"))
scheduled = importlib.import_module("validate_scheduled_backup")


class ScheduleMonitoring(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Executes Windows PowerShell property semantics")
    def test_finished_one_time_task_can_have_no_next_run(self):
        original = scheduled.ps
        def fake_provider(code):
            providers = "function Get-ScheduledTask { [pscustomobject]@{State='Ready'} };function Get-ScheduledTaskInfo { [pscustomobject]@{LastTaskResult=0;LastRunTime=[DateTime]::UtcNow;NextRunTime=$null} };"
            return original(providers + code)
        with patch.object(scheduled, "ps", side_effect=fake_provider):
            result = scheduled.task_info(scheduled.TASK)
        self.assertIsNone(result["NextRunUtc"])
        self.assertEqual(result["LastTaskResult"], 0)

    def test_running_task_with_previous_success_is_not_finished(self):
        before = {"LastRunUtc": "old"}
        running = {"LastRunUtc": "new", "State": "Running", "LastTaskResult": 0}
        finished = running | {"State": "Ready"}
        with patch.object(scheduled, "task_info", side_effect=[running, finished]), patch.object(scheduled.time, "sleep"):
            self.assertEqual(scheduled.wait_run(scheduled.TASK, before), finished)

    def test_timeout_is_bounded_when_task_never_starts(self):
        before = {"LastRunUtc": "old", "State": "Ready", "LastTaskResult": 0}
        with patch.object(scheduled, "task_info", return_value=before), \
                patch.object(scheduled.time, "monotonic", side_effect=[0, 0, 2]), \
                patch.object(scheduled.time, "sleep"), self.assertRaises(RuntimeError):
            scheduled.wait_run(scheduled.TASK, before, timeout=1)


if __name__ == "__main__":
    unittest.main()
