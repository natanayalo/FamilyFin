"""Fresh, synthetic-only candidate drill; existing labs and Serve are preserved.

Uses localhost 8092/8093 and :security-review images. Refuses existing financial
volumes, runs the complete original drill, then removes only these candidate
containers/networks. Volumes/evidence remain for inspection; no volume deletion.
"""
import argparse
import functools
import json

import manage
import validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", type=int, choices=range(1, 10), default=1)
    attempt = parser.parse_args().attempt
    suffix = "" if attempt == 1 else f"-{attempt}"
    projects = {"familyfin-m1-security-review": 8092, "familyfin-m1-security-recovery": 8093}
    projects = {name + suffix: port for name, port in projects.items()}
    manage.engine()
    for project in projects:
        manage.assert_owned(project)
        for volume_suffix in ("financial", "backups"):
            if manage.run("docker", "volume", "inspect", f"{project}_{volume_suffix}", check=False).returncode == 0:
                raise SystemExit("Fresh candidate volumes required; preserve existing evidence and data")
        if manage.run("docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}").stdout.strip():
            raise SystemExit("Candidate project already exists; refusing to adopt it")
    # The shared verifier now treats both original labs as unrelated services,
    # so their IDs, configuration and start times must remain identical too.
    manage.PROJECTS = validate.PROJECTS = projects
    validate.PRIMARY, validate.RESTORED = projects
    manage.REPORTS = validate.REPORTS = manage.ROOT / "reports" / ("security-review" + suffix)
    manage.STATE = validate.STATE = manage.ROOT / ".state" / ("security-review" + suffix)
    manage.REPORTS.mkdir(parents=True, exist_ok=True)
    manage.STATE.mkdir(parents=True, exist_ok=True)
    validate.compose = functools.partial(manage.compose, image_tag="security-review")
    identities = {name: json.loads(manage.run("docker", "image", "inspect",
                  f"familyfin-m1-{name}:security-review").stdout)[0]["Id"] for name in ("api", "web", "caddy")}
    configs = {}
    for name in identities:
        scan = json.loads((manage.ROOT / "reports" / f"trivy-familyfin-m1-{name}-security-review-summary.json").read_text(encoding="utf-8"))
        if scan["docker_image_id"] != identities[name]:
            raise SystemExit("Current candidate must have matching scan evidence before validation")
        configs[name] = scan["image_id"]
    before = manage.baseline()
    try:
        validate.main()
        for name, identity in identities.items():
            current = json.loads(manage.run("docker", "image", "inspect", f"familyfin-m1-{name}:security-review").stdout)[0]["Id"]
            assert current == identity, "Candidate tag changed during validation"
        for item in manage.inspect_all():
            labels = item["Config"].get("Labels") or {}
            if labels.get("com.docker.compose.project") in projects:
                name = labels["com.docker.compose.service"]
                # Engine's containerd store reports the index here; classic
                # storage reports the config. The scanner verified their link.
                assert item["Image"] in {identities[name], configs[name]}, "Running image differs from scan evidence"
        (manage.REPORTS / "tested-images.json").write_text(json.dumps(identities, indent=2), encoding="utf-8")
        (manage.REPORTS / "tested-configs.json").write_text(json.dumps(configs, indent=2), encoding="utf-8")
    finally:
        for project in projects:
            manage.assert_owned(project)
            validate.compose(project, "down")
        unchanged = manage.baseline_equal(before, manage.baseline())
        (manage.REPORTS / "cleanup-and-preservation.json").write_text(json.dumps({
            "existing_containers_and_serve_unchanged": unchanged,
            "candidate_containers_and_networks_removed": True,
            "candidate_volumes_retained": True,
        }, indent=2), encoding="utf-8")
        assert unchanged, "Existing container or Serve drift during candidate drill"


if __name__ == "__main__":
    main()
