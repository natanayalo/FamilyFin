# Windows deployment validation scope

This document contains shareable validation scope; private host receipts, detailed
scan exports, real network identifiers and key material are intentionally excluded.
Never treat build success or a generic report as host-specific production approval.

## Candidate validation — 23 October 2026

The candidate is based on the merged application-security update (#21), with the
complete platform lockfile and normal Next lockfile validation enabled. Clean
install/offline production build passed without a missing-SWC/repair warning;
the build checked the unchanged lock hash. The API's default Docker build target
is the production runtime, and pytest/ruff/debugpy are absent from that runtime.

- Python lint and tests: 270 passed, four skips (two absent real-workbook inputs,
  two Windows-specific checks), plus 36 subtests.
- Native Windows guard/backup/startup tests: 51 passed.
- Frontend: lint, types, five Node tests and 160 component tests passed.
- Actual service-worker handler harness: four passed; this is not phone CacheStorage.
- Fresh localhost candidate/clean-restore drill: all eight integration groups passed,
  including migrations, auth/session/CSRF, persistence after recreation, storage
  isolation, complete application backup/verify, financial/archive/audit/schema
  restoration, old-session rejection and both-user reauthentication.
- All original services and Serve were unchanged. Candidate containers/networks
  were removed; synthetic volumes and private evidence were retained. No promotion.

Strict image scans remain **FAIL**: API has 44 HIGH OS findings plus one UNKNOWN,
web has 43 HIGH OS findings plus one UNKNOWN, and Caddy retains one module-level
UNKNOWN. No Python/Node runtime-package findings were reported. The Caddy Alpine
library HIGH finding was removed by pinning brotli-libs 1.2.1-r0, available in the
[official Alpine package repository](https://pkgs.alpinelinux.org/package/v3.23/main/x86_64/brotli-libs).
Unfixed Debian findings and the UNKNOWN notice were neither hidden nor waived.
The raw scans and exact index/config identities are retained in private local evidence.
The existing trial exception does not authorize promotion of these changed images.

This candidate drill covers application backup/clean restore, not a new physical
media/replacement-PC or phone-storage acceptance test. Earlier portable and phone
evidence remains scoped to its tested release/environment. Remaining gates below
still apply; successful local checks do not make this production-approved.

The implementation has been exercised with disposable data through production
build/start, migrations, two-user login/logout/session/CSRF boundaries, health/headers,
SQLite persistence after recreation, API-only storage isolation, full application
backup/verification and clean restoration. Restore checks compare financial and
archive content, audit/migration state, old-session denial, both-user reauthentication
and a new verified backup. Original unrelated services and Serve are compared before
and after; candidate containers/networks are removed while evidence/volumes remain.

Portable recovery additionally covers copied-key Linux decryption without DPAPI,
wrong keys, corrupt/truncated ciphertext, interrupted producers, unsafe tar entries,
nonempty targets, wrong/missing media, stale-state catch-up, duplicate suppression,
process locks and persistent failure acknowledgement. Windows tests exercise task
monitoring, bounded startup readiness and preservation of reviewed restart baselines.
An observed Windows sign-in trial confirmed automatic Docker startup and a login
job waiting for API readiness before successful completion. A fresh pre-restart
backup was retained; no additional login archive is inferred from that skip.

## Evidence to collect for each exact candidate

| Check | Required evidence |
| --- | --- |
| Build / locks | Clean npm ci, offline Next build without SWC repair warnings, unchanged lock hash; locked Python/Go dependencies |
| Application / frontend | Python tests/lint, component/lint/type/health/lockfile tests and service-worker handler harness |
| Images / advisories | Exact index/config identity chain, raw scanner output, database/scanner identities and explicit unresolved findings |
| Synthetic integration | Fresh candidate/restore volumes, executed auth/CSRF/health/persistence/isolation/backup/restore assertions |
| Preservation | Original service IDs/configuration/states/ports/Serve identical after owned candidate cleanup |
| Physical recovery | Selected encrypted destination, copied recovery key, authenticated decrypt and matching application audit |
| Phone / cache | Actual approved device/TLS/session flows, install/offline/return-online and browser storage evidence |
| Exposure | Every published binding plus independent LAN/IPv6 and unauthorized-device policy evidence or explicit limits |
| Availability / schedule | Actual approved restart/login ordering and task results; distinguish duplicate skip from fresh archive creation |

Record PASS, FAIL, UNVERIFIED or an explicit user-approved SKIPPED with supporting
scope. The automated worker harness is not an inspection of iPhone CacheStorage.
Own-host LAN probes are not independent-peer or IPv6 evidence. Historical M0 policy
tests are not newly executed M1 tests. Partial mobile evidence must stay labelled.
Signed-out/before-login/lock/sleep availability and future calendar runs require
separate observations; do not repeatedly restart a host to repeat a passed condition.

No real-data readiness claim is made. Production still needs an exact-image security
decision, separately retained recovery identity/recovery proof, accepted calendar
cadence/retention/capacity/alerting, host availability policy and explicit household/
real-data activation. Raw unpatched image or development findings remain FAIL;
record-only scanning or a bounded synthetic exception does not remove them.
