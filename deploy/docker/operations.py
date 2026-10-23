"""Offline maintenance: fail closed on missing mounts and nonempty restore roots."""
import argparse
import os
import shutil
import uuid
from pathlib import Path

from family_finance.audit import AuditService
from family_finance.backup import BackupService
from family_finance.config import Settings


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["backup", "verify", "restore"])
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
    if args.action == "backup":
        if not AuditService(settings=settings).run().passed:
            raise SystemExit("Pre-backup audit failed")
        target = backups / ("familyfin-" + uuid.uuid4().hex)
        service.create(target)
        if not service.verify(target).passed:
            raise SystemExit("Backup verification failed")
        print(target.name)
        return
    if not args.snapshot or args.snapshot in {".", ".."} or Path(args.snapshot).name != args.snapshot:
        raise SystemExit("Snapshot must be a direct child name of /backups")
    snapshot = backups / args.snapshot
    if snapshot.is_symlink() or not service.verify(snapshot).passed:
        raise SystemExit("Snapshot verification failed")
    if args.action == "verify":
        print("Verified")
        return
    if any(root.iterdir()):
        raise SystemExit("Restore requires an empty, separately created data volume")
    # Never copy the old signing key. AuthService generates a replacement and
    # makes the restored sessions fail CSRF-secret validation at API startup.
    shutil.copytree(snapshot, root, dirs_exist_ok=True)
    (root / "manifest.json").unlink()
    if (root / "api-secret.key").exists():
        raise SystemExit("Unexpected signing key in snapshot")
    if not AuditService(settings=settings).run().passed:
        raise SystemExit("Restored application audit failed; preserve failed volume")
    print("Restored and audited; reauthentication required")


if __name__ == "__main__":
    main()
