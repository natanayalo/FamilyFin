"""Calendar scheduling regressions: manual backups, catch-up, midnight and DST."""
import importlib
import sys
import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/docker"))
host = importlib.import_module("portable_backup")


def success(stamp):
    return {"status": "PASS", "last_success_at": stamp.isoformat()}


class BackupCalendar(unittest.TestCase):
    def due(self, stamp, now, zone=UTC):
        return host.scheduled_backup_due(success(stamp), now=now, local_timezone=zone)

    def test_manual_backup_yesterday_does_not_suppress_daily_run(self):
        manual = datetime(2026, 10, 24, 14, tzinfo=UTC)
        scheduled = datetime(2026, 10, 25, 3, tzinfo=UTC)
        self.assertTrue(host.recent(success(manual), now=scheduled))  # Old rule incorrectly skipped.
        self.assertTrue(self.due(manual, scheduled))

    def test_manual_backup_before_three_does_not_suppress_upcoming_run(self):
        manual = datetime(2026, 10, 25, 2, 59, 59, tzinfo=UTC)
        self.assertTrue(self.due(manual, manual + timedelta(seconds=1)))

    def test_success_on_boundary_covers_the_period_inclusively(self):
        boundary = datetime(2026, 10, 25, 3, tzinfo=UTC)
        self.assertFalse(self.due(boundary, boundary))
        self.assertFalse(self.due(boundary, boundary + timedelta(hours=23, minutes=59)))
        self.assertTrue(self.due(boundary, boundary + timedelta(days=1)))

    def test_midnight_is_not_a_new_scheduled_period(self):
        stamp = datetime(2026, 10, 24, 15, tzinfo=UTC)
        self.assertFalse(self.due(stamp, datetime(2026, 10, 25, 0, tzinfo=UTC)))

    def test_logon_catches_up_after_missed_run_then_suppresses_duplicates(self):
        yesterday = datetime(2026, 10, 24, 3, tzinfo=UTC)
        logon = datetime(2026, 10, 25, 10, tzinfo=UTC)
        self.assertTrue(self.due(yesterday, logon))
        self.assertFalse(self.due(logon, logon + timedelta(minutes=1)))

    def test_manual_backup_after_three_covers_the_current_period(self):
        manual = datetime(2026, 10, 25, 4, tzinfo=UTC)
        self.assertFalse(self.due(manual, manual + timedelta(hours=19)))
        self.assertTrue(self.due(manual, datetime(2026, 10, 26, 3, tzinfo=UTC)))

    def test_failed_missing_malformed_naive_and_future_successes_never_skip(self):
        now = datetime(2026, 10, 25, 12, tzinfo=UTC)
        for receipt in ({}, {"status": "FAIL", "last_success_at": now.isoformat()},
                        {"status": "PASS", "last_success_at": "broken"},
                        {"status": "PASS", "last_success_at": None},
                        success(now.replace(tzinfo=None)), success(now + timedelta(seconds=1))):
            with self.subTest(receipt=receipt):
                self.assertTrue(host.scheduled_backup_due(receipt, now=now, local_timezone=UTC))

    def test_local_boundary_is_not_utc_three(self):
        local = timezone(timedelta(hours=3))
        before = datetime(2026, 10, 24, 23, 59, tzinfo=UTC)
        boundary = datetime(2026, 10, 25, 0, tzinfo=UTC)
        self.assertFalse(self.due(before, before, local))
        self.assertTrue(self.due(before, boundary, local))

    def test_daily_xml_refuses_a_time_that_disagrees_with_the_guard(self):
        with self.assertRaisesRegex(ValueError, "local 03:00"):
            host.schedule_xml(Path("config.json"), "S-1-5-21-123", "2026-10-25T04:00:00")

    def test_naive_now_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "aware"):
            host.scheduled_backup_due({}, now=datetime(2026, 10, 25, tzinfo=UTC).replace(tzinfo=None))

    def test_dst_periods_follow_each_boundary_dates_offset(self):
        try:
            zone = ZoneInfo("Asia/Jerusalem")
        except ZoneInfoNotFoundError:
            self.skipTest("IANA data absent on this Windows host; DST cases execute in Linux CI")
        for day, hours in ((datetime(2026, 3, 26, 3, tzinfo=zone), 23),
                           (datetime(2026, 10, 24, 3, tzinfo=zone), 25)):
            with self.subTest(day=day):
                following = day + timedelta(days=1)
                self.assertEqual((following.astimezone(UTC) - day.astimezone(UTC)).total_seconds(), hours * 3600)
                self.assertFalse(self.due(day, following.astimezone(UTC) - timedelta(seconds=1), zone))
                self.assertTrue(self.due(day, following.astimezone(UTC), zone))


if __name__ == "__main__":
    unittest.main()
