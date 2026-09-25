# FamilyFin PWA API contracts

Status: proposed transport contract for follow-up implementation. No HTTP API exists in the checked-out repository. Routes below adapt current Python services; they are not evidence of implemented endpoints.

## Common rules

- Base path: /api/v1. Same origin as the PWA. All routes except sign-in, sign-out, and session bootstrap require an authenticated household session.
- All requests and responses use UTF-8 JSON unless a route explicitly uploads or downloads a file. JSON responses use the envelope below; file downloads use ordinary content headers and no-store.
- The API is a transport adapter. It calls the existing domain services and returns their serialized results. It must not recalculate amounts, projections, status, classification, matching, completeness, or provenance in TypeScript.
- Never place financial response data, credentials, preview tokens, or draft edits in URLs, persistent browser storage, logs, analytics, or shared caches.

Success envelope:

| Field | Meaning |
| --- | --- |
| data | DTO or page result |
| meta.request_id | Server-generated request identifier safe to show in an error report |
| meta.next_cursor | Opaque cursor for a paginated collection; null at end |
| meta.limit | Page size when the result is paginated |

Error envelope:

| Field | Meaning |
| --- | --- |
| error.code | Stable API code such as VALIDATION_ERROR, PREVIEW_STALE, STALE_REVISION, DUPLICATE_SEED, or DATABASE_BUSY |
| error.message | Short safe message; no traceback, SQL, raw upload values, or credential detail |
| error.fields | Optional field-name to validation-message list |
| error.issue_codes | Optional domain issue codes from the current service |
| error.request_id | Same identifier as meta.request_id |

## Serialization

| Value | Wire form | Rule |
| --- | --- | --- |
| Decimal amounts, rates, ratios, exact counts that are not integers | JSON string | Canonical decimal text, no binary float conversion. Preserve the service’s scale/rounding semantics; do not round for transport. A value such as 0.1 is sent as "0.1". |
| Integer counts and identifiers | JSON integer or string identifier | IDs retain the type used by the domain model; opaque IDs remain strings. |
| Calendar dates | YYYY-MM-DD string | Strict ISO 8601 date. Scenario months are first-of-month dates as used by current services. |
| Datetimes | RFC 3339 UTC string ending in Z or +00:00 | No local-time timestamps on the wire. |
| Currency | Uppercase ISO currency code string | Keep currencies separate; never combine ILS and non-ILS totals. |
| Enums | Existing Python enum value | Do not relabel/translate wire values. Translate only in the Hebrew UI. |
| Optional values | null | Do not substitute zero, empty string, or “unknown” for a missing value. |
| Provenance/revision hashes | String | Preserve exact source file hash, decision-plan fingerprint, assumption hash, revision ID/number, source IDs, issue codes, and origin values returned by services. |

Pydantic domain values are serialized in JSON mode, then reviewed against these wire rules. Returning raw ORM rows is prohibited.

## Validation, errors, and status codes

| HTTP status | Use |
| --- | --- |
| 200 | Successful read, preview, comparison, or update with a representation |
| 201 | Created scenario, rule, snapshot, forecast, study, or import batch |
| 204 | Successful sign-out or a delete-shaped action with no body |
| 400 | Malformed transport syntax or unsupported request shape |
| 401 | Missing, expired, or invalid application session |
| 403 | Authenticated identity is not one of the enabled household users |
| 404 | Missing resource or resource not visible to this household |
| 409 | Stale preview/revision, duplicate seed, existing-snapshot conflict, or conflicting state transition |
| 413 | Upload exceeds transport or configured domain size limit |
| 422 | Domain validation failure, invalid workbook/CSV, invalid decision, or rejected field values |
| 503 | SQLite write lock/busy condition or unavailable local service; include Retry-After only when a safe retry is possible |
| 500 | Unexpected failure with a generic message and request ID only |

Field validation remains owned by the existing service/parser. The API may reject malformed transport types before calling it, but must not weaken workbook, CSV, decimal, date, account-coverage, category, schedule, classification, forecast, mortgage, completeness, or stale-valuation validation. Return safe service errors and issue codes; do not expose uploaded row content in logs.

Important configured file limits in the current code: FamilyBiz XLSX 25 MiB compressed, 100 MiB uncompressed, and at most 50,000 rows; planning CSV 10 MiB, 5,000 rows, 100 columns, 10,000 characters per field; net-worth CSV 10 MiB, 10,000 rows, 20 columns, 10,000 characters per field. Confirm the parser is authoritative when configuring reverse-proxy body limits.

## Collections and pagination

Collection routes accept limit (default 50, maximum 200) and cursor (opaque, optional) and return items plus next_cursor and limit in meta. Cursors are scoped to route and filters and must not expose personal values. Preserve a deterministic order from the existing repository/service result before slicing. Page locally at the HTTP adapter when a current list service returns all rows; do not add new domain service methods solely for pagination. Large filtered classification queues may need a later repository-level query optimization, but the first implementation must remain correct.

Do not paginate a calculation’s required inputs or truncate a service preview. Dashboard series, monthly projection results, revision lists needed for a comparison, and a preview token/plan are returned complete unless a specific route explicitly pages them.

## Preview and commit protocol

1. A preview endpoint validates and analyzes input but does not create the domain records that its later commit creates. It returns the service’s preview token and review data.
2. The browser keeps the token and selected upload bytes only in memory. Do not put them in query parameters, localStorage, IndexedDB, cache, or a persistent draft.
3. Commit resubmits the exact original file bytes and filename where the current service expects them, plus the untouched token and explicit user acknowledgements/mappings.
4. The API passes those exact inputs to the service. The service re-parses/re-validates and checks current baseline/version state. A stale token returns 409 PREVIEW_STALE; the UI must require a fresh preview.
5. A preview is not a commit authorization that bypasses current validation. Never permit commit after the user changes the upload, mappings, or relevant source assumptions without re-previewing.

Current preview-token families:

| Flow | Current service contract | Commit-specific behavior |
| --- | --- | --- |
| FamilyBiz | ImportService.preview_import / preflight_import; token binds file hash, parser/matcher/plan versions, and matching baseline | ImportService.commit_import receives original bytes, token, and filename; current baseline is checked and deterministic decisions are recomputed |
| Planning history | PlanningService.preview_history_seed | commit_history_seed receives token; no upload bytes |
| Planning CSV | PlanningService.preview_csv_seed | commit_csv_seed receives original bytes, token, and explicit category mappings; control gaps require acknowledgement in the UI contract |
| Net-worth CSV | NetWorthService.preview_csv | commit_csv receives original bytes, token, filename, create_new_revision, and quality_acknowledged; an existing snapshot date may produce a conflict unless explicitly creating a new revision |

The FamilyBiz preview also displays and downloads the complete deterministic decision plan. Preserve preview counts, issues, plan version/fingerprint, matching baseline, and sample rows. Protect the full download as household data. A network timeout must not cause the client to blindly repeat a commit.

Use Idempotency-Key on state-changing requests. This is new API metadata, not a financial-domain token. Save the authenticated actor, route, request-body hash, and completed response so an identical retry returns the original response; reject reuse with a different request. Do not reuse an idempotency key for a different action.

## Revision and concurrent-edit protocol

For services that accept expected_revision_number, send it from the currently loaded resource on save and restore. A stale value returns 409 STALE_REVISION with the current revision number and directs the client to reload. Restoring an old revision appends a new immutable current revision; it never rewrites the historical revision.

The current services have explicit expected revision support for planning save/restore, forecast save/restore, net-worth save/restore, and apartment save/restore. Import tokens are also stale-state checks. Do not pass an expected_revision_number to a service signature that does not accept one.

Current service writes without a comparable service-level precondition include classification override/rule operations, scenario/forecast/study archive toggles, and net-worth account lifecycle operations. Database write transactions serialize commits but do not alone prevent a second user from submitting stale data. This is an explicit gap; the API must not claim optimistic concurrency for these routes until the implementation adds a safe conditional check.

## Proposed route catalog

Every row is a proposed wrapper around named existing services. Request bodies use domain fields from their existing Pydantic input models; the parity matrix lists screen semantics and acceptance scenarios.

| Capability | Proposed route | Existing service call(s) |
| --- | --- | --- |
| Sign in/current session/sign out | POST /auth/session, GET /auth/session, DELETE /auth/session | New authentication infrastructure; no current auth service exists |
| Overview | GET /dashboard/overview | DashboardService.default_filters, overview |
| Expenses and transaction contributors | GET /dashboard/expenses; GET /dashboard/contributors?transaction_ids=... | DashboardService.expenses, contributors |
| Data quality | GET /dashboard/quality | DashboardService.data_quality |
| FamilyBiz preview/commit | POST /imports/familybiz/previews; POST /imports/familybiz/commits | ImportService.preview_import, commit_import |
| Import history | GET /imports/history | ImportService.history |
| Reconciliation | GET /reconciliation/cases; POST /reconciliation/cases/{case_id}/resolution | ImportService.reconciliation_cases, resolve_reconciliation |
| Classification review | GET /classification/review-queue; POST /classification/transactions/{transaction_id}/override; DELETE /classification/transactions/{transaction_id}/override | ClassificationService.review_queue/list_review_queue, save_override, clear_override |
| Reusable rules | GET /classification/rules; POST /classification/rules/previews; POST /classification/rules; POST /classification/rules/{rule_id}/disable | ClassificationService.list_rules, preview_rule, create_rule, disable_rule |
| Planning scenarios | GET /planning/scenarios?include_archived=...; POST /planning/scenarios; GET /planning/scenarios/{scenario_id}; POST /planning/scenarios/{scenario_id}/clone; POST /planning/scenarios/{scenario_id}/archive | PlanningService.list_scenarios, create_manual_scenario, get_scenario, clone_scenario, archive_scenario/unarchive_scenario |
| Planning seeds | POST /planning/seeds/history/previews; POST /planning/seeds/history/commits; POST /planning/seeds/csv/previews; POST /planning/seeds/csv/commits | PlanningService.preview_history_seed, commit_history_seed, preview_csv_seed, commit_csv_seed |
| Planning revisions and comparisons | GET /planning/scenarios/{scenario_id}/revisions; POST /planning/scenarios/{scenario_id}/projections; POST /planning/scenarios/{scenario_id}/revisions; POST /planning/scenarios/{scenario_id}/revisions/{revision_number}/restore; POST /planning/comparisons; GET /planning/scenarios/{scenario_id}/actual-comparison | PlanningService.list_revisions, project_draft, save_revision, restore_revision, compare_scenarios, compare_actual |
| Savings forecast | GET /forecasts; POST /forecasts; GET /forecasts/{forecast_id}; GET /forecasts/{forecast_id}/revisions; POST /forecasts/{forecast_id}/projections; POST /forecasts/{forecast_id}/revisions; POST /forecasts/{forecast_id}/revisions/{revision_number}/restore; POST /forecasts/{forecast_id}/clone; POST /forecasts/{forecast_id}/archive | SavingsForecastService.list/get/create/project/save/list_revisions/restore/clone/archive/unarchive |
| Net-worth accounts/snapshots | GET /net-worth/accounts; POST /net-worth/accounts; PUT /net-worth/accounts/{account_key}; POST /net-worth/accounts/{account_key}/close; POST /net-worth/accounts/{account_key}/reactivate; GET /net-worth/snapshots?include_archived=...; POST /net-worth/snapshots; POST /net-worth/snapshots/{snapshot_id}/revisions | NetWorthService.list/create/update/close/reactivate account, list_snapshots, create_snapshot, save_revision |
| Net-worth CSV/revisions/reporting | GET /net-worth/csv-template; POST /net-worth/csv/previews; POST /net-worth/csv/commits; GET /net-worth/snapshots/{snapshot_id}/revisions; POST /net-worth/snapshots/{snapshot_id}/revisions/{revision_number}/restore; POST /net-worth/snapshots/{snapshot_id}/archive; GET /net-worth/accounts/{account_key}/history; GET /net-worth/summary; GET /net-worth/trend; POST /net-worth/forecast-comparisons | NetWorthService.csv_template, preview_csv, commit_csv, list_revisions, restore_revision, archive_snapshot/unarchive_snapshot, account_history, summary, trend, compare_forecast_actual |
| Forecast pool seed bridge | POST /forecasts/net-worth-pool-seeds | NetWorthService.create_forecast_pool_seeds |
| Apartment studies | GET /apartment/studies?include_archived=...; POST /apartment/studies; GET /apartment/studies/{study_id}; GET /apartment/studies/{study_id}/revisions; POST /apartment/studies/{study_id}/projections; POST /apartment/studies/{study_id}/revisions; POST /apartment/studies/{study_id}/revisions/{revision_number}/restore; POST /apartment/studies/{study_id}/clone; POST /apartment/studies/{study_id}/archive | ApartmentPlanningService list/get/list_revisions/get_revision/project_draft/create_study/save_revision/restore_revision/clone_study/archive_study/unarchive_study; available_pool_balances |
| Automation/insights | GET /automation/status; POST /automation/runs; GET /automation/attention-files; POST /automation/attention-files/previews; POST /automation/attention-files/commits; GET /insights/preferences; PUT /insights/preferences; GET /insights/alerts; POST /insights/alerts/{alert_id}/acknowledge; POST /insights/alerts/{alert_id}/resolve; GET /insights/monthly-summaries | AuditService.run; AutomationService.run/list_attention_files/preflight_attention/commit_attention; InsightsService get/save preferences, list/acknowledge/resolve alerts, list_summary_revisions, summary_markdown, summary_json |
| Audit/backup operations | GET /operations/audit; POST /operations/backups; POST /operations/backups/verify | AuditService.run; BackupService.create, verify. No current restore service or endpoint. |

The current Automation & Insights page reads latest AutomationRunRow directly and calls a private inbox file helper to display status. The adapter may reproduce those existing reads for parity; do not invent a new domain service method and do not expose raw ORM models.

Service-only capabilities are explicitly distinguished from the current Streamlit UI in ui-parity-matrix.md. Do not add them silently under the claim that Streamlit already exposed them.

## Mutation request shapes

Every body below is JSON except explicit multipart uploads. Unknown properties are rejected. Decimal inputs are JSON strings. Inner object validation is performed by the named existing Pydantic model/service; the route layer should not duplicate or weaken its rules.

| Operation | Required body fields |
| --- | --- |
| Reconciliation decision | resolution; transaction_id only for link_existing; optional note. Supported resolutions are accept_as_new, dismiss, and link_existing. case_id comes from the URL. |
| Classification override | At least one of economic_class, analysis_category, expense_behavior; reason. Clearing uses DELETE and optional field names only if the adapter maps to the existing clear_override fields argument. |
| Reusable classification rule | account_kind, direction, source_category, currency, economic_class; optional source_movement_type, analysis_category, expense_behavior, reason. Preview uses the same fields and returns the existing exact-match count. |
| Manual planning scenario | name, currency, start_month, items. Each item uses kind, label, optional category, amount, frequency, and either monthly start_month/end_month or one-time occurrence_month. |
| Planning revision | expected_revision_number, items, optional notes. Existing item IDs and provenance are retained only when the existing PlanningItem model is submitted; new rows use PlanningItemInput. |
| Forecast preview/save | scenario_id, source_revision_number, starting_pools, cases; create additionally sends name and provisional_acknowledged. A pool uses name, optional pool_id, pool_type, opening_balance, as_of_date, and optional net-worth account/revision/valuation/staleness provenance. Each case has role, annual_return_rate, routes, sweep fields, adjustments, events, and confirmed. |
| Forecast adjustment | target_type, target, operation, value, start_month, optional end_month. Existing enum values are retained: line/category; replacement/fixed_delta/percentage_change. |
| Forecast event | event_type, month, amount, label, optional pool_name or pool_id. Contribution/withdrawal events require exactly one pool reference. |
| Manual net-worth account | account_key, display_name, side, category, active_from; optional liquidity for asset accounts, owner_label, active_to, and stale_after_days. The service assigns a key when blank. |
| Manual net-worth snapshot/revision | snapshot_date for create; balances; quality_acknowledged; expected_revision_number for an existing snapshot. Each balance uses account_key, amount_ils, valuation_date, optional notes. |
| Net-worth CSV commit | Multipart file and the original preview_token/filename; create_new_revision and quality_acknowledged. |
| Apartment projection/create | forecast_id, forecast_revision_number, alternatives, guardrails; create additionally sends name and source_quality_acknowledged. Each alternative uses name, forecast_role, purchase_month, property_price, family_gift, purchase_costs, equity_requirement {mode,value}, mortgage {principal,annual_nominal_rate,term_months}, pool_draws, stopped_housing_line_ids, housing_costs, and confirmed. |
| Apartment revision | Same assumption fields as create plus expected_revision_number and optional notes. |
| Net-worth/forecast comparison | forecast_id, observed snapshot revision_id, forecast_revision_number, role. Do not send a snapshot date in place of a revision ID. |
| Insight preferences | planning_scenario_id, forecast_id, forecast_role, apartment_study_id, apartment_alternative_name. Empty selection is null. |

The service return model is the response authority. In particular, do not rebuild a revision snapshot from just the submitted inputs: the service response includes the persisted revision number, generated ID/hash, origin, inherited quality/provenance, and timestamps.

## Provenance convention

Do not normalize away the existing origin names or hashes. Responses for imports, seeds, revisions, snapshots, forecasts, and apartment studies preserve the fields exposed by their current models: source file SHA-256 and archived source reference, import batch/source IDs, reconciliation resolution, matching method, parser/matcher/decision-plan version and fingerprint, seed origin, completeness snapshot and issue codes, source scenario revision, pinned forecast revision and assumption hash, revision number/content hash, CSV archive/reference, snapshot valuation date, and quality acknowledgements.

The API must not infer provenance missing from a service model. Actor identity is a separate new audit concern: current domain provenance describes data origin and revision ancestry, not consistently the household user who submitted a mutation.
