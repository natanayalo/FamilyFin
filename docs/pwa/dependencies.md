# PWA prerequisites and feature-module ownership

Status: follow-up plan for independent implementation PRs. T00 changes documentation only.

## Repository prerequisites

| Area | Present state | Required before feature modules |
| --- | --- | --- |
| Python | Python >=3.12,<3.13; uv project; current runtime dependencies include SQLAlchemy, Alembic, Pydantic, pandas, openpyxl, Plotly, and Streamlit | Keep current Python lock and financial packages. Add FastAPI, an ASGI server, and multipart parsing as API-foundation dependencies. Keep Streamlit installed. |
| Database | SQLite, SQLAlchemy 2, WAL, BEGIN IMMEDIATE write transactions, Alembic migrations through current head 0010 | Keep one active data root and current archive directories. Add only forward migrations for users/sessions, actor audit, and API idempotency if needed. Apply migration once before service startup. |
| Frontend | No JavaScript app or Node toolchain in FamilyFin | Add a frontend workspace, exact Node version pin, package manager and lockfile, TypeScript, Next App Router, React, Tailwind, shadcn components, RTL font assets, and build/lint CI. Do not copy the upstream lockfile wholesale. |
| HTTP | No API or authentication exists | Establish /api/v1, request/response DTOs, authentication/session middleware, domain exception mapping, no-store headers, CSRF, idempotency, and body limits before financial feature routes. |
| Deployment | Streamlit localhost config only; no process supervisor, Tailscale Serve config, reverse proxy, or production docs | Choose always-on host and backup destination; run Python API and Next server on loopback; expose one same-origin HTTPS entry point through Tailscale Serve; restrict tailnet ACL; keep Funnel disabled. |
| PWA | No manifest, service worker, install icons, offline state, or browser-cache policy | Add manifest and local icons; allow only static asset caching; exclude HTML with personal data, all /api responses, files and form state. |
| Source pin | Preferred Shadcn Fintech audit is pinned to e338240d10c908ab49403adbcd0bb4cc980ebfce | Use only this exact source revision if code is copied. Retain MIT attribution and review third-party asset/dependency licenses. See [template-audit.md](template-audit.md). |
| CI | Current GitHub Actions jobs lint/test Python 3.12, run migration cycle, and run import-capacity check | Add a separate frontend dependency/build/lint job. Add API contract and browser flow coverage in the feature PRs; keep current Python and capacity jobs. |

The exact API shapes are in [api-contracts.md](api-contracts.md); feature parity and acceptance scenarios are in [ui-parity-matrix.md](ui-parity-matrix.md). The requirements above are prerequisites, not current capabilities.

## Ownership model for follow-up PRs

Keep backend route ownership and browser feature ownership aligned by feature. Shared API infrastructure and page shell land first; after that, data modules can proceed independently. One PR should not edit another feature module’s DTOs or financial services without coordinating its owner.

Suggested structure:

- Python adapters: src/family_finance/api/routers/<feature>.py and DTOs in src/family_finance/api/schemas/
- Frontend: frontend/src/features/<feature>/, shared shell/components in frontend/src/components/
- Shared versioned contract: docs/pwa/api-contracts.md and a generated OpenAPI document from the actual adapter once implemented
- Financial logic stays in its present domain modules; route handlers call the exact services listed in the parity matrix.

| Follow-up module / owner | Primary scope | Existing Python ownership | PWA route ownership | Depends on | Can proceed independently when |
| --- | --- | --- | --- | --- | --- |
| 0. API, auth, and host foundation | FastAPI app/lifecycle, /api/v1, two app identities, server-side sessions, CSRF, actor identity policy, no-store, request IDs, idempotency, error mapping, body limits, health/status without financial detail, Tailscale deployment guide | New transport package wrapping existing services; no current auth service | Shared fetch client/session pages and global error handling | None; first prerequisite | Contracts are accepted. Needed by all authenticated financial modules before remote use. |
| 1. PWA shell and design system | Pin/upstream attribution, Next workspace, mobile shell, Hebrew/RTL root, local Hebrew font, navigation, responsive table/form patterns, install manifest, static-only service worker | None | Shared shell; sign-in; route stubs for all nine pages | API/auth contract for session UX; template audit | Can start in parallel with API foundation using mock DTO fixtures; must not add financial mock data to production navigation. |
| 2. Overview and Expenses | Filters, headline metrics, comparisons, charts, category behavior/trends, contributors, recurring/anomaly drill-down | DashboardService, MetricsService | /dashboard, /expenses | API foundation; shell | API contracts stable; can deliver as independent read-only PR. |
| 3. Data Quality, imports, reconciliation | Quality panel, XLSX preview/decision plan, download, commit, history, reconciliation resolution | DashboardService, ImportService, parser, repositories | /data-quality | API foundation; shell | Upload/error/token contracts stable. Coordinate with classification only on shared navigation/issue links. |
| 4. Classification | Filtered queue, overrides, clearing, reusable-rule preview/create/history/disable | ClassificationService | /classification | API foundation; shell; Data Quality link only | API contract stable. Concurrent-write policy for overrides/rules is explicitly documented before claiming protection. |
| 5. Planning | Manual scenario, historical/CSV seed previews, mapping acknowledgement, revision editor, restore/clone/archive, projection and comparisons | PlanningService, MetricsService | /planning | API foundation; shell; import/data-quality read access | API contract stable; can develop independently from forecast editor. |
| 6. Net Worth | Account registry, observed snapshots, strict CSV, immutable revisions, account history, aggregates, trend, forecast comparison endpoint | NetWorthService | /net-worth | API foundation; shell | API contract stable. Forecast comparison view may start after Forecast read API exists. |
| 7. Savings Forecast | Scenario/revision pin, starting pools, Net Worth bridge, three case editor, projection, save and existing forecast lifecycle service methods | SavingsForecastService, PlanningService, NetWorthService | /savings-forecast | API foundation; shell; Planning; Net Worth for snapshot seeding | API DTOs include exact planning revision and net-worth source provenance. |
| 8. Apartment Plan | Forecast pin, study lifecycle/revisions, guardrails, alternatives, projection/readiness, mortgage schedule, save | ApartmentPlanningService, SavingsForecastService, PlanningService | /apartment-plan | API foundation; shell; Forecast; Planning | API carries exact forecast revision/hash. |
| 9. Automation & Insights | Audit gate, run-now, status, preferences, attention files, alerts, monthly summaries/downloads | AuditService, AutomationService, InsightsService, existing AutomationRunRow | /automation-insights | API foundation; shell; Import/Planning/Forecast/Net Worth/Apartment | API contracts and data modules stable. Do not expose raw server paths. |
| 10. Operations continuity | Host runbook, audit and backup verification access, manual restore practice, backup destination/retention | AuditService, BackupService, CLI | Current CLI remains; optional /settings/operations only by explicit product decision | API foundation if web operations route is approved; host decision | CLI path can be documented independently. No automatic restore implementation in this module. |

Each module PR owns its route adapter, feature DTO mapping, Hebrew labels, loading/empty/error states, accessibility/mobile behavior, and acceptance coverage for its matrix rows. The core services remain shared, not duplicated per feature.

## Dependency sequence

1. Review this T00 contract; decide user identity bootstrap/recovery, Node deployment mode, host, tailnet name/ACL owners, actor-audit requirement, backup destination/retention, and whether operations controls belong in PWA.
2. Land API/auth foundations and PWA shell concurrently. Keep session identity separate from Tailscale identity. Do not route private data through an external auth or analytics provider.
3. Land independent read-only modules (Overview/Expenses, Data Quality) and then independent write modules (Classification, Planning, Net Worth) once error/Decimal/token contracts are frozen.
4. Land Savings Forecast after Planning and Net Worth; Apartment after Forecast; Automation & Insights after its referenced feature APIs.
5. Run the PWA alongside the unchanged Streamlit/CLI using the same database and archives. Compare each service output before the PWA becomes the primary entry point.
6. Verify private tailnet HTTPS, two-user login separation, mobile installability, offline denial of financial views/mutations, backup verification, and documented manual restore before household rollout.

The sequence does not authorize a financial schema rewrite. Existing service logic and financial invariants remain the compatibility target.
