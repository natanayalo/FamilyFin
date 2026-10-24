"""Promote the tested security-review images into the two existing synthetic labs.

Local labs only. Preserve previous images, verified backups and failure evidence;
never automatically downgrade a database, delete a volume, or modify Serve.
"""
import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import manage
import validate
from lab_profile import require_lab_python

require_lab_python()


def image_id(reference):
    return json.loads(manage.run("docker", "image", "inspect", reference).stdout)[0]["Id"]


def save(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def backup(project):
    name = manage.compose(project, "run", "--rm", "--no-deps", "--pull", "never",
                          "operations", "operations", "backup").stdout.strip().splitlines()[-1]
    assert name.startswith("familyfin-") and "/" not in name
    manage.compose(project, "run", "--rm", "--no-deps", "--pull", "never",
                   "operations", "operations", "verify", name)
    return name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-directory", required=True, type=Path)
    args = parser.parse_args()
    manage.engine()
    tested = args.evidence_directory
    images = json.loads((tested / "tested-images.json").read_text(encoding="utf-8"))
    configs = json.loads((tested / "tested-configs.json").read_text(encoding="utf-8"))
    drill = json.loads((tested / "synthetic-validation.json").read_text(encoding="utf-8"))
    assert sum(r["status"] == "PASS" for r in drill["results"]) == 8
    assert not any(r["status"] == "FAIL" for r in drill["results"])
    preservation = json.loads((tested / "cleanup-and-preservation.json").read_text(encoding="utf-8"))
    assert preservation["existing_containers_and_serve_unchanged"]
    for name, identity in images.items():
        assert image_id(f"familyfin-m1-{name}:security-review") == identity
        scan = json.loads((manage.REPORTS / f"trivy-familyfin-m1-{name}-security-review-summary.json").read_text(encoding="utf-8"))
        assert scan["docker_image_id"] == identity and scan["image_id"] == configs[name]
    before = manage.baseline()
    expected = json.loads((manage.STATE / "baseline.json").read_text(encoding="utf-8"))
    assert manage.baseline_equal(expected, before), "Resolve unrelated service/Serve drift first"
    fixture = json.loads((manage.REPORTS / "restored-state-comparison.json").read_text(encoding="utf-8"))
    assert fixture["status"] == "PASS"
    for project in manage.PROJECTS:
        manage.assert_owned(project)
        manage.verify(project)
        # No adoption of a real-data project based on its name alone.
        # Application backups deliberately omit this lab-only marker, so the
        # recovered lab is identified by the recorded fixture fingerprint too.
        if project == "familyfin-m1-synthetic":
            validate.execute(project, "from pathlib import Path; assert (Path('/var/lib/familyfin')/'.synthetic-lab').read_text() == 'Disposable FamilyFin M1 validation only'")
        current = validate.status(project)
        assert current["financial_sha256"] == fixture["financial_values_sha256"]
        assert current["migrations"] == fixture["migration"]
        assert len(current["archives"]) == fixture["archive_count"]
        validate.execute(project, "import sqlite3; c=sqlite3.connect('/var/lib/familyfin/family_finance.sqlite3'); assert sorted(r[0] for r in c.execute('SELECT username FROM api_users')) == ['qa-one','qa-two']")
        assert current["counts"]["api_users"] == 2
        assert current["counts"]["transactions"] == 1
        assert current["counts"]["source_files"] == 1
        assert current["counts"]["net_worth_accounts"] == 2
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    directory = manage.REPORTS / f"reviewed-rollout-{stamp}"
    directory.mkdir(exist_ok=False)
    receipt = {"status": "IN_PROGRESS", "checked_at": datetime.now(UTC).isoformat(),
               "scope": "Existing synthetic labs only; no origin, Serve or household changes",
               "tested_images": images, "previous_images": {}, "projects": {}}
    save(directory / "receipt.json", receipt)
    try:
        for name in images:
            previous = image_id(f"familyfin-m1-{name}:local")
            alias = f"familyfin-m1-{name}:before-review-{stamp.lower()}"
            manage.run("docker", "image", "tag", previous, alias)
            assert image_id(alias) == previous
            receipt["previous_images"][name] = {"id": previous, "retained_tag": alias}
        for project in manage.PROJECTS:
            initial = validate.status(project)
            snapshot = backup(project)
            assert validate.status(project) == initial
            receipt["projects"][project] = {"before": initial, "pre_update_snapshot": snapshot}
            save(directory / "receipt.json", receipt)
        # These aliases are local lab convenience names, never production releases.
        for name, identity in images.items():
            assert image_id(f"familyfin-m1-{name}:security-review") == identity
            manage.run("docker", "image", "tag", identity, f"familyfin-m1-{name}:local")
        for project in manage.PROJECTS:
            manage.compose(project, "up", "-d", "--no-build", "--pull", "never",
                           "--wait", "--wait-timeout", "180")
            detail = receipt["projects"][project]
            assert validate.status(project) == detail["before"], "Application state changed"
            detail["verification"] = manage.verify(project)
            for item in manage.inspect_all():
                labels = item["Config"].get("Labels") or {}
                if labels.get("com.docker.compose.project") == project:
                    name = labels["com.docker.compose.service"]
                    assert item["Image"] in {images[name], configs[name]}
            detail["post_update_snapshot"] = backup(project)
            assert validate.status(project) == detail["before"]
            port = manage.PROJECTS[project]
            for path in ("/api/v1/auth/session", "/api/v1/net-worth/accounts", "/api/v1/planning/scenarios"):
                assert manage.request(port, path)[0] == 401
            for origin in (None, "https://attacker.example"):
                assert manage.request(port, "/api/v1/auth/session", "POST",
                                      data={"username": "qa-one", "password": "invalid"}, origin=origin)[0] == 403
            detail["unauthenticated_and_origin_boundaries"] = "PASS"
            detail["state_preserved_before_auth_probes"] = True
            save(directory / "receipt.json", receipt)
            print(f"PASS {project}: reviewed images, preserved state, health/isolation/headers, verified backups and auth boundaries", flush=True)
        assert manage.baseline_equal(before, manage.baseline()), "Unrelated service or Serve changed"
        receipt["unrelated_services_and_serve_unchanged"] = True
        receipt["status"] = "PASS"
        receipt["limits"] = ["Positive two-user login/CSRF/logout/restore evidence is the exact-image fresh drill; existing lab passwords were discarded",
                             "Same-disk logical backups only; no independent encrypted-media acceptance",
                             "Residual scan findings remain; no mobile, remote-peer or reboot acceptance"]
    except BaseException as exc:
        receipt["status"] = "FAIL"
        receipt["error"] = str(exc)
        receipt["recovery"] = "Preserve volumes. Inspect migration state before considering old code; restore the verified pre-update snapshot into a clean project with retained images if needed. No automatic downgrade."
        raise
    finally:
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        save(directory / "receipt.json", receipt)
    print(str(directory / "receipt.json"))


if __name__ == "__main__":
    main()
