"""A restart can change process start times, never authorize configuration drift."""
import copy
import hashlib
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/docker"))
host = importlib.import_module("host_recovery")


class RestartBaseline(unittest.TestCase):
    def baseline(self):
        return {"containers": [{"id": "one", "name": "/api", "started_at": "before", "status": "running",
                                "configuration_sha256": "config", "mounts": [], "ports": {}}],
                "serve": {"upstream": "unchanged"}}

    def test_only_start_time_changes_are_accepted(self):
        before = self.baseline()
        after = copy.deepcopy(before)
        after["containers"][0]["started_at"] = "after"
        host.assert_preserved(before, after)
        self.assertEqual(before["containers"][0]["started_at"], "before")

    def test_identity_config_state_mount_port_and_route_drift_refused(self):
        for field, value in (("id", "new"), ("status", "exited"), ("configuration_sha256", "new"),
                             ("mounts", [{"Destination": "/data", "RW": True}]), ("ports", {"8000/tcp": "public"})):
            before = self.baseline()
            after = copy.deepcopy(before)
            after["containers"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                host.assert_preserved(before, after)
        before = self.baseline()
        after = copy.deepcopy(before)
        after["serve"] = {"upstream": "changed"}
        with self.assertRaises(ValueError):
            host.assert_preserved(before, after)

    def test_mobile_receipt_is_adjusted_in_memory_only_after_validation(self):
        before = self.baseline()
        receipt = {"preservation": copy.deepcopy(before)}
        after = copy.deepcopy(before)
        after["containers"][0]["started_at"] = "after"
        adapted = host.after_restart_receipt(receipt, before, after)
        self.assertEqual(adapted["preservation"]["containers"][0]["started_at"], "after")
        self.assertEqual(receipt["preservation"]["containers"][0]["started_at"], "before")
        after["containers"][0]["configuration_sha256"] = "changed"
        with self.assertRaises(ValueError):
            host.after_restart_receipt(receipt, before, after)

    def dns_fixture(self):
        old = self.baseline()
        config = {"User": "10001:10001", "Env": ["MODE=production"]}
        settings = {"Dns": None, "DnsOptions": None, "DnsSearch": None, "ReadonlyRootfs": True}
        old["containers"][0]["configuration_sha256"] = host.config_fingerprint([config, settings])
        settings = settings | {"Dns": [], "DnsOptions": [], "DnsSearch": []}
        raw = [{"Id": "one", "Config": config, "HostConfig": settings}]
        observed = copy.deepcopy(old)
        observed["containers"][0]["configuration_sha256"] = host.config_fingerprint([config, settings])
        return old, observed, raw

    def test_empty_dns_normalization_requires_entire_original_fingerprint(self):
        old, observed, raw = self.dns_fixture()
        projected, evidence = host.reconcile_empty_dns(old, observed, raw)
        host.assert_preserved(old, projected)
        self.assertEqual(evidence[0]["fields"], ["Dns", "DnsOptions", "DnsSearch"])
        self.assertNotEqual(observed["containers"][0]["configuration_sha256"], old["containers"][0]["configuration_sha256"])
        self.assertEqual(raw[0]["HostConfig"]["Dns"], [])

    def test_dns_normalization_never_conceals_security_or_nonempty_dns_change(self):
        for key, value in (("ReadonlyRootfs", False), ("Dns", ["8.8.8.8"])):
            old, observed, raw = self.dns_fixture()
            raw[0]["HostConfig"][key] = value
            observed["containers"][0]["configuration_sha256"] = host.config_fingerprint([raw[0]["Config"], raw[0]["HostConfig"]])
            with self.subTest(field=key), self.assertRaises(ValueError):
                host.reconcile_empty_dns(old, observed, raw)

    def test_inconsistent_inspect_observation_is_refused(self):
        old, observed, raw = self.dns_fixture()
        raw[0]["Config"]["User"] = "0:0"
        with self.assertRaises(ValueError):
            host.reconcile_empty_dns(old, observed, raw)


class ReviewedRestartBaseline(unittest.TestCase):
    def test_explicit_restart_baseline_cannot_override_other_policies(self):
        import mobile
        receipt = {"preservation": RestartBaseline().baseline()}
        wrong = copy.deepcopy(receipt["preservation"])
        wrong["serve"] = {"upstream": "changed"}
        with self.assertRaises(RuntimeError):
            mobile.verify(receipt, reviewed_preservation=wrong)

    def test_separate_restart_record_preserves_original_and_rejects_policy_drift(self):
        import mobile
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            receipt = {"preservation": RestartBaseline().baseline()}
            original = json.dumps(receipt).encode()
            (state / "receipt.json").write_bytes(original)
            record = {"status": "VERIFIED_RESTART", "original_receipt_sha256": hashlib.sha256(original).hexdigest(),
                      "preservation": copy.deepcopy(receipt["preservation"])}
            record["preservation"]["containers"][0]["started_at"] = "after"
            path = state / "restart-preservation.json"
            path.write_text(json.dumps(record))
            with patch.object(mobile, "STATE", state):
                selected = mobile.restart_preservation(receipt)
                self.assertEqual(selected["containers"][0]["started_at"], "after")
                self.assertEqual((state / "receipt.json").read_bytes(), original)
                record["preservation"]["serve"] = {"upstream": "changed"}
                path.write_text(json.dumps(record))
                with self.assertRaises(RuntimeError):
                    mobile.restart_preservation(receipt)
                record["original_receipt_sha256"] = "wrong"
                path.write_text(json.dumps(record))
                with self.assertRaises(RuntimeError):
                    mobile.restart_preservation(receipt)


if __name__ == "__main__":
    unittest.main()
