# Runtime image security investigation — 24 October 2026

This is a source/build change for review. It does not update the running trial,
Windows task, Tailscale route, recovery keys or external backup media. The Linux
systemd deployment is unchanged. Merging does not authorize real financial data.

## Remove unused components while retaining application runtimes

The API and web runtime stages use digest-pinned
`gcr.io/distroless/cc-debian13:nonroot`. Python remains **3.12.15** from the existing
pinned official Python image; Node remains **22.23.4** from the repository-pinned
official Node image. Build/test stages retain their package managers. Production
API/web stages have no shell, Perl, mount/nsenter utilities or package manager.
Use the existing Python/Node maintenance entry points; shell-based debugging
requires a separate disposable diagnostic environment.

`python_rootfs.py` copies the interpreter, standard library and shared libraries
needed by its working native extensions. Libraries already in the pinned Debian
13 base retain that base's versions. Additional libraries retain their real Debian
package/version records under `/var/lib/dpkg/status.d`, copyright notices and a
file-hash manifest under `/usr/share/familyfin/python-runtime.json`. This is a
partial-file runtime overlay, not a package-manager installation. It does not
remove inventory records to hide findings. pip/ensurepip and build tools are not
copied. The official slim image's existing unavailable Tcl/Tk GUI libraries remain
explicitly recorded; unexpected missing extension libraries stop the build.

The base [project documents its minimal contents and signature identity](https://github.com/GoogleContainerTools/distroless).
The pinned index digest is
`sha256:3ee00291cf386ec52a552e6a858d555debd74776eb4bfa53fa3df2cd6677515e`.
Its signature was verified locally with Cosign 3.1.4, pinned image digest
`sha256:0f06154836d2de34f887a5c273506d52ca43edaa1d9e53e6510fa78a48f69c2d`,
certificate identity `keyless@distroless.iam.gserviceaccount.com`, issuer
`https://accounts.google.com`; signature claims, certificate chain and logged
inclusion passed. Repeat verification when changing the base digest.

## Raw scan results and remaining applicability review

The same pinned Trivy scanner scanned exported images without a Docker socket,
financial mounts or uploaded private artifacts. Counts are package/advisory
matches, not a count of independent remotely exploitable bugs. No ignore file,
severity reduction or automated exception was added. MEDIUM/LOW reports remain.

| Runtime | Previous HIGH / UNKNOWN | Candidate HIGH / UNKNOWN | Strict gate |
| --- | --- | --- | --- |
| API | 44 / 1 | 6 / 0 | **FAIL** |
| Web | 43 / 1 | 0 / 0 | PASS |
| Caddy | 0 / 1 | 0 / 1 | **FAIL** |

No Python or Node application-package vulnerability was reported in these runtime
scans. This does not cover development dependencies or Windows/WSL/Docker itself.

The API's six retained HIGH matches are:

| Advisory | Scanner package matches | Component described by primary advisory | Candidate evidence |
| --- | --- | --- | --- |
| [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) | `libncursesw6`, `libtinfo6` | `infocmp` CLI overflow | These libraries support existing Python extensions; the `infocmp` executable is absent. |
| [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642) | `libuuid1` | privileged mount helper/hooks | Only the UUID library is copied; mount helpers are absent. |
| [CVE-2026-78408](https://security-tracker.debian.org/tracker/CVE-2026-78408) | `libuuid1` | `nsenter --join-cgroup` | `nsenter` is absent. |
| [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409) | `libuuid1` | `mount` subdirectory resolution | `mount` is absent. |
| [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) | `libuuid1` | restricted privileged bind mounts | `mount` is absent. |

Debian's stable-release records still list these source packages as affected.
**Assessment for review:** the described vulnerable executable code is absent
from this candidate. This inference does not patch the retained libraries or
change the scanner's FAIL. A reviewer must accept the applicability evidence or
require another fix before clearing the production security gate. New advisories
against these libraries require a fresh assessment.

Caddy's [GO-2026-5932](https://vuln.go.dev/ID/GO-2026-5932.json) concerns the
unmaintained `golang.org/x/crypto/openpgp` package and its subpackages. The module
is present for other functionality, so a module-level scanner still reports
UNKNOWN. Its pinned build now records the **exact `go list -deps` package set**
with the same target/toolchain/CGO settings, rejects any OpenPGP import, and ships
hashes binding the package list and executable together. Runtime checks verify
both hashes and absence of all affected imports. Assessment: affected packages
are not compiled into this binary. The raw UNKNOWN remains visible pending
review; upgrading the module alone cannot resolve an all-versions package notice.

## Validation and rollout boundary

`check_runtime_images.py --tag candidate-UNIQUE` tests non-root, read-only images
without network, ports, host mounts or financial volumes. It exercises Python
native extensions, SQLite online backup/integrity, compression, long-name PAX,
workbooks/Parquet, TLS trust, copied-library hashes, Node/Sharp and Caddy evidence.
The Docker runtime workflow repeats these checks against built production images.
It is a compatibility gate; a green job does not waive scanner findings.

Local amd64 candidate validation passed all eight existing synthetic groups:
startup/migrations/hardening; two-user bootstrap/import; sessions/authentication/
CSRF; recreation/persistence; filesystem/volume isolation; application snapshot
verification; separate clean restore/audit/reauthentication; port/LAN probes and
preservation of every pre-existing service and Serve setting. Lab ports were
8092/8093. Only owned candidate containers/networks were removed; disposable
volumes and private evidence were retained. No phone acceptance is claimed for
these new images. ARM and other architectures have not been validated.

The security branch's isolated Python suite passed **346 tests and 51 subtests**,
with four explicit skips (two unavailable personal workbooks and two Windows-only
checks). The existing age round-trip/long-name recovery regressions executed with
reviewed Linux tools. Repository lint and additional helper lint passed.

A separate one-off drill also used the **production API candidate itself** to
pack its real synthetic application snapshot, encrypt with the pinned Windows
age tool, authenticate/decrypt into a new labelled Linux staging volume, finalize
manifest/schema verification, and restore into a new clean financial volume.
SQLite integrity, migration revision, two users, imported transaction/accounts,
actor audit history and application audit passed; no old signing key was restored.
Verified staging was removed and the source snapshot retained. The ciphertext
and disposable key remained local on the host. **This is runtime compatibility
evidence, not an independent physical-media or key-custody drill.** No external
drive was accessed. Existing services and Serve were identical afterwards.

Raw scan JSON, export hashes, exact image identities and local drill receipts stay
in Git-ignored `deploy/docker/reports/` and `.state/`. Review the exact built image
identities before any rollout; rebuilding may change the image index even when
the executable/config content is unchanged. Scan the selected build again.

Production remains gated on review of retained findings, reviewed-image promotion
and phone acceptance, independent recovery-key custody/physical-media recovery,
and a permanent scheduling/retention/alert policy. The separate calendar-schedule
PR changes source only; the temporary running task remains on its approved code
and expiry. Neither PR extends the synthetic trial or accepts production risk.
