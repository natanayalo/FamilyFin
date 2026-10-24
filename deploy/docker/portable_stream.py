"""Container-side bounded archive transport. Never extracts onto the Windows host.

Decrypted staging is deliberately unusable until the host observes both the age
and receiver exit codes, then explicitly finalizes application verification.
"""
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import tarfile
from pathlib import Path, PurePosixPath

MAX_BYTES = 64 * 1024**3
MAX_FILES = 100_000


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or "\\" in name or ":" in name
            or any(part in {"", ".", ".."} for part in name.split("/"))
            or path.name in {"api-secret.key", ".synthetic-lab"}):
        raise ValueError("Unsafe or secret archive member")
    return path


def snapshot_name(value):
    if not re.fullmatch(r"familyfin-[0-9a-f]{32}", value):
        raise ValueError("Invalid snapshot identity")
    return value


def bundle(value, image):
    if (set(value) != {"format", "snapshot", "image"} or value["format"] != 1
            or value["image"] != image):
        raise ValueError("Wrong backup format or release; select the matching reviewed image")
    snapshot_name(value["snapshot"])
    return value


def verify(root):
    from family_finance.backup import BackupService
    from family_finance.config import Settings
    if not BackupService(settings=Settings.from_environment()).verify(root).passed:
        raise ValueError("Application backup verification failed")


def pack(root, name, image, output):
    source = root / snapshot_name(name)
    verify(source)
    metadata = json.dumps({"format": 1, "snapshot": name, "image": image}).encode()
    # PAX preserves original automation filenames, including long UTF-8 paths.
    # Construct headers ourselves so only path/size extensions can be generated;
    # no source ownership, timestamps or other filesystem metadata is exported.
    with tarfile.open(fileobj=output, mode="w|", format=tarfile.PAX_FORMAT) as archive:
        info = tarfile.TarInfo("bundle.json")
        info.size = len(metadata)
        info.mode = 0o600
        archive.addfile(info, io.BytesIO(metadata))
        count = total = 0
        for path in sorted(source.rglob("*")):
            mode = path.lstat().st_mode
            relative = path.relative_to(source).as_posix()
            safe_name(relative)
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode) or path.stat().st_nlink != 1:
                raise ValueError("Only independent regular files may be exported")
            count += 1
            total += path.stat().st_size
            if count > MAX_FILES or total > MAX_BYTES:
                raise ValueError("Backup exceeds configured transport limits")
            info = tarfile.TarInfo("snapshot/" + relative)
            info.size = path.stat().st_size
            info.mode = 0o600
            with path.open("rb") as data:
                archive.addfile(info, data)


def unpack(root, image, token, incoming):
    if any(root.iterdir()):
        raise ValueError("Decryption requires a newly created empty staging volume")
    (root / ".incomplete").write_text(token)
    count = total = 0
    seen = set()
    metadata = None
    with tarfile.open(fileobj=incoming, mode="r|") as archive:
        for info in archive:
            count += 1
            if count > MAX_FILES + 1 or not info.isreg() or info.sparse is not None:
                raise ValueError("Unsupported archive member or file count")
            name = safe_name(info.name)
            if info.name in seen or info.size < 0:
                raise ValueError("Duplicate or invalid member")
            seen.add(info.name)
            total += info.size
            if total > MAX_BYTES:
                raise ValueError("Archive exceeds size limit")
            source = archive.extractfile(info)
            if info.name == "bundle.json":
                if metadata is not None or count != 1 or info.size > 4096:
                    raise ValueError("Invalid transport metadata")
                metadata = bundle(json.loads(source.read()), image)
                target = root / metadata["snapshot"]
                target.mkdir(mode=0o700)
                (root / ".bundle.json").write_text(json.dumps(metadata))
                continue
            if metadata is None or len(name.parts) < 2 or name.parts[0] != "snapshot":
                raise ValueError("Unexpected archive layout")
            destination = target.joinpath(*name.parts[1:])
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with destination.open("xb") as output:
                remaining = info.size
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("Truncated archive")
                    output.write(chunk)
                    remaining -= len(chunk)
            destination.chmod(0o600)
    # Drain past the tar trailer so the decryptor authenticates the final chunk.
    # Nonzero age exit still leaves .incomplete, even if all tar files were valid.
    while incoming.read(1024 * 1024):
        pass
    if metadata is None or count < 3:
        raise ValueError("Incomplete backup bundle")


def finalize(root, image, token):
    if (root / ".incomplete").read_text() != token or (root / ".verified").exists():
        raise ValueError("Wrong staging identity or already finalized")
    metadata = bundle(json.loads((root / ".bundle.json").read_text()), image)
    verify(root / metadata["snapshot"])
    (root / ".incomplete").rename(root / ".verified")
    print(json.dumps(metadata | {"manifest_sha256": hashlib.sha256((root / metadata["snapshot"] / "manifest.json").read_bytes()).hexdigest()}))


def remove_exported(root, name, manifest_sha256):
    """Remove one exported snapshot; never traverse a link or prune siblings."""
    name = snapshot_name(name)
    if not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256 or "") or not shutil.rmtree.avoids_symlink_attacks:
        raise ValueError("Verified manifest and descriptor-safe deletion required")
    source = root / name
    before = source.lstat()
    if not stat.S_ISDIR(before.st_mode):
        raise ValueError("Snapshot must be a real directory")
    for path in source.rglob("*"):
        info = path.lstat()
        safe_name(path.relative_to(source).as_posix())
        if not stat.S_ISDIR(info.st_mode) and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise ValueError("Unsafe snapshot entry; preserve for investigation")
    if hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest() != manifest_sha256:
        raise ValueError("Snapshot differs from the verified encrypted export")
    verify(source)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("Snapshot changed before cleanup")
        shutil.rmtree(name, dir_fd=descriptor)
    finally:
        os.close(descriptor)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("pack", "unpack", "finalize", "require-verified", "remove-exported"))
    parser.add_argument("--image", required=True)
    parser.add_argument("--snapshot")
    parser.add_argument("--token")
    parser.add_argument("--manifest-sha256")
    args = parser.parse_args()
    os.umask(0o077)
    root = Path("/backups")
    if not os.path.ismount(root):
        raise ValueError("Explicit backup-volume mount required")
    if args.action == "pack":
        pack(root, args.snapshot, args.image, sys.stdout.buffer)
    elif args.action == "unpack":
        unpack(root, args.image, args.token, sys.stdin.buffer)
    elif args.action == "finalize":
        finalize(root, args.image, args.token)
    elif args.action == "remove-exported":
        remove_exported(root, args.snapshot, args.manifest_sha256)
    else:
        if (root / ".incomplete").exists() or (root / ".verified").read_text() != args.token:
            raise ValueError("Staging is not authenticated and verified for this run")
        metadata = bundle(json.loads((root / ".bundle.json").read_text()), args.image)
        verify(root / metadata["snapshot"])
        print(json.dumps(metadata))


if __name__ == "__main__":
    main()
