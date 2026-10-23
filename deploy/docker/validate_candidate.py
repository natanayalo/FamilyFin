"""Fresh localhost candidate/clean-restore drill; no trial or Serve promotion.

Only newly named lab volumes on 8092/8093 are used. All existing containers and
Serve are compared before/after. Owned candidate containers/networks are removed;
volumes and private evidence remain. Raw scanner failures are never waived here.
"""
import argparse
import functools
import json
import re
import socket

import manage
import validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"candidate-[a-z0-9][a-z0-9.-]{0,63}", args.tag) or not re.fullmatch(r"[a-z0-9-]{1,32}", args.run_id):
        raise ValueError("Explicit candidate tag and unique lowercase run ID required")
    projects = {"familyfin-m1-candidate-" + args.run_id: 8092,
                "familyfin-m1-candidate-restore-" + args.run_id: 8093}
    manage.engine()
    for project, port in projects.items():
        manage.assert_owned(project)
        for suffix in ("financial", "backups"):
            if manage.run("docker", "volume", "inspect", project + "_" + suffix, check=False).returncode == 0:
                raise ValueError("Fresh candidate volumes required; never reuse previous data")
        if manage.run("docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + project).stdout.strip():
            raise ValueError("Candidate project already exists")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))
    images = {}
    configs = {}
    scans = {}
    for service in ("api", "web", "caddy"):
        image = f"familyfin-m1-{service}:{args.tag}"
        identity = json.loads(manage.run("docker", "image", "inspect", image).stdout)[0]["Id"]
        scan = json.loads((manage.REPORTS / ("trivy-" + image.replace(":", "-") + "-summary.json")).read_text())
        if scan["docker_image_id"] != identity:
            raise ValueError("Candidate scan identity mismatch")
        images[service] = identity
        configs[service] = scan["image_id"]
        scans[service] = scan["status"]
    manage.PROJECTS = validate.PROJECTS = projects
    before = manage.baseline()
    validate.PRIMARY, validate.RESTORED = projects
    manage.REPORTS = validate.REPORTS = manage.ROOT / "reports" / ("candidate-" + args.run_id)
    manage.STATE = validate.STATE = manage.ROOT / ".state" / ("candidate-" + args.run_id)
    if manage.STATE.exists() or manage.REPORTS.exists():
        raise ValueError("Fresh private evidence directories required")
    manage.STATE.mkdir(parents=True)
    manage.REPORTS.mkdir(parents=True)
    validate.compose = functools.partial(manage.compose, image_tag=args.tag)
    try:
        validate.main()
        for service, identity in images.items():
            current = json.loads(manage.run("docker", "image", "inspect", f"familyfin-m1-{service}:{args.tag}").stdout)[0]["Id"]
            if current != identity:
                raise ValueError("Candidate image tag changed during validation")
        for item in manage.inspect_all():
            labels = item["Config"].get("Labels") or {}
            if labels.get("com.docker.compose.project") in projects:
                service = labels["com.docker.compose.service"]
                if item["Image"] not in (images[service], configs[service]):
                    raise ValueError("Running candidate differs from scanned image")
        (manage.REPORTS / "tested-images.json").write_text(json.dumps(images, indent=2))
        (manage.REPORTS / "tested-configs.json").write_text(json.dumps(configs, indent=2))
    finally:
        for project in projects:
            manage.assert_owned(project)
            validate.compose(project, "down")
        unchanged = manage.baseline_equal(before, manage.baseline())
        summary = {"existing_services_and_Serve_unchanged": unchanged,
                   "candidate_containers_networks_removed": True, "candidate_volumes_retained": True,
                   "images": images, "raw_scan_status": scans, "promoted": False,
                   "scope": "Local synthetic candidate only; no private endpoint or security exception changed"}
        (manage.REPORTS / "cleanup-and-preservation.json").write_text(json.dumps(summary, indent=2))
        if not unchanged:
            raise ValueError("Existing services or Serve drifted")


if __name__ == "__main__":
    main()
