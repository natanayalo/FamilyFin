# FamilyFin API host deployment

This guide covers the Python API foundation. It does not deploy or configure the T02 frontend, reverse proxy, tailnet ACL, or host supervisor. Keep the API bound to loopback and expose the same-origin proxy through private Tailscale HTTPS only. Do not enable Funnel.

## One-time account bootstrap and recovery

1. Install the pinned Python environment and run `family-finance auth-bootstrap` on the household host as the dedicated operating-system account that owns the data root.
2. Enter two different usernames, display names, and passwords interactively. Passwords are read with terminal echo disabled, are never command-line arguments, and must be at least 14 characters. Bootstrap is refused if any API account already exists. There is no public registration, third-party login, application administrator, or unequal household permission.
3. The API creates a random 32-byte `data_root/api-secret.key` with mode `0600`. Keep it with the host's protected data. It protects login-throttle identifiers and derives per-session CSRF tokens. The current `BackupService` does not include this file: if you need to preserve sessions across host restore, copy it separately into a protected host-level backup. If it is lost, a replacement key invalidates existing sessions; users can sign in again with their account passwords.
4. For password recovery, the authorized host operator runs `family-finance auth-reset-password USERNAME` at the host console and enters a new password twice. The reset revokes every active session for that account. There is no email/SMS recovery route. Protect host access and the data root with the operating system's account controls.

Passwords are stored as salted scrypt hashes. The API issues a random opaque session cookie; SQLite stores only its SHA-256 digest, CSRF digest, account, issue/expiry times, and revocation state. The cookie is `Secure`, `HttpOnly`, `SameSite=Strict`, scoped to `/api/v1`, and has an eight-hour absolute lifetime by default. The server validates and revokes sessions on every request. Sign-out revokes the server record. Login failures are throttled after five failures per account/client pair; the stored throttle key is HMACed and raw usernames/IP addresses are not stored in the throttle table or event log.

## Loopback API and same-origin proxy

Install the project with its lockfile, configure the data/backup roots, and set:

```sh
export FAMILY_FINANCE_API_PUBLIC_ORIGIN='https://familyfin.example-tailnet.ts.net'
export FAMILY_FINANCE_API_TRUSTED_HOSTS='familyfin.example-tailnet.ts.net,localhost,127.0.0.1'
export FAMILY_FINANCE_API_PORT='8000'
family-finance-api
```

`family-finance-api` binds Uvicorn to `127.0.0.1`, uses one worker, disables access logs, and does not trust forwarded headers. Run migrations and construct one reusable service graph during app startup. A local reverse proxy should serve the frontend and forward `/api/` to `127.0.0.1:8000`, preserving the configured external `Host` and HTTPS `Origin`. Configure Tailscale Serve for the proxy only, restrict the tailnet ACL to the two household identities/devices, and keep Funnel disabled. Firewall other host interfaces. Do not bind FastAPI or Next directly to a public interface.

The API rejects unknown hosts, missing or mismatched `Origin` on every state-changing `/api/` request, and cross-origin browser writes. Authenticated mutation routers must be created with `authenticated_router()`: it requires a valid household session and CSRF token on non-read methods. Sign-in is protected by same-origin validation and login throttling; sign-out also requires CSRF. Do not add permissive CORS.

The default request-body limit is 1 MiB and applies even to chunked API requests. Current T01 endpoints accept only small JSON bodies. Any future upload route must define an explicit parser-aligned limit and still preserve the configured FamilyBiz/CSV compressed, expanded, row, column, and field limits; do not raise the global limit for convenience. Financial API responses and health responses receive `Cache-Control: private, no-store`. Health reports availability only.

## Privacy, logs, backups, and mutation gates

Uvicorn access logging is disabled. The API creates server request IDs and returns them in the standard error envelope and `X-Request-ID`; application logs must not include bodies, cookies, authorization values, filenames, descriptions, amounts, account references, client addresses, or usernames. Append-only `actor_audit_events` records only account ID, request ID, short event/target codes, outcome, and UTC time. A financial route must write the actor event in the same database transaction as its mutation and idempotency response when it claims atomic replay safety.

No financial mutation route is currently registered, so none claims automatic retry safety. Filesystem side effects (notably upload archives) need a route-specific verified recovery/deduplication protocol before retry promises. Remote mutating automation and attention-file commits must remain unavailable until every AutomationService entry point checks verified readiness and creates its own successful verified pre-import backup before processing. These changes do not remove the current CLI or Streamlit fallback.

Back up the database and source archives using the existing verified backup procedure and a protected destination. If preserving current sessions across host restore is required, store `api-secret.key` separately under equivalent host-level access controls because the current verified backup omits it. Keep restore manual and operator-controlled. Before household rollout, verify the reverse proxy/Tailscale ACL, HTTPS/certificate lifecycle, both account logins and equal permissions, session revocation, CSRF/origin rejection, backup verification, and a documented restore practice. T12 retires Streamlit only after the broader parity and recovery acceptance gate passes.
