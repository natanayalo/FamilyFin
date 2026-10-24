"""Mobile preparation must fail closed before changing the wrong data or route."""
import copy
import importlib
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/docker"))
mobile = importlib.import_module("mobile")


def original():
    return {"TCP":{"443":{"HTTPS":True}},"Web":{
        "familyfin.example-tailnet.ts.net:443":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:8088"}}}}}


class MobileGuards(unittest.TestCase):
    def test_accepts_only_existing_private_m0_route(self):
        self.assertEqual(mobile.private_hostname(original()), "familyfin.example-tailnet.ts.net")
        for mutation in ("funnel","extra-handler","other-target","public-host","extra-listener","hostname-injection"):
            value=original()
            listener=next(iter(value["Web"]))
            if mutation=="funnel": value["AllowFunnel"]={listener:True}
            if mutation=="extra-handler": value["Web"][listener]["Handlers"]["/other"]={"Proxy":"http://127.0.0.1:8088"}
            if mutation=="other-target": value["Web"][listener]["Handlers"]["/"]["Proxy"]="http://127.0.0.1:8090"
            if mutation=="public-host": value["Web"]["example.com:443"]=value["Web"].pop(listener)
            if mutation=="extra-listener": value["TCP"]["8443"]={"HTTPS":True}
            if mutation=="hostname-injection": value["Web"]["evil;command.ts.net:443"]=value["Web"].pop(listener)
            with self.subTest(mutation=mutation),self.assertRaises(RuntimeError):mobile.private_hostname(value)

    def test_readonly_verifier_allows_only_exact_preapproved_shape_of_trial_route(self):
        before={"containers":[{"id":"restore-id","mounts":[],"status":"running"}],"serve":original()}
        after=copy.deepcopy(before)
        hostname="familyfin.example-tailnet.ts.net"
        after["serve"]["Web"][hostname+":443"]["Handlers"]["/"]["Proxy"]="http://127.0.0.1:8090"
        with self.assertRaises(RuntimeError):mobile.preserved(before,after,hostname)
        self.assertIn("trial",mobile.preserved(before,after,hostname,allow_trial=True))
        after["containers"][0]["status"]="exited"
        with self.assertRaises(RuntimeError):mobile.preserved(before,after,hostname,allow_trial=True)

    def test_compose_does_not_inherit_development_or_remote_overrides(self):
        ambient={"COMPOSE_FILE":"evil.yml","COMPOSE_PROJECT_NAME":"other","FAMILYFIN_PORT":"0.0.0.0:80",
                 "FAMILY_FINANCE_LOCAL_DEV":"1","FAMILY_FINANCE_DATA_ROOT":"other-data","PATH":"keep"}
        with patch.dict(mobile.os.environ,ambient,clear=True):
            env=mobile.environment("familyfin.example-tailnet.ts.net")
        self.assertEqual(env["FAMILYFIN_PORT"],"8090")
        self.assertEqual(env["FAMILYFIN_HOST"],"familyfin.example-tailnet.ts.net")
        self.assertEqual(env["FAMILYFIN_ORIGIN"],"https://familyfin.example-tailnet.ts.net")
        self.assertEqual(env["COMPOSE_DISABLE_ENV_FILE"],"1")
        self.assertNotIn("COMPOSE_FILE",env)
        self.assertNotIn("FAMILY_FINANCE_LOCAL_DEV",env)
        self.assertNotIn("FAMILY_FINANCE_DATA_ROOT",env)

    def test_noninteractive_credential_setup_stops_before_application_access(self):
        with patch.object(mobile.sys.stdin,"isatty",return_value=False),patch.object(mobile,"verify") as verify:
            with self.assertRaises(RuntimeError):mobile.set_test_passwords({})
            verify.assert_not_called()

    def test_different_fixture_stops_before_marker_or_account_access(self):
        with TemporaryDirectory() as folder:
            report=Path(folder)
            (report/"restored-state-comparison.json").write_text(json.dumps({"financial_values_sha256":"known","migration":[["head"]],"archive_count":1}))
            current={"financial_sha256":"different","migrations":[["head"]],"archives":{"archive":"hash"},
                     "counts":{"api_users":2,"transactions":1,"source_files":1,"net_worth_accounts":2}}
            with patch.object(mobile.manage,"REPORTS",report),patch.object(mobile.manage,"assert_owned"),patch.object(mobile.validate,"status",return_value=current),patch.object(mobile.validate,"execute") as execute:
                with self.assertRaises(RuntimeError):mobile.fixture()
                execute.assert_not_called()

    def test_backup_failure_prevents_configuration_or_credential_mutation(self):
        with TemporaryDirectory() as folder:
            report=Path(folder);state=report/"private";state.mkdir()
            images={name:"sha256:"+str(index)*64 for index,name in enumerate(("api","web","caddy"),1)}
            (report/"reviewed-images.json").write_text(json.dumps(images))
            (report/"tested-configs.json").write_text(json.dumps(images))
            for name,value in images.items():
                (report/f"trivy-familyfin-m1-{name}-security-review-summary.json").write_text(json.dumps({"docker_image_id":value,"image_id":value}))
            (state/"baseline.json").write_text(json.dumps({"containers":[],"serve":original()}))
            baseline={"containers":[],"serve":original()}
            with patch.object(mobile,"REPORT",report),patch.object(mobile,"STATE",state),patch.object(mobile.manage,"STATE",state),patch.object(mobile.manage,"baseline",return_value=baseline),patch.object(mobile,"preservation",return_value=baseline),patch.object(mobile,"fixture",return_value={}),patch.object(mobile.manage,"verify"),patch.object(mobile,"check_images"),patch.object(mobile,"protected_folder"),patch.object(mobile.manage,"run") as run,patch.object(mobile,"backup",side_effect=RuntimeError("verification failed")),patch.object(mobile,"compose") as compose,patch.object(mobile,"reset_passwords") as reset:
                run.return_value.returncode=1
                with self.assertRaisesRegex(RuntimeError,"verification failed"):mobile.prepare()
                compose.assert_not_called();reset.assert_not_called()
                self.assertFalse(any("tag" in call.args for call in run.call_args_list))

    def test_changed_release_image_stops_before_application_mutation(self):
        with patch.object(mobile,"image_id",return_value="different"), self.assertRaises(RuntimeError):
            mobile.check_images({name:"expected" for name in ("api","web","caddy")},mobile.TAG)

    def test_compose_failure_does_not_echo_stdin_or_subprocess_output(self):
        result=mobile.subprocess.CompletedProcess([],1,stdout="sensitive",stderr="sensitive")
        with patch.object(mobile.subprocess,"run",return_value=result), self.assertRaises(RuntimeError) as caught:
            mobile.compose("familyfin.example-tailnet.ts.net","exec",stdin="sensitive")
        self.assertNotIn("sensitive",str(caught.exception))

    def test_lab_reversion_refuses_until_m0_route_is_restored(self):
        before={"containers":[],"serve":original()}
        current=copy.deepcopy(before)
        current["serve"]["Web"]["familyfin.example-tailnet.ts.net:443"]["Handlers"]["/"]["Proxy"]="http://127.0.0.1:8090"
        receipt={"hostname":"familyfin.example-tailnet.ts.net","preservation":before}
        with patch.object(mobile,"preservation",return_value=current),patch.object(mobile,"compose") as compose:
            with self.assertRaises(RuntimeError):mobile.restore_lab(receipt)
            compose.assert_not_called()

    def test_ordinary_lab_start_cannot_replace_prepared_mobile_origin(self):
        with TemporaryDirectory() as folder:
            state=Path(folder);directory=state/"mobile-acceptance";directory.mkdir()
            (directory/"receipt.json").write_text(json.dumps({"status":"PREPARED_LOCAL_ONLY"}))
            with patch.object(mobile.manage,"STATE",state),patch.object(sys,"argv",["manage.py","start"]),patch.object(mobile.manage,"engine") as engine,patch.object(mobile.manage,"compose") as compose:
                with self.assertRaisesRegex(RuntimeError,"Mobile preparation owns"):
                    mobile.manage.main()
                engine.assert_not_called();compose.assert_not_called()


class MobileProfile(unittest.TestCase):
    def test_preparation_profile_follows_receipt_without_repeating_cli_options(self):
        configs={name:"sha256:"+"a"*64 for name in ("api","web","caddy")}
        receipt={"lab_profile":{"report_name":"chosen-report","image_tag":"chosen-reviewed","image_configs":configs}}
        original=copy.deepcopy(receipt)
        with patch.object(mobile,"REPORT",mobile.REPORT),patch.object(mobile,"TAG",mobile.TAG):
            self.assertEqual(mobile.select_profile(receipt),configs)
            self.assertEqual(mobile.REPORT,mobile.manage.REPORTS/"chosen-report")
            self.assertEqual(mobile.environment("familyfin.example-tailnet.ts.net")["FAMILYFIN_IMAGE_TAG"],"chosen-reviewed")
        self.assertEqual(receipt,original)

    def test_profile_rejects_legacy_redirected_or_incomplete_evidence_without_mutation(self):
        good={"report_name":"reviewed-report","image_tag":"reviewed-tag",
              "image_configs":{name:"sha256:"+"a"*64 for name in ("api","web","caddy")}}
        before=(mobile.REPORT,mobile.TAG)
        for profile in (None,good|{"report_name":"../other"},good|{"image_tag":"bad;command"},good|{"image_configs":{}}):
            with self.subTest(profile=profile),self.assertRaises(RuntimeError):
                mobile.select_profile({"lab_profile":profile})
            self.assertEqual((mobile.REPORT,mobile.TAG),before)


if __name__=="__main__":
    unittest.main()
