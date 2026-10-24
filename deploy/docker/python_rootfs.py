"""Build-time CPython overlay for the pinned Debian 13 distroless base.

Keep the upstream interpreter/stdlib and working extension dependencies, without
shipping unrelated OS commands. Preserve Debian package/version/license records
for copied libraries so vulnerability scanners can still identify them.
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def dependencies(output):
    paths = []
    missing = []
    for line in output.splitlines():
        match = re.match(r"\s*\S+ => (/\S+) \(", line)
        if match:
            paths.append(Path(match[1]))
        elif "=> not found" in line:
            missing.append(line.strip().split()[0])
    return paths, missing


def canonical_library(path):
    # Debian 13 uses usrmerge. Resolve against the builder, not absolute symlinks
    # in the staged base (which would accidentally resolve against the builder).
    name = path.as_posix()
    return Path("/usr" + name) if name.startswith(("/lib/", "/lib64/")) else path


def run(*args):
    return subprocess.check_output(args, text=True)


def stage(base, destination):
    python_lib = Path("/usr/local/lib/python3.12")
    files = [Path("/usr/local/bin/python3.12"), Path("/usr/local/lib/libpython3.12.so.1.0")]
    files += sorted((python_lib / "lib-dynload").glob("*.so"))
    libraries = set()
    known_missing = {}
    for executable in files:
        paths, missing = dependencies(run("ldd", str(executable)))
        if missing:
            # Official python:slim already lacks Tk's GUI libraries. Preserve
            # that upstream limitation explicitly; never overlook a new one.
            if not executable.name.startswith("_tkinter.") or set(missing) != {"libtk8.6.so", "libtcl8.6.so"}:
                raise ValueError(f"Unresolved runtime libraries: {executable}: {missing}")
            known_missing[executable.name] = missing
        libraries.update(canonical_library(path) for path in paths)

    def copy(source, target=None):
        target = destination / (target or source).relative_to("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=True)

    copy(Path("/usr/local/bin/python3.12"))
    copy(Path("/usr/local/lib/libpython3.12.so.1.0"))
    for alias, target in (("/usr/local/bin/python", "python3.12"),
                          ("/usr/local/bin/python3", "python3.12"),
                          ("/usr/local/lib/libpython3.12.so", "libpython3.12.so.1.0")):
        (destination / alias.lstrip("/")).symlink_to(target)
    shutil.copytree(python_lib, destination / python_lib.relative_to("/"),
                    ignore=shutil.ignore_patterns("__pycache__", "ensurepip", "site-packages"))
    packages = set()
    evidence = []
    for library in sorted(libraries):
        if library.is_relative_to("/usr/local"):
            continue  # libpython was copied above.
        if (base / library.relative_to("/")).is_file():
            continue  # Keep the base's ABI-compatible libraries and inventory.
        copy(library)
        owner = run("dpkg-query", "-S", str(library)).strip().split(": ", 1)[0]
        if "\n" in owner:
            raise ValueError(f"Ambiguous library owner: {library}")
        packages.add(owner)
        evidence.append({"path": str(library), "package": owner,
                         "sha256": hashlib.sha256(library.read_bytes()).hexdigest()})
    status = destination / "var/lib/dpkg/status.d"
    status.mkdir(parents=True)
    for package in sorted(packages):
        (status / (package.replace(":", "_") + ".status")).write_text(run("dpkg-query", "-s", package))
        name = package.split(":")[0]
        copy(Path("/usr/share/doc") / name / "copyright")
    shutil.copytree("/usr/share/common-licenses", destination / "usr/share/common-licenses", dirs_exist_ok=True)
    manifest = destination / "usr/share/familyfin/python-runtime.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"python": sys.version, "copied_libraries": evidence,
                                    "upstream_unavailable_gui_libraries": known_missing}, indent=2) + "\n")


if __name__ == "__main__":
    stage(Path(sys.argv[1]), Path(sys.argv[2]))
