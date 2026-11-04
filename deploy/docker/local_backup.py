"""Simple verified Windows-local backups; seven owned archives, no external media."""
import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import backup_readiness
import manage
import portable_backup as portable
import portable_stream as transport

ARCHIVE = re.compile(r"familyfin-\d{8}T\d{6}Z-[0-9a-f]{32}\.tar")
IMAGE = re.compile(r"sha256:[0-9a-f]{64}")
KEEP = 7


def real_path(path):
    path = Path(path).absolute()
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise ValueError("Redirected backup paths are not supported")
    return path


def read_config(path):
    config = json.loads(real_path(path).read_text(encoding="utf-8-sig"))
    if (config.get("format") != 1
            or not re.fullmatch(r"familyfin-[a-z0-9-]+", config.get("project", ""))
            or not IMAGE.fullmatch(config.get("image", ""))
            or config.get("container_image") != config["image"]
            or not re.fullmatch(r"[0-9a-f]{32}", config.get("media_token", ""))):
        raise ValueError("Invalid local backup configuration")
    directory = real_path(config["directory"])
    marker = json.loads(real_path(directory / ".familyfin-local.json").read_text())
    if marker != {"format": 1, "owner": config["media_token"]}:
        raise ValueError("Backup folder ownership marker does not match")
    return config


def source(config):
    manage.engine()
    api = json.loads(portable.call(["docker", "inspect", config["project"] + "-api-1"]))[0]
    labels = api["Config"].get("Labels") or {}
    if (api["Image"] != config["image"]
            or labels.get("com.docker.compose.project") != config["project"]
            or labels.get("com.docker.compose.service") != "api"
            or not api["State"].get("Running")
            or api["State"].get("Health", {}).get("Status") != "healthy"):
        raise ValueError("Reviewed API release is missing, changed or unhealthy")
    volume = config["project"] + "_financial"
    mounts = [m for m in api["Mounts"] if m["Destination"] == "/var/lib/familyfin"]
    if len(mounts) != 1 or mounts[0]["Type"] != "volume" or mounts[0]["Name"] != volume:
        raise ValueError("API financial volume does not match the configured project")
    details = json.loads(portable.call(["docker", "volume", "inspect", volume]))[0]
    if (details["Driver"] != "local" or details.get("Options")
            or (details.get("Labels") or {}).get("com.docker.compose.project") != config["project"]):
        raise ValueError("Financial volume ownership mismatch")


@contextmanager
def scratch(config, *, name=None):
    name = name or "familyfin-local-stage-" + uuid.uuid4().hex
    exists = subprocess.run(["docker", "volume", "inspect", name], capture_output=True, check=False)
    if exists.returncode == 0:
        raise ValueError("Recovery/scratch volume already exists")
    portable.call(["docker", "volume", "create", "--label",
                   "familyfin.local.owner=" + config["media_token"], name])
    try:
        yield name
    finally:
        remove_volume(config, name)


def remove_volume(config, name):
    details = json.loads(portable.call(["docker", "volume", "inspect", name]))[0]
    if (not re.fullmatch(r"familyfin-local-(?:stage|recovery)-[0-9a-f]{32}", name)
            or (details.get("Labels") or {}).get("familyfin.local.owner") != config["media_token"]):
        raise ValueError("Refusing cleanup of an unrelated volume")
    portable.call(["docker", "volume", "rm", name])


def stream(config, volume, action, **options):
    command = portable.docker(config, [(volume, "/backups", action == "pack")],
                              interactive=action == "unpack")
    command += ["-c", portable.STREAM.read_text(encoding="utf-8"), action, "--image", config["image"]]
    for key, value in options.items():
        command += ["--" + key.replace("_", "-"), value]
    return command


@contextmanager
def staged(config, archive):
    archive = real_path(archive)
    if not archive.is_file() or not 0 < archive.stat().st_size <= 65 * 1024**3:
        raise ValueError("Invalid local archive")
    with scratch(config) as volume:
        token = uuid.uuid4().hex
        with archive.open("rb") as incoming:
            result = subprocess.run(stream(config, volume, "unpack", token=token),
                                    stdin=incoming, capture_output=True, check=False)
        if result.returncode:
            raise ValueError("Local archive extraction failed")
        metadata = json.loads(portable.call(stream(config, volume, "finalize", token=token)))
        yield volume, metadata


def checked_receipt(directory, receipt_path, owner):
    receipt_path = real_path(receipt_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    name = receipt_path.name.removesuffix(".receipt.json")
    if (not isinstance(receipt, dict) or not ARCHIVE.fullmatch(name) or receipt.get("archive") != name
            or receipt.get("owner") != owner or receipt.get("format") != 1):
        raise ValueError("Not an owned local backup receipt")
    archive = real_path(directory / name)
    if not archive.is_file() or portable.digest(archive) != receipt["sha256"]:
        raise ValueError("Backup hash mismatch")
    return archive, receipt


def prune(directory, owner):
    """Only verified, receipt-owned archive pairs are eligible for retention."""
    owned = []
    for path in directory.glob("*.tar.receipt.json"):
        # Unrelated/malformed files are preserved, never adopted for deletion.
        try:
            archive, receipt = checked_receipt(directory, path, owner)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        owned.append((archive.name, archive, path))
    removed = []
    for _, archive, receipt in sorted(owned, reverse=True)[KEEP:]:
        # Recheck immediately before deleting exact top-level owned filenames.
        checked_receipt(directory, receipt, owner)
        archive.unlink()
        receipt.unlink()
        removed.append(archive.name)
    return removed


def create_backup(config):
    source(config)
    directory = real_path(config["directory"])
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = directory / ("familyfin-" + stamp + "-" + uuid.uuid4().hex + ".tar")
    partial = target.with_suffix(".tar.partial")
    try:
        with scratch(config) as snapshots:
            command = portable.docker(config, [
                (config["project"] + "_financial", "/var/lib/familyfin", False),
                (snapshots, "/backups", False)])
            snapshot = portable.call(command + ["/app/deploy/docker/operations.py", "backup"]).decode().strip()
            transport.snapshot_name(snapshot)
            with partial.open("xb") as output:
                result = subprocess.run(stream(config, snapshots, "pack", snapshot=snapshot),
                                        stdout=output, stderr=subprocess.PIPE, check=False)
                if result.returncode:
                    raise RuntimeError("Local backup export failed")
                output.flush()
                os.fsync(output.fileno())
            archive_hash = portable.digest(partial)
            with staged(config, partial) as (_, metadata):
                if metadata["snapshot"] != snapshot:
                    raise ValueError("Verified snapshot identity mismatch")
            if portable.digest(partial) != archive_hash:
                raise ValueError("Archive changed after verification")
            partial.rename(target)
        receipt = {"format": 1, "owner": config["media_token"], "archive": target.name,
                   "sha256": archive_hash, "image": config["image"], "snapshot": snapshot,
                   "status": "PASS", "last_success_at": datetime.now(UTC).isoformat(),
                   "bytes": target.stat().st_size}
        portable.save_json(target.with_name(target.name + ".receipt.json"), receipt)
        receipt["pruned"] = prune(directory, config["media_token"])
        return receipt
    finally:
        if partial.exists():
            partial.unlink()


def current_backup(config, state):
    name = state.get("archive", "")
    if state.get("status") != "PASS" or not ARCHIVE.fullmatch(name):
        return False
    try:
        _, receipt = checked_receipt(Path(config["directory"]),
                                     Path(config["directory"]) / (name + ".receipt.json"),
                                     config["media_token"])
        return receipt["sha256"] == state.get("sha256")
    except (OSError, ValueError, KeyError, TypeError):
        return False


def restore(config, archive, *, check_only):
    manage.engine()
    with staged(config, archive) as (backups, metadata):
        target = "familyfin-local-recovery-" + uuid.uuid4().hex
        portable.call(["docker", "volume", "create", "--label",
                       "familyfin.local.owner=" + config["media_token"], target])
        try:
            command = portable.docker(config, [(target, "/var/lib/familyfin", False),
                                               (backups, "/backups", True)])
            portable.call(command + ["/app/deploy/docker/operations.py", "restore", metadata["snapshot"]])
            return {"status": "PASS", "restore_audit": "PASS", "reauthentication_required": True,
                    "test_volume_removed": check_only, "volume": None if check_only else target}
        finally:
            if check_only:
                remove_volume(config, target)
            # Actual recovery leaves the new volume intact, including on failure.
            # It is never attached to or substituted for the live financial volume.


def initialize(path, directory, project):
    path, directory = real_path(path), real_path(directory)
    if path.exists() or (directory.exists() and any(directory.iterdir())):
        raise ValueError("Initialize requires a new config and an empty dedicated backup folder")
    api = json.loads(portable.call(["docker", "inspect", project + "-api-1"]))[0]
    config = {"format": 1, "project": project, "image": api["Image"],
              "container_image": api["Image"], "directory": str(directory),
              "media_token": uuid.uuid4().hex}
    source(config)
    directory.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    portable.save_json(directory / ".familyfin-local.json",
                       {"format": 1, "owner": config["media_token"]})
    portable.save_json(path, config)
    return {"status": "CONFIGURED", "directory": str(directory), "keep": KEEP}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "run", "status", "verify", "restore-check", "restore"])
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--project", default="familyfin-m1-synthetic")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--if-due", action="store_true")
    parser.add_argument("--wait-ready", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "init":
        if not args.directory:
            parser.error("init requires --directory")
        manage.engine()
        print(json.dumps(initialize(args.config, args.directory, args.project)))
        return 0
    config = read_config(args.config)
    state_path = args.config.parent / "local-last-run.json"
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    if args.action == "status":
        healthy = current_backup(config, previous)
        print(json.dumps({"backup_available_and_hash_valid": healthy, "last_run": previous,
                          "directory": config["directory"], "keep": KEEP}))
        return 0 if healthy else 1
    if args.action in {"verify", "restore-check", "restore"}:
        if not args.archive:
            parser.error("archive operation requires --archive")
        if args.action == "verify":
            manage.engine()
            with staged(config, args.archive) as (_, metadata):
                result = {"status": "PASS", "snapshot": metadata["snapshot"]}
        else:
            result = restore(config, args.archive, check_only=args.action == "restore-check")
        print(json.dumps(result))
        return 0
    try:
        with portable.lock(args.config.parent / "local-backup.lock"):
            # Reload only after acquiring the process lock.
            previous = json.loads(state_path.read_text()) if state_path.exists() else {}
            if (args.if_due and not portable.scheduled_backup_due(previous)
                    and current_backup(config, previous)):
                print(json.dumps({"status": "SKIPPED", "reason": "Verified backup covers this local day"}))
                return 0
            if args.wait_ready:
                backup_readiness.wait_ready(config)
            result = create_backup(config)
            portable.save_json(state_path, result)
    except Exception as exc:  # noqa: BLE001 -- Scheduled jobs must record every failure.
        # Preserve details privately, without printing child command output/data.
        result = {"status": "FAIL", "checked_at": datetime.now(UTC).isoformat(),
                  "failure_type": type(exc).__name__, "last_success_at": previous.get("last_success_at")}
        portable.save_json(state_path, result)
        print(json.dumps(result), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
