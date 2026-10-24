"""Export commits before exact-snapshot cleanup; cleanup failures remain visible."""
import importlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack, nullcontext
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/docker"))
host = importlib.import_module("portable_backup")
IMAGE = "sha256:" + "a" * 64
NAME = "familyfin-" + "b" * 32


class ExportCleanup(unittest.TestCase):
    def run_export(self, root, *, fail=None):
        media, state = root / "media", root / "state"
        media.mkdir(); state.mkdir()
        old = media / "existing-archive"
        old.write_bytes(b"keep existing external files")
        config = {"directory": str(media), "project": "familyfin-m1-test", "image": IMAGE}
        staged = {"snapshot": NAME, "image": IMAGE, "manifest_sha256": "c" * 64}
        cleaned = []

        def encrypt(_, snapshot, target):
            self.assertEqual(snapshot, NAME)
            Path(target).write_bytes(b"verified ciphertext fixture")
            if fail == "encrypt":
                raise RuntimeError("export failed")

        def stage(_, target):
            if fail == "authentication":
                raise ValueError("authentication failed")
            if fail == "changed-ciphertext":
                Path(target).write_bytes(b"changed after verification")
            return staged | ({"snapshot": "familyfin-" + "d" * 32} if fail == "wrong-snapshot" else {})

        def stream_command(_, volume, action, **options):
            self.assertEqual(volume, config["project"] + "_backups")
            self.assertEqual(action, "remove-exported")
            self.assertEqual(options, {"snapshot": NAME, "manifest_sha256": "c" * 64})
            saved = json.loads((state / "last-run.json").read_text())
            archive = media / saved["archive"]
            self.assertEqual(saved["status"], "PASS")
            self.assertEqual(saved["plaintext_snapshot_cleanup"]["status"], "PENDING")
            self.assertEqual(host.digest(archive), saved["archive_sha256"])
            self.assertEqual(json.loads(archive.with_name(archive.name + ".receipt.json").read_text()), saved)
            return ["cleanup-only-current-snapshot"]

        def call(command):
            if command == ["cleanup-only-current-snapshot"]:
                cleaned.append(NAME)
                if fail == "cleanup":
                    raise RuntimeError("cleanup denied")
                return b""
            self.assertEqual(command[-1], "backup")
            return (NAME + "\n").encode()

        with ExitStack() as stack:
            for name in ("check_media", "identity", "source", "remove_stage"):
                stack.enter_context(patch.object(host, name))
            stack.enter_context(patch.object(host, "docker", return_value=["operations"]))
            stack.enter_context(patch.object(host, "call", side_effect=call))
            stack.enter_context(patch.object(host, "encrypt", side_effect=encrypt))
            stack.enter_context(patch.object(host, "stage", side_effect=stage))
            stack.enter_context(patch.object(host, "stream_command", side_effect=stream_command))
            if fail == "receipt":
                stack.enter_context(patch.object(host.os, "fsync", side_effect=OSError("receipt flush failed")))
            if fail in {"encrypt", "authentication", "changed-ciphertext", "wrong-snapshot", "receipt"}:
                with self.assertRaises((ValueError, RuntimeError, OSError)):
                    host.backup(config, state)
                self.assertEqual(cleaned, [])
                result = None
            else:
                result = host.backup(config, state)
                self.assertEqual(cleaned, [NAME])
        self.assertEqual(old.read_bytes(), b"keep existing external files")
        return result

    def test_success_receipts_and_final_verified_ciphertext_precede_exact_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.run_export(Path(folder))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["plaintext_snapshot_cleanup"]["status"], "REMOVED")

    def test_cleanup_failure_preserves_success_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.run_export(Path(folder), fail="cleanup")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["plaintext_snapshot_cleanup"], {"status": "FAILED", "failure_type": "RuntimeError"})

    def test_export_or_receipt_failure_never_requests_snapshot_cleanup(self):
        for failure in ("encrypt", "authentication", "changed-ciphertext", "wrong-snapshot", "receipt"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                self.run_export(Path(folder), fail=failure)

    def test_cleanup_mount_is_only_the_owned_backup_volume_and_release_is_rechecked(self):
        config = {"project": "familyfin-m1-test", "image": IMAGE, "media_token": "test"}
        with patch.object(host, "source") as source:
            with self.assertRaises(ValueError):
                host.stream_command(config, "unrelated_backups", "remove-exported", snapshot=NAME)
            source.assert_not_called()
            command = host.stream_command(config, "familyfin-m1-test_backups", "remove-exported",
                                          snapshot=NAME, manifest_sha256="c" * 64)
            source.assert_called_once_with(config)
        self.assertEqual([command[i + 1] for i, arg in enumerate(command) if arg == "--mount"],
                         ["type=volume,source=familyfin-m1-test_backups,target=/backups"])
        self.assertNotIn("/var/lib/familyfin", " ".join(command[command.index("--entrypoint") + 3:]))


class CleanupMonitoring(unittest.TestCase):
    def invoke(self, root, action, receipt=None, extra=()):
        with patch("sys.argv", ["backup", action, "--config", str(root / "config.json"), *extra]), \
                patch.object(host, "read_config", return_value={}), \
                patch.object(host, "lock", side_effect=lambda _: nullcontext()), \
                patch.object(host.manage, "engine"), patch.object(host, "check_media"), \
                patch.object(host, "recovery_readiness", return_value={"recovery_ready": True}), \
                patch.object(host, "backup", return_value=receipt) as backup, \
                patch("sys.stdout", new_callable=io.StringIO) as output, \
                patch("sys.stderr", new_callable=io.StringIO):
            code = host.main()
        return code, output.getvalue(), backup.called

    def receipt(self, cleanup):
        return {"status": "PASS", "last_success_at": datetime.now(UTC).isoformat(),
                "plaintext_snapshot_cleanup": {"status": cleanup}}

    def test_cleanup_failure_alerts_and_returns_nonzero_without_losing_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            receipt = self.receipt("FAILED")
            self.assertEqual(self.invoke(root, "run", receipt)[0], 1)
            self.assertEqual(json.loads((root / "last-run.json").read_text()), receipt)
            self.assertEqual(host.read_alert(root)["failure_type"], "PlaintextSnapshotCleanupFailed")
            self.assertEqual(json.loads((root / "history.jsonl").read_text()), receipt)

    def test_incomplete_cleanup_keeps_status_and_recent_skip_nonzero_without_retrying_deletion(self):
        for cleanup in ("PENDING", "FAILED"):
            with self.subTest(cleanup=cleanup), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                receipt = self.receipt(cleanup)
                host.save_json(root / "last-run.json", receipt)
                code, output, _ = self.invoke(root, "status")
                result = json.loads(output)
                self.assertEqual(code, 1)
                self.assertTrue(result["backup_healthy"] and result["last_backup_successful"])
                self.assertEqual(result["status"], "ATTENTION_REQUIRED")
                self.assertTrue(result["snapshot_cleanup_attention"])
                self.assertFalse((root / "backup-alert.json").exists())
                code, _, called = self.invoke(root, "run", extra=("--if-due",))
                self.assertEqual(code, 1)
                self.assertFalse(called)
                self.assertEqual(json.loads((root / "last-run.json").read_text()), receipt)
                self.assertEqual(host.read_alert(root)["status"], "UNACKNOWLEDGED")


if __name__ == "__main__":
    unittest.main()
