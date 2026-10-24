"""Local image evidence, without a Docker socket or application mounts in Trivy.

Default exit status fails on any HIGH/CRITICAL result, including unfixed issues.
--record-only saves evidence without treating a successful scan as acceptance.
No registry upload or automatic ignore/exception list is used.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import tarfile

import manage

SCANNER = "aquasec/trivy@sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c"


def exported_config_id(archive: Path, identity: str) -> str:
    """Verify the OCI index -> manifest -> config chain, without extracting.

    Containerd-backed Docker reports an index ID; Trivy reports the config ID.
    Classic Docker may report the config ID directly. Never compare these two
    different identifiers as if they were interchangeable.
    """
    with tarfile.open(archive) as saved:
        def read(name):
            entry = saved.getmember(name)
            if not entry.isfile() or entry.size > 4 * 1024 * 1024:
                raise ValueError("Invalid image metadata member")
            return saved.extractfile(entry).read()

        manifest = json.loads(read("manifest.json"))
        if len(manifest) != 1:
            raise ValueError("Expected exactly one platform image")
        config = read(manifest[0]["Config"])
        config_id = "sha256:" + hashlib.sha256(config).hexdigest()
        if identity == config_id:
            return config_id

        index = json.loads(read("index.json"))
        roots = [d for d in index["manifests"] if d["digest"] == identity]
        if len(roots) != 1:
            raise ValueError("Export does not contain the selected Docker identity")

        def linked(descriptor):
            digest = descriptor["digest"]
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise ValueError("Unsupported image descriptor digest")
            data = read("blobs/sha256/" + digest.split(":")[1])
            if "sha256:" + hashlib.sha256(data).hexdigest() != digest:
                raise ValueError("Image metadata digest mismatch")
            node = json.loads(data)
            if node.get("config", {}).get("digest") == config_id:
                return True
            return any(linked(child) for child in node.get("manifests", []))

        if not linked(roots[0]):
            raise ValueError("Selected Docker identity does not reference the scanned config")
        return config_id


def summarize(report: dict) -> dict:
    if report.get("SchemaVersion") != 2 or not isinstance(report.get("Results"), list) or not report["Results"]:
        raise ValueError("Missing or unsupported scanner results")
    if not report.get("Metadata", {}).get("ImageID"):
        raise ValueError("Missing scanned image identity")
    sections = []
    blocking = []
    for section in report["Results"]:
        # A successful target with no vulnerabilities may omit this member.
        issues = section.get("Vulnerabilities") or []
        if not isinstance(issues, list):
            raise ValueError("Invalid vulnerability collection")
        counts = Counter()
        for issue in issues:
            severity = issue.get("Severity", "UNKNOWN")
            if severity not in {"LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"}:
                raise ValueError("Unknown severity vocabulary")
            counts[severity] += 1
            if severity in {"HIGH", "CRITICAL", "UNKNOWN"}:
                blocking.append({"target": section["Target"], **{
                    key: issue.get(key) for key in (
                        "VulnerabilityID", "PkgName", "InstalledVersion", "FixedVersion", "Severity", "Status", "PrimaryURL"
                    )}})
        sections.append({"target": section["Target"], "type": section.get("Type"), "counts": dict(counts)})
    return {"image_id": report["Metadata"]["ImageID"], "sections": sections,
            "status": "FAIL" if blocking else "PASS", "blocking": blocking}


def scan(image: str) -> dict:
    if not re.fullmatch(r"familyfin-m1-(api|web|caddy):[a-zA-Z0-9_.-]+", image):
        raise ValueError("Only locally tagged FamilyFin images can be scanned by this helper")
    scratch = manage.STATE / "security-scans"
    scratch.mkdir(parents=True, exist_ok=True)
    cache = scratch / "trivy-cache"
    cache.mkdir(exist_ok=True)
    label = image.replace(":", "-")
    archive = scratch / (label + ".tar")
    identity = json.loads(manage.run("docker", "image", "inspect", image).stdout)[0]["Id"]
    manage.run("docker", "image", "save", "--output", str(archive), identity)
    config_id = exported_config_id(archive, identity)
    result = manage.run("docker", "run", "--rm", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--user", "10004:10004", "--memory", "2g",
        "--cpus", "2", "--pids-limit", "128", "--tmpfs", "/tmp:size=512m,mode=1777",
        "--mount", f"type=bind,source={archive},target=/input.tar,readonly",
        "--mount", f"type=bind,source={cache},target=/cache", SCANNER,
        "--cache-dir", "/cache", "image", "--input", "/input.tar", "--scanners", "vuln",
        "--skip-java-db-update", "--format", "json", "--quiet", "--timeout", "15m")
    report = json.loads(result.stdout)
    summary = summarize(report)
    manage.REPORTS.mkdir(exist_ok=True)
    target = manage.REPORTS / ("trivy-" + label + ".json")
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if summary["image_id"] != config_id:
        raise ValueError("Scanner identity does not match the verified exported image config")
    summary.update(image=image, docker_image_id=identity, scanner=SCANNER, report=target.name,
                   report_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    (manage.REPORTS / ("trivy-" + label + "-summary.json")).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+")
    parser.add_argument("--record-only", action="store_true")
    args = parser.parse_args()
    manage.engine()
    summaries = [scan(image) for image in args.images]
    for result in summaries:
        print(json.dumps({key: result[key] for key in ("image", "image_id", "status", "sections", "report")}))
    return 0 if args.record_only or all(s["status"] == "PASS" for s in summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
