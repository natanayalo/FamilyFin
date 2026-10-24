# Windows / WSL2 Docker deployment

This is a guarded synthetic deployment, separate from the supported
[Linux systemd deployment](deployment.md). Real-data activation, household accounts
and private endpoint changes require explicit operator approval. Read the
[security comparison](windows-security-assessment.md), [backup procedure](portable-backup.md)
and [validation limits](windows-validation.md) before promotion.

## Architecture and prerequisites

```text
Approved phone -> Tailscale Serve HTTPS :443
  -> 127.0.0.1:8090 -> Caddy :8080 -> api:8000 or web:3000
                                      |
                               named Linux financial volume
```

The local lab defaults to `https://familyfin.test`. Actual-origin phone preparation
is a separate guarded workflow; these defaults are not an activated phone endpoint.
Docker Desktop must use WSL2 Linux containers through the local `desktop-linux`
named pipe. Windows PowerShell, Python 3.12+, Engine 28+ and Compose 2.24.4+ are
required. Check current vendor security releases separately from minimum compatibility.
API Python, repository-pinned Node and all base images have exact versions/digests.
Python uses `uv.lock`; Node uses `npm ci`. Next lockfile checking stays enabled,
and networkless production compilation must leave the lockfile unchanged.
Dependency reproducibility is tested; byte-identical images are not claimed.

Only Caddy is host-published, on IPv4 loopback 8090 (restore lab 8091). API/web have
no host ports. The application network is internal; only Caddy additionally joins
an edge bridge for Docker Desktop localhost publishing. SQLite/WAL, managed source
archives and the API signing key live in a named Linux volume mounted only by the
API and explicit offline maintenance containers. Web/Caddy never mount it. No
privilege, Docker socket or host financial directory is used.

API/web/Caddy run as distinct non-root UIDs, with read-only roots, bounded tmpfs,
capabilities dropped, no-new-privileges, health checks, restart policy and memory,
CPU/PID/log limits. Same-origin authentication, Secure/HttpOnly/SameSite cookies,
CSRF checks, trusted hosts, CSP/HSTS and no-store remain enabled. Standalone Next
output is Docker-only; Linux startup/listeners remain unchanged. No secret is baked
into images or passed through build args. Docker/Windows administrators remain trusted.

## Disposable local operation

```powershell
./deploy/docker/start.ps1 -Build
./deploy/docker/verify.ps1
./deploy/docker/backup.ps1
./deploy/docker/stop.ps1
```

Wrappers fix lab project/origin/ports and discard ambient Compose/development
settings. They refuse ownership conflicts, remote engines and accidental replacement
of a prepared mobile trial. Stop removes only owned containers/networks and retains
volumes. Never prune Docker or reuse a nonempty financial volume to reset a test.
`validate.py` runs only on fresh lab volumes; credentials are generated in memory
and sent through stdin. Local HTTP tests simulate the TLS boundary and do not
certify Safari. Never weaken Secure cookies, CSRF, host checks or TLS verification.

## Candidate validation and release

Build new unique candidate tags, preserving the active/rollback references:

```powershell
docker build -f deploy/docker/api.Dockerfile -t familyfin-m1-api:candidate-RELEASE .
docker build -f deploy/docker/web.Dockerfile -t familyfin-m1-web:candidate-RELEASE .
docker build -f deploy/docker/caddy.Dockerfile -t familyfin-m1-caddy:candidate-RELEASE .
python deploy/docker/scan_images.py familyfin-m1-api:candidate-RELEASE familyfin-m1-web:candidate-RELEASE familyfin-m1-caddy:candidate-RELEASE --record-only
python deploy/docker/validate_candidate.py --tag candidate-RELEASE --run-id UNIQUE
```

Use lowercase safe release/run identifiers. `--record-only` preserves scanner FAIL;
it is not a waiver. The ordinary scanner exits nonzero for blocking findings,
including UNKNOWN. The candidate validator checks exact scan/image identities and
uses fresh localhost 8092/8093 volumes. It verifies authentication/CSRF, isolation,
persistence, backup, clean restore, audit/migrations and old-session rejection.
It removes only candidate containers/networks, retaining data/evidence, and compares
all original services and Serve before/after. Do not promote a changed image under
an exception for a different digest. Review findings and authorize exact promotion.

## Independent backup and clean recovery

The default backup volume shares Docker's virtual disk and cannot protect against
loss of that disk. Use the [file-encrypted portable procedure](portable-backup.md)
after selecting/approving independent media. The older BitLocker-only export
wrapper and Compose overrides have been retired; existing encrypted drives and
their contents are unaffected. Existing drive files/settings must never be modified to satisfy
a deployment guard. Neither path may silently fall back to local Docker storage.

Use the matching release/schema to verify and restore into a new empty financial
volume/project. Keep the original data and snapshot. Restoration verifies manifest
hashes/schema/invariants before copying and audits afterward. The old signing key
is excluded; startup creates a new owner-only key, so users must reauthenticate.
Never downgrade Alembic or run older code against a possibly migrated live database.

## Availability and synthetic scheduling

Docker restart policies only work after Docker Desktop is available. AutoStart is
an operator-selected setting; verify an actual restart/sign-in without manually
opening Docker. The temporary synthetic task runs under the signed-in operator,
without a saved Windows password, at 03:00 local time plus login, with explicit
expiry, retries and a one-hour limit. Registration requires a reviewed XML hash
and approval; no task is created by a build or normal start command.

The task waits at most five minutes for the pinned local engine and reviewed API
health. Probes are read-only/time-bounded. Wrong endpoint/release or missing
containers fail closed; it never starts or recreates dependencies. Failures return
nonzero and retain a warning until exact-ID acknowledgement after review.
A brief popup does not establish unattended alert delivery. Duplicate suppression
uses Windows-local schedule periods beginning at 03:00, so a manual backup before
that boundary cannot suppress the new period's daily run. Successful catch-up or
manual runs after the boundary cover that period. Status freshness remains a
separate 26-hour check. Review retention/capacity and a permanent policy before
real data. Before-login, signed-out,
locked and sleep/resume availability require their own evidence.

`host_recovery.py prepare --config CONFIG.json` creates a fresh verified backup and private baseline;
it never restarts Windows. After separately approved restart, `verify --receipt PATH`
requires a changed boot and checks all original identities/configurations/states/
ports/Serve plus data/key persistence. Empty DNS null/list normalization is accepted
only when the entire original configuration hash matches. A separately reviewed
comparison record may renew process start times; original receipts remain intact.

## Proposed Tailscale cutover and rollback

These commands document a plan, not permission to activate it. Confirm the current
handler/ACL, approved device, exact candidate digests and actual-origin configuration;
keep Funnel disabled. Create and independently verify a fresh encrypted backup.
Save the complete existing Serve JSON in a protected receipt; for this POC the
known-good M0 root is loopback 8088. Refuse unexpected listeners/handlers.

Only after approval of the exact root replacement:

```powershell
tailscale serve --bg --https=443 --set-path=/ http://127.0.0.1:8090
tailscale serve status --json
```

Compare the complete configuration: only that upstream may change. Test normal
TLS validation, health/headers, both test-user login/logout, CSRF, PWA/offline/cache,
Wi-Fi/cellular/VPN-off behavior and independent LAN exposure. Keep M0 available.
On failure, restore only the known-good root and compare with the saved receipt:

```powershell
tailscale serve --bg --https=443 --set-path=/ http://127.0.0.1:8088
tailscale serve status --json
```

Never use `serve reset`. Retain all data/evidence. No extra API/frontend ports,
new tailnet grants or household credentials are needed for a synthetic trial.
Real-data bootstrap remains a separate protected-console operation; never send
passwords, recovery identities or session cookies through chat, args or images.
