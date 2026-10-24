# Windows deployment validation scope

This document contains shareable validation scope; private host receipts, detailed
scan exports, real network identifiers and key material are intentionally excluded.
Never treat build success or a generic report as host-specific production approval.

## Review cleanup — 24 October 2026

- Restore now rejects signing keys, symlinks, hardlinks and special files before
  writing the destination. A Linux descriptor-relative copy refuses link traversal;
  copied bytes are application-verified in staging before publication. A failed
  restore retains an incomplete marker that blocks API startup. Tests include a
  deliberately altered, otherwise verified manifest and an outside-directory link.
- Management/health verification uses explicit errors under optimized Python.
  Acceptance harness imports refuse optimization so their assertions cannot be
  removed while still producing a report. Lab config/evidence paths are explicit;
  fixed topology/fixture requirements are documented separately from runtime tools.
  Preparation binds the selected report/tag and reviewed image configurations to
  its protected receipt; follow-up helpers validate and reuse that profile.
- The unused BitLocker-only export route is retired. Age remains the supported
  Windows export. Snapshot inventory/admission guards and a manual retention
  review procedure bound further growth without deleting retained data.
- Locked Python suite: 330 passed, four documented skips, 44 subtests. Native
  Windows safety tests: 55 passed. Lint passed. Actual age long-filename encrypted
  round trips and clean application restores executed in the suite.
- A separately tagged production API and fresh localhost stack/clean restore
  passed all eight integration groups. All existing services and Serve were
  preserved; only candidate containers/networks were removed. No image promotion,
  task change, external-media writes, live endpoint or real-data activation.
- The changed API was scanned: 44 HIGH OS findings and one UNKNOWN remain FAIL;
  its Python/Node package sections had no findings. Web/Caddy were unchanged, and
  their prior raw scans were reused by verified immutable image/config identity
  and raw-report hash, explicitly recorded as reused rather than fresh scans.
  Their unresolved findings remain FAIL too. No new security exception is implied.

The new snapshot guard can refuse a preexisting full backup volume. Review its
inventory and retention policy before adopting this candidate. Production key
custody, physical/device acceptance and permanent cadence/retention/alert delivery
remain separate gates. The prior frozen trial and its helpers were not updated.

## Candidate validation — 23 October 2026

### PR #22 recovery-review follow-up

The subsequent scheduled-skip review found that `run --if-due` still bypassed the
new archive/key check. Four regressions (missing ciphertext/key, each with and
without `--wait-ready`) reproduced exit zero against the reviewed code. The guard
now requires current recovery readiness before skipping. Unavailable recovery
persists FAIL/history/unacknowledged alert and returns nonzero, preserving the
last-success timestamp. It never creates a replacement backup automatically.
The successful-skip regression also requires the recovery probe and preserves an
existing warning. Full locked Python suite: 288 passed, four documented skips,
40 subtests; native Windows backup/startup tests: 32 passed. Lint passed. These
tests use disposable files; no registered task or running helper was replaced.
All 12 preexisting containers and Serve matched the prior candidate baseline.

Both reported P2 regressions were reproduced against the original review head:
long ASCII/UTF-8 automation filenames failed USTAR packing, and disconnected media,
absent archives or missing keys did not prevent a recent receipt from reporting PASS.
The six regression cases fail against that head and pass with the fixes.

- PAX packing preserves long original filenames with controlled file metadata.
  Real automation imports, verified application snapshots, real age encryption/
  decryption and clean guarded application restore passed for ASCII and Hebrew
  names exceeding 100 UTF-8 bytes. Restored source bytes, financial rows, automation
  provenance, audit and a subsequent verified backup were checked.
- Status now probes current media identity, finalized readable archive and matching
  protected recovery key. An explicit integrity option detects ciphertext hash
  mismatch without changing historical success receipts or acknowledgement state.
- Full locked Python suite: 286 passed, four documented skips, 36 subtests. The two
  age round trips executed locally; CI builds the locked tools and requires them.
  Native Windows backup/startup guards: 30 passed. Lint passed (the extra container
  check of deployment helpers excluded only Windows-mapped executable-bit metadata).
- Eight read-only Windows checks passed against the existing synthetic recovery
  setup, including actual ciphertext hashing and missing/wrong media, archive/key
  and saved-hash fault detection through in-memory test configuration. No disk was
  disconnected or changed; backup-state files, all 12 preexisting containers and
  Serve matched the previous candidate audit and remained unchanged.

These are backup-helper/source tests, not a new runtime-image scan, phone trial,
physical-media write drill or replacement-PC test. Running trial helpers/images and
the registered task were not changed. The candidate image findings and all remaining
production gates below still apply.

### Original candidate build and full stack drill

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
