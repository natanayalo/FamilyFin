# Local development and disconnected QA

The native stack runs on macOS or Linux with Python 3.12 and Node **22.23.4**
(see `.nvmrc`). The real PWA and API are available at
**http://127.0.0.1:3000**. All listeners stay on loopback. This workflow needs
no Tailscale, DNS, certificates, Docker, or Caddy.

## Setup once with internet

Install Python 3.12 and the pinned Node version. With nvm, run `nvm install`
and `nvm use` from the repository. The launcher checks the exact Node version
and does not replace the machine's Node installation.

```sh
./dev setup
```

Setup installs locked Python development dependencies (including debugpy),
locked npm dependencies, and Playwright Chromium. It uses `uv` from PATH or
`.uv-bootstrap/bin/uv`, creating that ignored bootstrap environment if needed.
It loads native Next/compiler/image binaries while connected to discover missing
platform packages. On Linux, install Chromium's system libraries while connected
if Playwright reports missing OS dependencies.

Keep these dependencies and browser binaries installed on the same machine.
Subsequent commands use installed executables directly, disable telemetry, and
set package managers to offline operation. Dependency updates or switching
operating systems/architectures require connected setup again. There is no
offline installation bundle.

## Initialize isolated data

Stop all processes writing to the source data: Streamlit, API, CLI imports,
and scheduled automation. Then run:

```sh
./dev init-data
```

The command asks you to confirm that source writers are stopped. A noninteractive
invocation requires `--source-stopped`; this records your assertion rather than
stopping or detecting every possible writer. To select another source, use
`--source /absolute/path/to/data`.
New account passwords still require an interactive terminal.

Initialization takes a read-only SQLite online snapshot of `data/local`, copies
referenced imports and managed processed/review automation files, and relocates
their paths inside the copy. Unprocessed inbox files, source logs, and the source
secret are not copied. Only the snapshot is migrated and audited. Any failure
prevents activation and leaves the source unchanged.

The repository's existing database is at schema `0010` without API accounts.
Initialization prompts for two development accounts after migrating the copy.
Passwords are hidden and require at least 14 characters. For newer sources that
already have accounts, identities and passwords are retained, sessions and login
throttles are cleared, and a separate secret is generated.

The activated copy lives in ignored **`data/dev-local/`** and contains real
household financial data. Keep it on protected local storage. Existing
destinations are refused. To refresh, stop the local stack, preserve the old copy
by moving it outside the active path, then initialize again. There is no automatic
overwrite or delete command.

## Develop and debug

```sh
./dev start
./dev start --streamlit
./dev start --debug-api
```

The PWA uses port 3000, API 8000, optional Streamlit 8501, and optional debugger
5678. Occupied ports fail clearly. The launcher waits for readiness, monitors
its servers, and stops their process groups on Ctrl-C, termination, or failure.
Run one stack/check command at a time because they share local build output.

To stop a stack from another terminal in this checkout:

```sh
./dev stop
```

This stops hot-reload, QA, debugger and optional Streamlit services together,
including an in-progress QA build, and waits for child-process cleanup. It uses
a private local control socket rather than a saved PID, so stale state cannot
signal an unrelated process. Running it again reports that no server is running.
The stop command does not require Node or install dependencies. It only controls
servers started with this launcher; standalone servers still use their own terminal.

If another application uses these ports, select alternatives with `--port`,
`--api-port`, `--streamlit-port`, or `--debug-port`. For example:
`./dev start --port 3150 --api-port 8150`. The proxy and cookie origin follow
the selected ports.

Python code under `src/` reloads automatically; Next supplies frontend hot reload.
Use browser DevTools for frontend breakpoints and request inspection. With
`--debug-api`, attach your IDE to `127.0.0.1:5678`, enable subprocess debugging,
and select `.venv/bin/python`. The API starts without waiting for the debugger.
Combine `--qa --debug-api` for a stable API process without its reloader.

The launcher overrides inherited financial paths, migration URLs, API origins,
trusted hosts, and backup destinations. Scope manual CLI operations explicitly:

```sh
FAMILY_FINANCE_DATA_ROOT="$PWD/data/dev-local" .venv/bin/family-finance audit
FAMILY_FINANCE_DATA_ROOT="$PWD/data/dev-local" .venv/bin/family-finance auth-reset-password USERNAME
FAMILY_FINANCE_DATA_ROOT="$PWD/data/dev-local" \
  FAMILY_FINANCE_AUTOMATION_BACKUP_ROOT="$PWD/data/dev-backups" \
  .venv/bin/family-finance automate --dry-run
```

In-app automation uses ignored `data/dev-backups/`, outside the active data root,
and retains the verified pre-import backup gate. The launcher enables no schedule.

## Built-app and PWA QA

```sh
./dev start --qa
```

QA builds and starts Next's production runtime with the real local API and
development copy. Local builds use `.next-local/`; deployment builds use `.next/`.
Always rebuild through this command after changing profiles.

Hot-reload development unregisters FamilyFin workers, removes only FamilyFin
static caches, and reloads an already-controlled document. QA enables the normal
PWA worker, manifest, and static caching. Neither profile persists financial
responses, uploads, or drafts in browser storage.

HTTP requires `FAMILY_FINANCE_LOCAL_DEV=1` and exact loopback/localhost origins
and hosts. Local HTTP cookies omit Secure while retaining HttpOnly,
SameSite=Strict, CSRF, origin checks, expiry, and throttling. Production still
requires HTTPS and Secure cookies. Local QA does not verify certificates,
Tailscale policy, Linux systemd, or production host isolation.

Disconnect external networking while keeping loopback available, then sign in,
reload, inspect dashboards, and preview/commit an XLSX in the development copy.
API reachability determines connectivity, regardless of internet status. Stop
the API to verify that the next request/revalidation hides financial content;
restart it and use Retry to restore authenticated access. DevTools' **Offline**
setting blocks localhost too: use it to test API unavailability rather than
internet independence.

## Automated checks

```sh
./dev check
```

Checks cover Python lint/tests, frontend lint/types/unit tests/build, existing
mocked browser acceptance, and a live API/browser suite. They use disposable
paths and synthetic records, never your development copy or original household
database. The live suite verifies cookies, refresh/logout, populated dashboard,
multipart imports, blocked external requests, and outage/recovery with
`navigator.onLine=false`. Live browser traces are disabled.

This environment exposes existing modules. The apartment PWA page remains its
existing placeholder; its implemented workflows are available in fallback
Streamlit.


### Populated Net Worth data for browser QA

Use synthetic data when working on Net Worth UI. The reusable
`tests.qa_net_worth.seed_net_worth_qa(database, as_of=...)` helper populates the
existing disposable live-browser household with eight sample asset/debt accounts
and three snapshots. Pass the intended date explicitly; the fixture includes two
preceding month ends and an older investment valuation for warning-state checks.
All names and amounts are synthetic.

Call it only after creating an isolated live-browser stack whose frontend proxies
to its own temporary API. The helper refuses a database outside a
`familyfin-live-*` temporary directory and refuses an already populated Net Worth
registry. It never overwrites existing records. The default live stack remains
empty for first-use checks. Closing that stack discards its temporary data; the
helper can recreate the populated scenario in the next disposable stack.
