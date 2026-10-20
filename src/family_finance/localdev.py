"""Native, disconnected development tooling. Run through the repository's ./dev."""

from __future__ import annotations

import argparse
import fcntl
import getpass
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import closing, contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
DATA = ROOT / "data" / "dev-local"
BACKUPS = ROOT / "data" / "dev-backups"
PYTHON = ROOT / ".venv" / "bin" / "python"
NODE_VERSION = (ROOT / ".nvmrc").read_text().strip()
MARKER = ".familyfin-development"


def local_environment(
    data_root: Path = DATA, *, web_port: int = 3000, api_port: int = 8000
) -> dict[str, str]:
    """Override inherited production paths, origin, proxy, and migration settings."""
    env = os.environ.copy()
    env.update(
        {
            "FAMILY_FINANCE_LOCAL_DEV": "1",
            "FAMILY_FINANCE_DATA_ROOT": str(data_root.resolve()),
            "FAMILY_FINANCE_DATABASE_URL": f"sqlite:///{data_root.resolve()}/family_finance.sqlite3",
            "FAMILY_FINANCE_AUTOMATION_BACKUP_ROOT": str(BACKUPS),
            "FAMILY_FINANCE_API_PUBLIC_ORIGIN": f"http://127.0.0.1:{web_port}",
            "FAMILY_FINANCE_API_TRUSTED_HOSTS": "127.0.0.1,localhost",
            "FAMILY_FINANCE_API_PORT": str(api_port),
            "NEXT_TELEMETRY_DISABLED": "1",
            "DO_NOT_TRACK": "1",
            "UV_OFFLINE": "1",
            "UV_NO_SYNC": "1",
            "npm_config_offline": "true",
            "npm_config_audit": "false",
            "npm_config_fund": "false",
            "NO_PROXY": "127.0.0.1,localhost,::1",
            "no_proxy": "127.0.0.1,localhost,::1",
        }
    )
    env.pop("NODE_ENV", None)
    env.pop("NODE_OPTIONS", None)
    return env


@contextmanager
def scoped_environment(env: dict[str, str]):
    original = os.environ.copy()
    os.environ.clear()
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def require_versions() -> None:
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Python 3.12 is required. Install it, then rerun ./dev setup.")
    if not shutil.which("node") or not shutil.which("npm"):
        raise RuntimeError(f"Node {NODE_VERSION} and npm are required (see .nvmrc).")
    version = subprocess.check_output(["node", "--version"], text=True).strip().lstrip("v")
    if version != NODE_VERSION:
        raise RuntimeError(
            f"Node {NODE_VERSION} is required; found {version}. Use nvm install && nvm use, "
            "or put the pinned Node installation on PATH."
        )


def require_dependencies() -> None:
    require_versions()
    if not PYTHON.is_file() or not (FRONTEND / "node_modules/.bin/next").is_file():
        raise RuntimeError("Dependencies are missing. Run ./dev setup while connected first.")


def run(command: list[str], env: dict[str, str], *, cwd: Path = ROOT) -> None:
    with Processes(env) as processes:
        processes.start(command[0], command, cwd=cwd)
        result = processes.children[0][1].wait()
        if result:
            raise subprocess.CalledProcessError(result, command)


def setup() -> None:
    require_versions()
    uv = shutil.which("uv") or str(ROOT / ".uv-bootstrap/bin/uv")
    if not Path(uv).is_file():
        run([sys.executable, "-m", "venv", str(ROOT / ".uv-bootstrap")], os.environ.copy())
        run(
            [str(ROOT / ".uv-bootstrap/bin/python"), "-m", "pip", "install", "uv"],
            os.environ.copy(),
        )
    env = os.environ.copy()
    for key in ("UV_OFFLINE", "UV_NO_SYNC", "npm_config_offline", "NODE_ENV", "NODE_OPTIONS"):
        env.pop(key, None)
    env.update(
        {
            "NEXT_TELEMETRY_DISABLED": "1",
            "npm_config_audit": "false",
            "npm_config_fund": "false",
            "npm_config_engine_strict": "true",
        }
    )
    run([uv, "sync", "--locked", "--dev", "--python", "3.12"], env)
    run(["npm", "ci"], env, cwd=FRONTEND)
    run(["node", "node_modules/@playwright/test/cli.js", "install", "chromium"], env, cwd=FRONTEND)
    # Load platform-native build tools while connected, before an offline build.
    run(
        [
            "node",
            "-e",
            "require('next/dist/build/swc').loadBindings().then(() => require('sharp'))",
        ],
        env,
        cwd=FRONTEND,
    )
    print("Setup complete. Stop source writers, then run ./dev init-data.")


def prompt_accounts():
    from family_finance.api.auth import BootstrapAccount

    if not sys.stdin.isatty():
        raise RuntimeError("New development accounts require an interactive terminal")
    accounts = []
    for label in ("First", "Second"):
        username = input(f"{label} development account username: ").strip()
        display_name = input(f"{label} account display name: ").strip()
        password = getpass.getpass("Password (14+ characters): ")
        if password != getpass.getpass("Confirm password: "):
            raise ValueError("Password confirmation did not match")
        accounts.append(BootstrapAccount(username, display_name, password))
    return accounts


def initialize_data(source: Path, destination: Path, *, accounts_factory=prompt_accounts) -> None:
    """Stage a read-only snapshot, relocate files, migrate/audit, then publish once."""
    from sqlalchemy import delete

    from family_finance.api.auth import AuthService
    from family_finance.audit import AuditService
    from family_finance.backup import BackupService
    from family_finance.config import Settings
    from family_finance.persistence.db import Database
    from family_finance.persistence.models import ApiLoginThrottleRow, ApiSessionRow

    source, destination = source.resolve(), destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Development destination already exists; preserve/rename it first")
    if source == destination.resolve() or source in destination.resolve().parents:
        raise ValueError("Development destination must be outside the source data tree")
    database_path = source / "family_finance.sqlite3"
    if not database_path.is_file():
        raise FileNotFoundError("Source database is missing; no empty copy was created")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".dev-local-", dir=destination.parent))
    stage.chmod(0o700)
    try:
        snapshot_path = stage / database_path.name
        with (
            closing(sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True)) as source_db,
            closing(sqlite3.connect(snapshot_path)) as snapshot,
        ):
            source_db.backup(snapshot)
        # Read the captured metadata, not a later version of the live database.
        snapshot_db = Database(snapshot_path, read_only=True)
        try:
            BackupService(snapshot_db, Settings(data_root=source)).copy_snapshot_archives(
                stage, snapshot_db
            )
        finally:
            snapshot_db.engine.dispose()
        with scoped_environment(local_environment(stage)):
            settings = Settings.from_environment()
            settings.ensure_directories()
            database = Database(snapshot_path)
            try:
                audit = AuditService(database, settings).run()
                if not audit.passed:
                    codes = sorted({code for check in audit.checks for code in check.issue_codes})
                    raise RuntimeError("Copied data failed audit: " + ", ".join(codes))
                with database.write_session() as session:
                    session.execute(delete(ApiSessionRow))
                    session.execute(delete(ApiLoginThrottleRow))
                auth = AuthService(database, settings)
                if auth.account_count() == 0:
                    auth.bootstrap_accounts(accounts_factory())
                elif auth.account_count() != 2:
                    raise RuntimeError("Copied data must have exactly two household accounts")
                (stage / MARKER).write_text("FamilyFin isolated development data\n")
                with database.engine.connect() as connection:
                    connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                database.engine.dispose()
        # Existing non-empty destinations cannot be replaced by rename.
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("Development destination appeared during initialization")
        stage.rename(destination)
    except BaseException:
        shutil.rmtree(stage)
        raise


def require_development_data() -> None:
    if DATA.is_symlink() or not (DATA / MARKER).is_file():
        raise RuntimeError("No isolated development copy found. Run ./dev init-data first.")


@contextmanager
def workspace_lock():
    """Avoid simultaneous Next builds/servers using the same local build directory."""
    lock_path = FRONTEND / ".familyfin-dev.lock"
    with lock_path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another ./dev command is using the local workspace") from None
        yield


def control_socket_path() -> Path:
    return FRONTEND / ".familyfin-dev.sock"


@contextmanager
def stop_listener():
    """Accept stop requests through a private socket, never a reusable stored PID."""
    path = control_socket_path()
    # The caller holds the workspace lock, so any old socket is stale.
    path.unlink(missing_ok=True)
    finished = threading.Event()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    def listen():
        while not finished.is_set():
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with connection:
                connection.settimeout(1)
                try:
                    with connection.makefile("rb") as stream:
                        request = stream.readline(16)
                    if request != b"stop\n":
                        connection.sendall(b"invalid\n")
                        continue
                    connection.sendall(b"stopping\n")
                except OSError:
                    continue
            os.kill(os.getpid(), signal.SIGTERM)
            return

    worker = threading.Thread(target=listen, name="familyfin-dev-stop", daemon=True)
    try:
        listener.bind(str(path))
        path.chmod(0o600)
        listener.listen(1)
        listener.settimeout(0.2)
        worker.start()
        yield
    finally:
        finished.set()
        listener.close()
        if worker.ident is not None:
            worker.join(timeout=2)
        path.unlink(missing_ok=True)


def stop(*, timeout: float = 15) -> None:
    """Stop only this checkout's registered stack and wait for child cleanup."""
    path = control_socket_path()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        try:
            connection.connect(str(path))
        except (FileNotFoundError, ConnectionRefusedError):
            print("No local FamilyFin server is running.")
            return
        connection.sendall(b"stop\n")
        with connection.makefile("rb") as stream:
            acknowledgement = stream.readline(32)
        if acknowledgement != b"stopping\n":
            raise RuntimeError("Local server did not acknowledge the stop request")
    deadline = time.monotonic() + timeout
    while path.exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("Local server is still stopping; check its terminal output")
        time.sleep(0.1)
    print("Stopped local FamilyFin services.")


class Processes:
    def __init__(self, env: dict[str, str]) -> None:
        self.env = env
        self.children: list[tuple[str, subprocess.Popen]] = []
        self.opener = build_opener(ProxyHandler({}))

    def start(self, name: str, command: list[str], *, cwd: Path = ROOT) -> None:
        process = subprocess.Popen(command, env=self.env, cwd=cwd, start_new_session=True)
        self.children.append((name, process))

    def ensure_running(self) -> None:
        for name, process in self.children:
            if process.poll() is not None:
                raise RuntimeError(
                    f"{name} exited with status {process.returncode}; see output above"
                )

    def ready(self, url: str, *, timeout: float = 90) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.ensure_running()
            try:
                with self.opener.open(url, timeout=1) as response:
                    if response.status == 200:
                        return
            except (OSError, URLError):
                pass
            time.sleep(0.2)
        raise RuntimeError(f"Service readiness timed out: {url}")

    def stop(self) -> None:
        # Signal the whole group, including Next/uvicorn reload children.
        for _, process in reversed(self.children):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 5
        for _, process in self.children:
            try:
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stop()


def require_free_ports(ports: list[int]) -> None:
    if len(ports) != len(set(ports)):
        raise ValueError("Service ports must be distinct")
    for port in ports:
        with socket.socket() as listener:
            # Like the actual servers, allow restart while closed sockets remain
            # in TIME_WAIT; an active listener must still reject the probe.
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                listener.bind(("127.0.0.1", port))
                listener.listen(1)
            except OSError:
                raise RuntimeError(f"Loopback port {port} is already in use") from None


def start(
    *,
    qa: bool,
    streamlit: bool,
    debug_api: bool,
    port: int = 3000,
    api_port: int = 8000,
    streamlit_port: int = 8501,
    debug_port: int = 5678,
) -> None:
    require_dependencies()
    require_development_data()
    require_free_ports(
        [port, api_port]
        + ([streamlit_port] if streamlit else [])
        + ([debug_port] if debug_api else [])
    )
    env = local_environment(DATA, web_port=port, api_port=api_port)
    with workspace_lock(), stop_listener(), Processes(env) as processes:
        if qa:
            run(["npm", "run", "build"], env, cwd=FRONTEND)
        api = [str(PYTHON), "-m", "family_finance.api.cli"]
        if debug_api:
            api = [
                str(PYTHON),
                "-m",
                "debugpy",
                "--listen",
                f"127.0.0.1:{debug_port}",
                "--configure-subProcess",
                "true",
                "-m",
                "family_finance.api.cli",
            ]
        if not qa:
            api.append("--reload")
        processes.start("API", api)
        processes.ready(f"http://127.0.0.1:{api_port}/api/v1/health")
        processes.start(
            "PWA",
            [
                "npm",
                "run",
                "start" if qa else "dev",
                "--",
                "--port",
                str(port),
            ],
            cwd=FRONTEND,
        )
        processes.ready(f"http://127.0.0.1:{port}")
        processes.ready(f"http://127.0.0.1:{port}/api/v1/health")
        if streamlit:
            processes.start(
                "Streamlit",
                [
                    str(PYTHON),
                    "-m",
                    "streamlit",
                    "run",
                    "streamlit_app.py",
                    "--server.address",
                    "127.0.0.1",
                    "--server.port",
                    str(streamlit_port),
                ],
            )
            processes.ready(f"http://127.0.0.1:{streamlit_port}/_stcore/health")
        print(
            f"FamilyFin ready at http://127.0.0.1:{port} "
            "(Ctrl-C or ./dev stop stops all services)",
            flush=True,
        )
        if debug_api:
            print(f"Python debugger: attach to 127.0.0.1:{debug_port}", flush=True)
        while True:
            processes.ensure_running()
            time.sleep(0.5)


def check() -> None:
    require_dependencies()
    # The entire check, including Python tests and builds, receives disposable paths.
    with workspace_lock(), tempfile.TemporaryDirectory(prefix="familyfin-check-") as directory:
        env = local_environment(Path(directory) / "data", web_port=3101, api_port=8101)
        env["FAMILY_FINANCE_AUTOMATION_BACKUP_ROOT"] = str(Path(directory) / "backups")
        test_env = env.copy()
        # Migration tests intentionally supply their own disposable Config URL.
        test_env.pop("FAMILY_FINANCE_DATABASE_URL", None)
        for command in (
            [str(PYTHON), "-m", "ruff", "check", "src", "tests", "streamlit_app.py"],
            [str(PYTHON), "-m", "pytest"],
        ):
            run(command, test_env)
        # Next generates route declarations before standalone tsc can run on a
        # freshly installed checkout with no prior .next directory.
        for script in ("lint", "test", "build", "typecheck", "test:e2e"):
            run(["npm", "run", script], env, cwd=FRONTEND)
        run(["npm", "run", "test:live"], env, cwd=FRONTEND)


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("setup", help="Install locked dependencies once while connected")
    subparsers.add_parser("stop", help="Stop this checkout's local servers")
    init = subparsers.add_parser(
        "init-data", help="Copy existing data; source writers must be stopped"
    )
    init.add_argument("--source", type=Path, default=ROOT / "data/local")
    init.add_argument(
        "--source-stopped",
        action="store_true",
        help="Confirm all processes writing to the source data are stopped",
    )
    serve = subparsers.add_parser("start", help="Start the isolated loopback stack")
    serve.add_argument("--qa", action="store_true")
    serve.add_argument("--streamlit", action="store_true")
    serve.add_argument("--debug-api", action="store_true")

    def loopback_port(value: str) -> int:
        port = int(value)
        if not 1 <= port <= 65535:
            raise argparse.ArgumentTypeError("Port must be between 1 and 65535")
        return port

    for name, default in (
        ("port", 3000),
        ("api-port", 8000),
        ("streamlit-port", 8501),
        ("debug-port", 5678),
    ):
        serve.add_argument(f"--{name}", type=loopback_port, default=default)
    subparsers.add_parser("check", help="Run checks with disposable data")
    args = parser.parse_args()

    def interrupted(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        if args.command == "setup":
            setup()
        elif args.command == "stop":
            stop()
        elif args.command == "init-data":
            require_dependencies()
            if not args.source_stopped:
                if not sys.stdin.isatty():
                    raise RuntimeError("Stop source writers, then pass --source-stopped")
                answer = input(
                    "Have you stopped all source API/Streamlit/CLI/automation writers? [y/N] "
                )
                if answer.strip().casefold() not in {"y", "yes"}:
                    raise RuntimeError("Stop source writers before making the development copy")
            with workspace_lock():
                initialize_data(args.source, DATA)
            print("Development copy ready. Run ./dev start.")
        elif args.command == "start":
            start(
                qa=args.qa,
                streamlit=args.streamlit,
                debug_api=args.debug_api,
                port=args.port,
                api_port=args.api_port,
                streamlit_port=args.streamlit_port,
                debug_port=args.debug_port,
            )
        elif args.command == "check":
            check()
    except KeyboardInterrupt:
        print("Stopped.")
        raise SystemExit(130) from None
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"dev: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
