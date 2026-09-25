# FamilyFin PWA architecture

Status: target architecture with T01/T02 foundations and the T04 Data Quality module implemented. Remaining financial modules follow the ownership and route contracts below.

Implementation update: T01 provides a FastAPI app, two local household identities, server-side sessions, CSRF/origin controls, request limits, request IDs, safe actor audit metadata, and atomic idempotency primitives. T04 adds Data Quality, FamilyBiz import, history, and reconciliation routes. Reconciliation resolution is replay-safe; FamilyBiz commit remains outcome-unknown after a timeout pending verified archive recovery. See [deployment.md](deployment.md) and [api-contracts.md](api-contracts.md).

## Repository baseline and change status

The checked-out repository was clean at commit b8bb6d069ca9e2202ef90504336baa44918d9dd0 on 2026-09-25. The current master contains PR #1 (dashboard review fixes) and PR #2 (import integrity). A live GitHub query returned only those two PRs, both merged; no pending PR was listed.

- [PR #1, Fix dashboard review findings](https://github.com/natanayalo/FamilyFin/pull/1), merged 2026-09-24. Its changes are already in the current tree.
- [PR #2, Import Integrity](https://github.com/natanayalo/FamilyFin/pull/2), merged 2026-09-24. It added deterministic occurrence-aware import planning, a capacity check, expanded parser/import validation, and documentation of a remaining compound-revision matching limitation.
- Completeness and source coverage are current code in metrics and dashboard services, including explicit incomplete/provisional state and an “unknown” coverage value where source completeness cannot be established. No separate pending coverage PR was found.
- Audit and verified backup support predate these PRs and are current: AuditService checks database, schema, archive, provenance, and domain invariants; BackupService creates and verifies a backup set. The automation backup root is currently optional unless configured; this is an existing safety gap, not an acceptable remote-mutation contract. Restore remains a documented manual procedure.

The current app has nine Streamlit pages. The page inventory and exact service/API correspondence are in [ui-parity-matrix.md](ui-parity-matrix.md). The service layer and SQLite model remain the financial source of truth.

## Target shape

Use the existing Python application as the domain/backend. Add a thin HTTP adapter that constructs and calls the existing services; it must not recalculate financial values or persist competing domain state. FastAPI is the proposed adapter because the application is Python 3.12 and already uses Pydantic models. FastAPI, an ASGI server, and multipart parsing are not current dependencies and are future prerequisites, not claims about the present repository.

Use the pinned Shadcn Fintech source only as the preferred visual foundation: layout, shadcn components, responsive table/card patterns, and chart presentation. Replace demo data and demo actions with authenticated calls to the API. The pinned source and audit findings are in [template-audit.md](template-audit.md).

The browser calls a same-origin, versioned JSON API under /api/v1. Financial data is fetched after the user session is checked; do not place it in Next server-rendered HTML, shared caches, static props, URLs, or build output. Keep the API and front end on one household host. The Python API and Next production server are separate loopback processes. A local reverse proxy routes / to Next and /api to FastAPI; Tailscale Serve is the proposed private HTTPS entry point to that proxy. Restrict access with the tailnet ACL, do not use Funnel, and do not bind either application directly to a public interface. The reverse-proxy product and its supervision are not chosen in this documentation-only PR.

The template uses the Next App Router and its documented production command starts a Next server. T00 therefore assumes a Node production process. Static export could remove that process, but the pinned app is not configured or verified for export; treating it as static is an open implementation decision. In either deployment, only static app assets may be cached. The same-origin API must remain online.

## Boundaries and ownership

| Boundary | Responsibility | Must not do |
| --- | --- | --- |
| Browser PWA | Hebrew-first RTL views, mobile layout, form state, charts, accessible validation display, upload selection, preview confirmation, and request status | Recompute balances, monthly metrics, matching, forecast projections, validation policy, or revision hashes; persist financial responses for offline use |
| HTTP adapter | Authenticate, authorize household membership, parse/validate transport shapes, call current domain services, serialize DTOs, map exceptions, paginate collection responses, set cache/security headers, and provide request idempotency | Introduce alternate business rules, update SQLite tables directly for domain mutations, or return ORM internals |
| Existing domain services | Financial logic, import/reconciliation decisions, source and revision provenance, validation, projection, and service transaction boundaries | Depend on Streamlit or browser state |
| SQLite and archives | Existing database, Alembic history, WAL, source archives, imported provenance, and saved revisions | Move to cloud storage or a browser database as part of the UI migration |
| Host operations | Process supervision, HTTPS on the tailnet, filesystem permissions, backup destination, audit and restore runbook | Expose a public internet endpoint or silently restore/overwrite household data |

Keep Streamlit available as the fallback financial UI until the final parity and recovery acceptance gate passes. T12 retires Streamlit after that gate; it is not an indefinite second financial interface. Keep the Python CLI as an ongoing operational interface. Both UIs must point at the same configured data root while they coexist. Keep migrations 0001–0010 and all existing tables/data; add only forward-only migrations needed for app identities, sessions, actor audit, or atomic HTTP idempotency. Do not drop or rewrite imported records, source files, classifications, reconciliation decisions, scenario revisions, forecast revisions, net-worth snapshots, or apartment studies.

Startup should run migrations once before serving traffic, then create one reusable service graph for the Python process. Do not instantiate ImportService per request: its construction initializes the database and builds the related services. Keep the current CLI commands. The legacy Streamlit app stays available as a recovery/fallback UI only until the final parity and recovery gate passes; T12 retires it after sign-off.

## Authentication and authorization

Tailscale access is the network boundary, not the household application identity. Add exactly two individually named application accounts with equal read and edit permissions. Do not offer public registration, third-party sign-in, or an administrator-only financial role. Require application authentication even from an allowed tailnet device.

The API foundation now provisions exactly two individually named household accounts through a one-time local host bootstrap; both accounts have equal permissions and there is no public registration, third-party login, or administrator-only financial role. Passwords use salted scrypt hashes. An authorized host operator can reset one account at the console; the reset revokes that account's sessions. Sessions are server-side, revocable, eight hours by default, and referenced by Secure, HttpOnly, SameSite=Strict cookies. Mutation requests require same-origin checks and CSRF tokens, and login attempts are throttled. Never keep credentials or session tokens in localStorage. MFA is not implemented and remains a product/security decision for a future review.

The current provenance records imported source files, batches, transaction links, assumptions, and immutable revisions. They do not consistently record which household user made a change. If actor attribution is required, add an append-only actor audit record for authenticated mutations and preserve the actor across Streamlit/CLI flows where practical. This requires a schema/service integration design because existing services commit their own transactions; an HTTP-only log written after the financial commit would have a crash gap. Do not claim actor provenance exists today.

## Network, deployment, and privacy

The existing Streamlit config binds to 127.0.0.1. For the PWA, expose only the reverse proxy through Tailscale Serve over HTTPS, proxying to loopback services. Configure the tailnet ACL for the two approved household identities/devices, disable public Funnel exposure, firewall other interfaces, and verify the host’s tailnet DNS/certificate lifecycle. Tailscale Serve is designed for tailnet-only access, uses TLS certificates when HTTPS is enabled, and applies tailnet access controls; see the [Serve guide](https://tailscale.com/docs/features/tailscale-serve) and [Serve CLI reference](https://tailscale.com/docs/reference/tailscale-cli/serve). Tailscale deployment and ACL configuration are not present in this repository.

Serve the app shell and API from one origin to avoid cross-origin credentials and broad CORS. API responses containing household data use Cache-Control: no-store and private; do not enable shared proxy caching. Disable request-body, cookie, Authorization-header, and query-string logging. Continue the existing privacy-safe event convention: event names, UTC timestamps, durations, aggregate counts, and issue/error codes only. Do not log descriptions, amounts, account references, uploaded content, tokens, passwords, or session identifiers.

PWA requirements:

- The app must require an online authenticated API for every financial view and mutation.
- The service worker may cache versioned static JavaScript, CSS, icons, and fonts only. Exclude /api, HTML containing personalized data, and uploads from every cache rule.
- On loss of connectivity, show an explicit reconnect state and disable mutations. Do not show stale financial content or queue edits.
- Do not use IndexedDB, Cache Storage, localStorage, or persistent browser state for financial responses, uploads, preview tokens, or drafts. Keep a preview in memory only; require a fresh preview after reload.
- Add a manifest, locally hosted icons, install guidance, and offline shell behavior that contains no financial values. The pinned template has no manifest/service worker.
- Host fonts and other runtime assets locally. No telemetry, analytics, external financial APIs, or third-party runtime requests.

## Concurrency and request safety

The database enables SQLite WAL and its write-session/transaction gateways use BEGIN IMMEDIATE. This serializes writers, but it does not make stale UI edits safe by itself. Run one API worker initially and preserve the database’s transaction boundaries; do not deploy multiple database copies or a network filesystem.

Pass the current revision number for planning, forecast, apartment, and net-worth updates wherever the service accepts an expected revision. A conflict returns HTTP 409 and requires the client to reload current state before deciding whether to reapply the user’s edit. Import preview tokens already bind file/parser/matcher/decision-plan and matching-baseline state and are checked again at commit. CSV and history seeds have their own service tokens. Never trust a client-calculated revision hash.

Some current writes lack a service-level expected revision, including classification changes and account lifecycle operations. SQLite will serialize the writes, but the second user can still act on stale displayed state. The API workstream must document those limits and either add conditional transport checks around the current service state or defer those controls to a service/persistence follow-up; it must not report a conflict guarantee that does not exist.

An Idempotency-Key by itself does not make a mutation safe to replay. Existing services manage their own transactions, so a separate API metadata write after service commit has a crash window and is not an acceptable contract. T01 must use an API-owned SQLite unit of work for any route that claims replay safety: the domain change and completed idempotency result must commit in the same transaction, with existing services participating without independent commit. Same-key concurrent requests must serialize and re-read the committed result; key reuse with a different canonical request returns 409. A crash before commit rolls back both; a crash after commit leaves both available for replay. External filesystem effects need their own verified recovery/deduplication protocol or the route cannot claim replay safety. Do not blanket-mark routes retryable before they pass this gate. Until then clients must not automatically retry after timeout; they show outcome unknown and ask the user to reconcile state before any resubmission.

## Backward compatibility and migration

1. Preserve the current Python financial services and their return/exception semantics. Route handlers adapt those results; new Pydantic transport DTOs may wrap but must not replace domain models.
2. Preserve the current SQLite file, archive directories, Alembic history, and content hashes. Database initialization remains the Alembic path already used by Database.
3. Keep CLI inspect, audit, backup, verify-backup, and automate commands as ongoing operational interfaces. Keep Streamlit pages and localhost configuration until final parity and recovery acceptance passes; T12 retires Streamlit after that gate.
4. During rollout, compare PWA responses with existing service outputs for the same filters and saved revisions. No independent JavaScript formulas are allowed.
5. Keep restore manual and operator-controlled. The application has no safe automated restore service or Streamlit flow today.

## Unsupported and unresolved requirements

- The repository has no HTTP API, authentication, household-user table, session store, PWA manifest/service worker, Tailscale configuration, or production supervisor.
- The local reverse-proxy product and process supervisor are not selected.
- Exactly two accounts and equal authorization are product requirements but have no current implementation.
- Actor attribution for edits is absent from current saved revision metadata.
- Tailscale host, device ACLs, certificate naming, credential bootstrap/recovery, MFA, and backup destination/retention are not specified by repository code.
- The pinned source is not RTL-ready at the app root and is not configured as a static export.
- No restore endpoint exists. Restore is manual and must remain so unless a separate, reviewed recovery design is approved.
- Current UI lets the user download the complete import decision plan. The PWA should preserve this action only behind authentication and no-store download headers; whether any import-plan fields need additional redaction is unresolved.
- Existing classification/account writes lack consistent optimistic revision tokens. Their exact concurrent-edit behavior must be agreed in the API implementation before claiming lost-update protection.
- The final parity and recovery acceptance gate must be defined and signed off before T12 retires Streamlit. It must include workflow parity, verified backup readiness, a successful restore practice, and verified private access. The operational owner and evidence retention location remain undecided.
