"""Offline maintenance: fail closed on missing mounts and nonempty restore roots."""
import argparse
import json
import os
import shutil
import stat
import uuid
from pathlib import Path

from family_finance.audit import AuditService
from family_finance.backup import BackupService
from family_finance.config import Settings

RESERVED = {"api-secret.key", ".restore-incomplete", ".restore-staging"}
MAX_SNAPSHOTS = 32
MAX_BACKUP_BYTES = 16 * 1024**3
MIN_FREE_BYTES = 8 * 1024**3


def snapshot_tree(root, *, allow_staging_root=False):
    """Inspect every entry without following links, before any restore writes."""
    pending = [root]
    while pending:
        path = pending.pop()
        info = path.lstat()
        if path.name in RESERVED and not (allow_staging_root and path == root and path.name == ".restore-staging"):
            raise ValueError("Signing key or reserved restore marker in snapshot")
        if stat.S_ISDIR(info.st_mode):
            pending.extend(path.iterdir())
        elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Snapshot requires independent regular files and directories")


def copy_snapshot(source, destination):
    """Linux descriptor-relative copy: never follow a substituted source link."""
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    def directory(descriptor, target):
        with os.scandir(descriptor) as entries:
            for entry in entries:
                if entry.name in RESERVED:
                    raise ValueError("Reserved file in restore source")
                info = entry.stat(follow_symlinks=False)
                output = target / entry.name
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(entry.name, directory_flags, dir_fd=descriptor)
                    try:
                        output.mkdir(mode=0o700)
                        directory(child, output)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    child = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
                    with os.fdopen(child, "rb") as incoming:
                        before = os.fstat(incoming.fileno())
                        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                            raise ValueError("Restore source is not an independent regular file")
                        with output.open("xb") as outgoing:
                            shutil.copyfileobj(incoming, outgoing)
                        after = os.fstat(incoming.fileno())
                        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                            raise ValueError("Restore source changed during copy")
                    output.chmod(0o600)
                else:
                    raise ValueError("Unsupported restore source entry")

    descriptor = os.open(source, directory_flags)
    try:
        directory(descriptor, destination)
    finally:
        os.close(descriptor)


def inventory(backups):
    snapshots = []
    for path in sorted(backups.iterdir()):
        snapshot_tree(path)
        size = sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) if path.is_dir() else path.stat().st_size
        snapshots.append({"name": path.name, "bytes": size})
    return {"snapshots": snapshots, "count": len(snapshots),
            "total_bytes": sum(item["bytes"] for item in snapshots),
            "free_bytes": shutil.disk_usage(backups).free}


def check_backup_capacity(backups):
    usage = inventory(backups)
    if usage["count"] >= MAX_SNAPSHOTS or usage["total_bytes"] >= MAX_BACKUP_BYTES or usage["free_bytes"] < MIN_FREE_BYTES:
        raise SystemExit("Backup capacity limit reached; review inventory and retention before another snapshot")
    return usage


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["backup", "verify", "restore", "inventory"])
    parser.add_argument("snapshot", nargs="?")
    args = parser.parse_args(argv)
    os.umask(0o077)
    settings = Settings.from_environment()
    root = settings.data_root.resolve()
    backups = Path("/backups")
    if not os.path.ismount(root) or not os.path.ismount(backups):
        raise SystemExit("Data and backup roots must be separate mounted volumes")
    if root == backups or root in backups.parents or backups in root.parents:
        raise SystemExit("Backup and data roots overlap")
    service = BackupService(settings=settings)
    if args.action == "inventory":
        print(json.dumps(inventory(backups)))
        return
    if args.action == "backup":
        if not AuditService(settings=settings).run().passed:
            raise SystemExit("Pre-backup audit failed")
        check_backup_capacity(backups)
        target = backups / ("familyfin-" + uuid.uuid4().hex)
        service.create(target)
        if not service.verify(target).passed:
            raise SystemExit("Backup verification failed")
        print(target.name)
        return
    if not args.snapshot or args.snapshot in {".", ".."} or Path(args.snapshot).name != args.snapshot:
        raise SystemExit("Snapshot must be a direct child name of /backups")
    snapshot = backups / args.snapshot
    if args.action == "restore" and any(root.iterdir()):
        raise SystemExit("Restore requires an empty, separately created data volume")
    try:
        snapshot_tree(snapshot)
    except (OSError, ValueError) as exc:
        raise SystemExit("Snapshot verification failed: unsafe or missing entries") from exc
    if not service.verify(snapshot).passed:
        raise SystemExit("Snapshot verification failed")
    if args.action == "verify":
        print("Verified")
        return
    # Never copy the old signing key. AuthService generates a replacement and
    # makes the restored sessions fail CSRF-secret validation at API startup.
    # Recheck after application verification, then copy through no-follow Linux
    # descriptors into staging. Reverify the copied bytes before publishing them.
    snapshot_tree(snapshot)
    marker = root / ".restore-incomplete"
    marker.write_text("Restore in progress; do not start this volume")
    staging = root / ".restore-staging"
    staging.mkdir(mode=0o700)
    copy_snapshot(snapshot, staging)
    snapshot_tree(staging, allow_staging_root=True)
    if not service.verify(staging).passed:
        raise SystemExit("Copied snapshot verification failed; preserve failed volume")
    for item in staging.iterdir():
        item.rename(root / item.name)
    staging.rmdir()
    (root / "manifest.json").unlink()
    if (root / "api-secret.key").exists():
        raise SystemExit("Unexpected signing key in snapshot")
    if not AuditService(settings=settings).run().passed:
        raise SystemExit("Restored application audit failed; preserve failed volume")
    marker.unlink()
    print("Restored and audited; reauthentication required")


if __name__ == "__main__":
    main()
