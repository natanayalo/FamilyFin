"""Scan evidence must not silently accept malformed or unresolved findings."""
import hashlib
import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/docker"))
spec = importlib.util.spec_from_file_location("docker_security_scan", ROOT / "deploy/docker/scan_images.py")
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)


def report(issues):
    return {"SchemaVersion": 2, "Metadata": {"ImageID": "sha256:example"},
            "Results": [{"Target": "OS", "Vulnerabilities": issues}]}


@pytest.mark.parametrize("severity", ["CRITICAL", "HIGH", "UNKNOWN"])
@pytest.mark.parametrize("fixed", [None, "2.0.0"])
def test_fixed_and_unfixed_findings_remain_blockers(severity, fixed):
    result = scan.summarize(report([{"Severity": severity, "FixedVersion": fixed}]))
    assert result["status"] == "FAIL"
    assert len(result["blocking"]) == 1


@pytest.mark.parametrize("bad", [{}, {"SchemaVersion": 2, "Results": []},
    {"SchemaVersion": 2, "Results": [{"Target": "OS"}]}])
def test_missing_evidence_is_not_clean(bad):
    with pytest.raises(ValueError):
        scan.summarize(bad)


def test_successful_empty_target_is_clean():
    assert scan.summarize(report([]))["status"] == "PASS"


def test_lower_severity_findings_remain_visible():
    result = scan.summarize(report([{"Severity": "MEDIUM"}]))
    assert result["sections"][0]["counts"] == {"MEDIUM": 1}


def test_unrecognized_severity_is_not_clean():
    with pytest.raises(ValueError):
        scan.summarize(report([{"Severity": "UNEXPECTED"}]))


def make_archive(tmp_path, *, corrupt=False, wrong_link=False, multiple=False):
    config = b'{"architecture":"amd64","os":"linux"}'
    config_id = "sha256:" + hashlib.sha256(config).hexdigest()
    config_path = "blobs/sha256/" + config_id.split(":")[1]
    manifest = json.dumps({"config": {"digest": "sha256:" + "0" * 64 if wrong_link else config_id}}).encode()
    manifest_id = "sha256:" + hashlib.sha256(manifest).hexdigest()
    index = json.dumps({"manifests": [{"digest": manifest_id}]}).encode()
    index_id = "sha256:" + hashlib.sha256(index).hexdigest()
    entries = {"index.json": json.dumps({"manifests": [{"digest": index_id}]}).encode(),
        "manifest.json": json.dumps([{"Config": config_path}] * (2 if multiple else 1)).encode(),
        config_path: config, "blobs/sha256/" + manifest_id.split(":")[1]: manifest,
        "blobs/sha256/" + index_id.split(":")[1]: b"corrupt" if corrupt else index}
    path = tmp_path / "image.tar"
    with tarfile.open(path, "w") as target:
        for name, data in entries.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            target.addfile(member, io.BytesIO(data))
    return path, index_id, config_id


def test_oci_index_is_cryptographically_linked_to_scanned_config(tmp_path):
    path, index_id, config_id = make_archive(tmp_path)
    assert scan.exported_config_id(path, index_id) == config_id
    assert scan.exported_config_id(path, config_id) == config_id


@pytest.mark.parametrize("options", [{"corrupt": True}, {"wrong_link": True}, {"multiple": True}])
def test_corrupt_or_unrelated_export_is_rejected(tmp_path, options):
    path, index_id, _ = make_archive(tmp_path, **options)
    with pytest.raises(ValueError):
        scan.exported_config_id(path, index_id)
