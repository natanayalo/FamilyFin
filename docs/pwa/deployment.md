# PWA private host deployment and operations

This is a reference deployment for a Linux systemd host. It runs the API and PWA as separate loopback-only processes, uses Caddy for same-origin routing, and exposes Caddy over Tailscale Serve HTTPS. The repository includes sample units and a guarded daily backup job under [`deploy/`](../../deploy/). They are templates; selecting the real host, tailnet identities, hostname, and encrypted backup volume is still required before activation.

The request path is:

```text
Household browser --HTTPS/tailnet--> Tailscale Serve :443
    --> Caddy 127.0.0.1:8080
        /api/* --> FastAPI 127.0.0.1:8000
        /*      --> Next.js 127.0.0.1:3000
```

Only the app/API uses the Tailscale network path. The application does not send financial data to analytics, external authentication, cloud storage, or third-party financial services. Keep Funnel disabled. Tailscale Serve is private to the tailnet and uses the tailnet access policy; see the [Tailscale Serve guide](https://tailscale.com/docs/features/tailscale-serve) and [current CLI reference](https://tailscale.com/docs/reference/tailscale-cli/serve).

## Host layout and installation

Use a supported Linux host with systemd, Python 3.12, uv, Caddy v2, and the exact Node version pinned in [`.nvmrc`](../../.nvmrc) (currently `22.14.0`). Keep application code root-owned and read-only to service users. Create separate non-login accounts for the API and Next server so a web process cannot read the financial data root:

```sh
sudo useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin familyfin-api
sudo useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin familyfin-web
sudo install -d -o familyfin-api -g familyfin-api -m 0700 /var/lib/familyfin/data
sudo install -d -o root -g root -m 0755 /opt/familyfin
```

Install a checked-out release at `/opt/familyfin/current`, owned by `root:root` and not writable by either service account. Build from the lockfiles in that release:

```sh
uv sync --locked --no-dev
/opt/node-v22.14.0/bin/npm ci --prefix frontend
/opt/node-v22.14.0/bin/npm run build --prefix frontend
```

After the build, make only the Next runtime cache writable by `familyfin-web`:

```sh
sudo install -d -o familyfin-web -g familyfin-web -m 0750 /opt/familyfin/current/frontend/.next/cache
```

Install the sample environment file with owner-only-by-group access, then replace the example MagicDNS hostname everywhere it appears:

```sh
sudo install -d -o root -g root -m 0755 /etc/familyfin
sudo install -o root -g familyfin-api -m 0640 deploy/systemd/api.env.example /etc/familyfin/api.env
sudoedit /etc/familyfin/api.env
```

Set `FAMILY_FINANCE_API_PUBLIC_ORIGIN` to the exact HTTPS origin, with no path, and include that hostname in `FAMILY_FINANCE_API_TRUSTED_HOSTS`. Keep `FAMILY_FINANCE_DATA_ROOT=/var/lib/familyfin/data`. The API rejects a host/origin mismatch. Do not put passwords, cookies, or session tokens in this file.

Bootstrap the two household accounts once from a protected host console. This command prompts without echoing passwords:

```sh
sudo -u familyfin-api env FAMILY_FINANCE_DATA_ROOT=/var/lib/familyfin/data \
  /opt/familyfin/current/.venv/bin/family-finance auth-bootstrap
```

It creates two equal-permission accounts and `api-secret.key` with mode `0600`. The API migrates its database on startup and binds to `127.0.0.1:8000`. Keep the key in the protected data root. It is not part of a verified backup set; after restore, the API creates a replacement key and users sign in again. Keep account recovery local using `family-finance auth-reset-password USERNAME`.

Install the included systemd units under `/etc/systemd/system/`. They run one API worker, bind the Next server to `127.0.0.1:3000`, use restricted service accounts, and give only the API account write access to `/var/lib/familyfin/data`. The Next process can read the built app but cannot read that data directory.

Add the Caddy site from [`familyfin.Caddyfile`](../../deploy/caddy/familyfin.Caddyfile) to the host's Caddy configuration. It binds only to `127.0.0.1:8080`, preserves the request host and origin through proxying, sends `/api/` to FastAPI, and sends all other paths to Next. Caddy's reverse proxy passes incoming headers, including `Host`, through by default; see the [Caddy reverse proxy reference](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy). The sample does not enable access logging. Validate the full host Caddy configuration before reloading it:

```sh
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl daemon-reload
sudo systemctl enable --now familyfin-api.service familyfin-web.service caddy.service
```

Do not bind FastAPI, Next, or Caddy to a LAN/public interface. Firewall host interfaces so only the tailnet entry point reaches the app. Do not configure shared proxy caching, request-body logging, or cookie/header logging.

## Tailnet policy and Serve

Choose a dedicated tailnet device name and grant access to the two approved household identities. Tag the host `tag:familyfin`, then merge a narrow grant like this into the existing tailnet policy (replace both sample emails). Do not paste it over the complete policy file:

```json
{
  "tagOwners": {
    "tag:familyfin": ["autogroup:admin"]
  },
  "grants": [
    {
      "src": ["household-one@example.com", "household-two@example.com"],
      "dst": ["tag:familyfin"],
      "ip": ["tcp:443"]
    }
  ]
}
```

Tailscale grants add permissions together. Review existing ACLs and grants for broader access to this host; a narrow grant does not cancel a pre-existing broad grant. If access should be limited to specific registered devices as well as the two identities, define that device selector or posture requirement in the tailnet policy before rollout. Tailnet identity is a network gate only; each household member still signs in to FamilyFin separately.

Enable HTTPS certificates for the tailnet and configure a single Serve proxy to the local Caddy listener:

```sh
sudo tailscale serve --bg --https=443 http://127.0.0.1:8080
tailscale serve status --json
tailscale funnel status --json
```

The Serve status must show HTTPS on port 443 proxying to `http://127.0.0.1:8080`. Funnel status must show no active endpoint. Do not run Funnel commands. If Funnel is already configured on this host, pause rollout and have the tailnet operator remove that exposure without disturbing any unrelated service. Tailscale's Serve and Funnel use separate commands; Serve is intended for tailnet access while Funnel makes a service public. See the [Funnel CLI reference](https://tailscale.com/docs/reference/tailscale-cli/funnel).

The FastAPI process deliberately ignores forwarded client addresses. With one loopback proxy, login throttling shares a peer bucket across household browsers. Caddy must preserve the browser's external `Host` and `Origin`; the app rejects unknown hosts, cross-origin writes, and state-changing requests without a valid origin. Do not enable permissive CORS or trust client-supplied forwarded headers.

## Deployment verification

Run repository checks without any host or tailnet credentials:

```sh
uv run pytest tests/test_deployment_artifacts.py
bash -n deploy/bin/familyfin-backup
```

After host activation, record results in the household's protected operations record. Use these checks on the host and on enrolled client devices:

1. `systemctl is-active familyfin-api familyfin-web caddy` reports all three active. `ss -ltnp` shows only loopback listeners for `127.0.0.1:3000`, `127.0.0.1:8000`, and `127.0.0.1:8080`.
2. `tailscale serve status --json` maps the HTTPS service to `http://127.0.0.1:8080`; `tailscale funnel status --json` has no active endpoint. Inspect this after Tailscale restart and host reboot.
3. From an approved tailnet device, load `https://HOST.ts.net` and call `https://HOST.ts.net/api/v1/health`. The health body reports availability only, and the API response includes `Cache-Control: private, no-store`. There must be no certificate warning or external runtime asset request.
4. From a tailnet device/user outside the grant, confirm port 443 is denied. From a non-tailnet device with no route into the tailnet, confirm the URL cannot connect. Also try the host's LAN address against ports 3000, 8000, and 8080; none should answer.
5. Sign in as each household account on separate clients. Confirm both can use the same actions; sign out one session and verify it is rejected. Confirm a cross-origin write and a write without the session's CSRF token are rejected. Confirm the browser does not retain API responses, HTML, upload content, or financial drafts in persistent caches.
6. Reboot the host, repeat the listener/Serve/Funnel/HTTPS checks, then check `family-finance audit` and the latest backup verification.

Tailscale status and the live outside-tailnet denial cannot be established by CI because they require the actual host and tailnet. The repository test checks that the shipped reference artifacts keep listeners on loopback, route the same origin, require a mounted separate backup volume, and do not configure Funnel.

## Backups, retention, and restore

The sample backup service runs every day at 02:15 UTC and uses a random delay of up to 20 minutes. Its script fails closed if the destination is not a mounted volume or overlaps the live data root. It runs the read-only application audit, creates a verified snapshot with the SQLite online backup API and all managed source archives, then verifies the result again. It never overwrites or prunes backups. See [`familyfin-backup`](../../deploy/bin/familyfin-backup), `familyfin-backup.service`, and `familyfin-backup.timer`.

Choose a dedicated encrypted local volume, for example `/mnt/familyfin-backup`. Create and mount it independently from the app data disk; set the mount root owner to `familyfin-api:familyfin-api` and mode `0700`. Configure the matching mount path in `backup.env.example`, `RequiresMountsFor`, and `ReadWritePaths` before installing the unit. Keep backups off cloud sync and external financial services. Enable the timer only after the encrypted volume is mounted and tested:

```sh
sudo install -o root -g familyfin-api -m 0640 deploy/systemd/backup.env.example /etc/familyfin/backup.env
sudo systemctl daemon-reload
sudo systemctl enable --now familyfin-backup.timer
sudo systemctl start familyfin-backup.service
sudo systemctl status familyfin-backup.service
```

The suggested retention policy is 30 daily snapshots and one month-end snapshot for each of the previous 12 months. Keep at least two complete verified snapshots before removing any expired set. Pruning is a monthly operator task: list the snapshots, identify the 30 daily and 12 month-end sets to retain, verify the new replacement snapshot and the current restore practice, then remove only individually reviewed expired directories. There is deliberately no automatic delete step. Recheck free space after each monthly review.

The backup includes the SQLite database and `imports/`, `planning-imports/`, `net-worth-imports/`, and managed `automation/` files. It includes password hashes and financial records, so encryption at rest and restrictive filesystem permissions are mandatory. It does not include `api-secret.key`; restoring without that file invalidates existing sessions, and each person signs in again. If session continuity is specifically required, keep a separately encrypted mode-`0600` copy outside the verified snapshot directory so the snapshot manifest stays valid.

### Backup check

Check the active application audit and a newly created backup from the host console:

```sh
sudo -u familyfin-api env FAMILY_FINANCE_DATA_ROOT=/var/lib/familyfin/data \
  /opt/familyfin/current/.venv/bin/family-finance audit
sudo systemctl start familyfin-backup.service
sudo systemctl show familyfin-backup.service -p Result
```

Require `Result=success`. Locate the newest `familyfin-*` directory on the mounted volume and verify it explicitly:

```sh
BACKUP_DIR=/mnt/familyfin-backup/familyfin-YYYYMMDDTHHMMSSZ-PID
sudo -u familyfin-api env \
  FAMILY_FINANCE_DATA_ROOT=/var/lib/familyfin/data \
  PATH=/opt/familyfin/current/.venv/bin:/usr/bin:/bin \
  /opt/familyfin/current/.venv/bin/family-finance verify-backup "$BACKUP_DIR"
```

Verification must pass manifest hashes, SQLite integrity/foreign keys, current Alembic revision, application invariants, and source-archive coverage. Do not copy a snapshot off the encrypted volume to an unprotected path.

`verify-backup` expects the schema head used when that snapshot was created. Before upgrading application code, create and verify a fresh snapshot and retain the previous release until the new version passes its own audit. When restoring an older snapshot, run its verifier from the matching application release, then migrate the staged database forward. Do not bypass a schema-revision mismatch.

### Restore practice and incident recovery

Perform a restore drill at least quarterly into a separate `0700` staging directory on encrypted local storage. Do not overwrite the live data during the drill. Record the UTC date, the backup manifest schema revision, verifier/audit outcomes, release used, and whether the restored API starts. Remove the staging copy after the drill using the host's secure deletion/volume disposal procedure.

For an actual recovery, keep it manual and operator-controlled:

1. Put household users into maintenance mode. Stop all writers and public entry points, including the backup timer and any active backup job:

   ```sh
   sudo systemctl stop familyfin-backup.timer familyfin-backup.service \
     familyfin-web.service familyfin-api.service caddy.service
   ```

   Confirm those units are stopped and no CLI or Streamlit process is using the data root.
2. Select a complete snapshot from the protected volume. Verify it with `family-finance verify-backup` using the matching release; stop if any hash, schema, database, invariant, or archive-coverage check fails.
3. Create a unique staging directory beside the canonical data root, on the same filesystem. This rename procedure requires `/var/lib/familyfin/data` to be a directory on the `/var/lib/familyfin` filesystem, not a separate mountpoint. Copy the verified snapshot as one matched set, then verify the staged copy before changing it. For example:

   ```sh
   BACKUP_DIR=/mnt/familyfin-backup/familyfin-YYYYMMDDTHHMMSSZ-PID
   STAGING_ROOT=/var/lib/familyfin/recovery-staging-20260925T021500Z
   sudo install -d -o familyfin-api -g familyfin-api -m 0700 "$STAGING_ROOT"
   sudo -u familyfin-api rsync -a -- "$BACKUP_DIR"/ "$STAGING_ROOT"/
   sudo -u familyfin-api env \
     FAMILY_FINANCE_DATA_ROOT=/var/lib/familyfin/data \
     PATH=/opt/familyfin/current/.venv/bin:/usr/bin:/bin \
     /opt/familyfin/current/.venv/bin/family-finance verify-backup "$STAGING_ROOT"
   ```

   Stop if either verification fails. Do not mix a database and archive directories from different snapshots.
4. Apply migrations to the staged database with `FAMILY_FINANCE_DATABASE_URL` set to its `family_finance.sqlite3` path, then run `family-finance audit` with `FAMILY_FINANCE_DATA_ROOT` set to the staging root. For the staging root above, run:

   ```sh
   sudo -u familyfin-api env \
     FAMILY_FINANCE_DATABASE_URL=sqlite:////var/lib/familyfin/recovery-staging-20260925T021500Z/family_finance.sqlite3 \
     /opt/familyfin/current/.venv/bin/alembic upgrade head
   sudo -u familyfin-api env \
     FAMILY_FINANCE_DATA_ROOT=/var/lib/familyfin/recovery-staging-20260925T021500Z \
     PATH=/opt/familyfin/current/.venv/bin:/usr/bin:/bin \
     /opt/familyfin/current/.venv/bin/family-finance audit
   ```

   Require both commands to succeed. Confirm the staging root is owned by `familyfin-api` and mode `0700`.
5. Keep `/etc/familyfin/api.env` unchanged at `FAMILY_FINANCE_DATA_ROOT=/var/lib/familyfin/data`. The API unit retains `ProtectSystem=strict` and `ReadWritePaths=/var/lib/familyfin/data`; the staging path is only for the one-shot verification and migration commands. Rename the live root aside, then atomically rename the verified staging directory into the canonical path. Both directories must remain on the same filesystem:

   ```sh
   set -eu
   CANONICAL_ROOT=/var/lib/familyfin/data
   STAGING_ROOT=/var/lib/familyfin/recovery-staging-20260925T021500Z
   PRESERVED_ROOT=/var/lib/familyfin/data.recovery-old-20260925T021500Z
   test "$(stat -c '%d' "$CANONICAL_ROOT")" = "$(stat -c '%d' /var/lib/familyfin)"
   test "$(stat -c '%d' "$STAGING_ROOT")" = "$(stat -c '%d' /var/lib/familyfin)"
   test ! -e "$PRESERVED_ROOT"
   sudo mv -- "$CANONICAL_ROOT" "$PRESERVED_ROOT"
   if ! sudo mv -- "$STAGING_ROOT" "$CANONICAL_ROOT"; then
     sudo mv -- "$PRESERVED_ROOT" "$CANONICAL_ROOT"
     echo "Staging activation failed; the previous data root was restored" >&2
     exit 1
   fi
   grep -Fx 'FAMILY_FINANCE_DATA_ROOT=/var/lib/familyfin/data' /etc/familyfin/api.env
   ```

   Do not repoint the API environment file to the staging directory. If the second rename fails, the command restores the preserved root to the canonical path before exiting.
6. Start API, PWA, and Caddy at the canonical path. Run the audit against that root and check service state:

   ```sh
   sudo systemctl start familyfin-api.service familyfin-web.service caddy.service
   sudo systemctl is-active familyfin-api.service familyfin-web.service caddy.service
   sudo -u familyfin-api env \
     FAMILY_FINANCE_DATA_ROOT=/var/lib/familyfin/data \
     PATH=/opt/familyfin/current/.venv/bin:/usr/bin:/bin \
     /opt/familyfin/current/.venv/bin/family-finance audit
   ```

   From authorized client devices, check the health/no-store response, both household logins, session behavior, and private-access checks above. The restored data has no `api-secret.key`; the API creates a replacement key and both users sign in again.
7. After those application checks pass, restart the backup timer and run one backup immediately:

   ```sh
   sudo systemctl start familyfin-backup.timer
   sudo systemctl start familyfin-backup.service
   sudo systemctl show familyfin-backup.service -p Result
   ```

   Require `Result=success` and verify the new snapshot as described in [Backup check](#backup-check). Recovery is accepted only after the application checks and this fresh verified backup pass.
8. Keep `PRESERVED_ROOT` and the selected source backup untouched until recovery is accepted. If any acceptance check fails, stop the backup timer/job and app services, rename the failed canonical tree to a separate recovery-failed path, move `PRESERVED_ROOT` back to `/var/lib/familyfin/data`, then restart the app services. For example:

   ```sh
   set -eu
   CANONICAL_ROOT=/var/lib/familyfin/data
   PRESERVED_ROOT=/var/lib/familyfin/data.recovery-old-20260925T021500Z
   FAILED_ROOT=/var/lib/familyfin/data.recovery-failed-20260925T021500Z
   sudo systemctl stop familyfin-backup.timer familyfin-backup.service \
     familyfin-web.service familyfin-api.service caddy.service
   test ! -e "$FAILED_ROOT"
   sudo mv -- "$CANONICAL_ROOT" "$FAILED_ROOT"
   sudo mv -- "$PRESERVED_ROOT" "$CANONICAL_ROOT"
   sudo systemctl start familyfin-api.service familyfin-web.service caddy.service
   ```

   Keep the failed tree for investigation. Restart the backup timer only after the original root passes the audit and acceptance checks.

Never automate restore or delete the previous live root as part of the recovery procedure. Keep the Python CLI and Streamlit fallback available until the separate PWA parity/recovery gate authorizes retiring Streamlit.

## Authentication and privacy operations

Passwords use salted scrypt hashes; API sessions are revocable, eight hours by default, and carried in `Secure`, `HttpOnly`, `SameSite=Strict` cookies scoped to `/api/v1`. There is no public registration or third-party login. Password reset is an interactive host-console operation and revokes the account's active sessions.

Uvicorn access logging is disabled. Do not enable request-body, cookie, authorization-header, filename, query-string, description, amount, account-reference, client-address, or username logging in the API, Next, Caddy, systemd wrappers, or monitoring. API and health responses use `Cache-Control: private, no-store`. The service worker may cache only versioned static assets; it must exclude HTML with personal data, all `/api/` responses, uploads, and form state.

No financial mutation route currently claims automatic retry safety. Filesystem side effects need a route-specific recovery protocol. Remote mutating automation and attention-file commits remain blocked until every entry point requires a verified pre-import backup. T12 may retire Streamlit only after feature parity, private access, verified backup readiness, and a successful restore practice have been recorded.
