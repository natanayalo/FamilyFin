# FamilyFin Windows / WSL2 deployment

Read the [runbook](../../docs/pwa/windows-deployment.md),
[Linux/Docker security comparison](../../docs/pwa/windows-security-assessment.md),
[portable backup procedure](../../docs/pwa/portable-backup.md) and
[validation scope](../../docs/pwa/windows-validation.md).
See also the [runtime image security investigation](../../docs/pwa/runtime-security.md)
for the minimal runtime changes, retained scanner findings and validation limits.

Defaults are disposable localhost labs, not household bootstrap or a Tailscale
cutover. Linux systemd remains supported. The Windows host needs Python 3.12+,
PowerShell, Docker Desktop's local Linux named-pipe endpoint, Engine 28+ and
Compose 2.24.4+. Those minimums express compatibility, not a security endorsement.

```powershell
./deploy/docker/start.ps1 -Build
./deploy/docker/verify.ps1
./deploy/docker/backup.ps1
./deploy/docker/stop.ps1
```

Helpers reject ambient/remote endpoint overrides, fix lab origins/ports, check
project/volume ownership and never delete volumes. Ordinary labs use 8090/8091.
`validate.py` requires fresh financial volumes and creates disposable users/data.
`test.ps1` builds isolated Python/frontend test targets. `cache.test.mjs` exercises
the actual service-worker handlers with controlled cache/network objects.
`check_runtime_images.py --tag candidate-UNIQUE` checks production runtime native
libraries, workbook/SQLite/archive compatibility and Caddy dependency evidence in
isolated containers. API/web runtimes have no shell; use their Python/Node entry points.

For a separately built candidate, scan its exact tags first, then use
`validate_candidate.py --tag candidate-UNIQUE --run-id UNIQUE`. It uses fresh labs
on 8092/8093, checks backup/clean restore and preserves every existing service and
Serve configuration. It removes only its containers/networks; evidence and volumes
remain. Scanner FAIL is retained and grants no promotion or exception.

`.state/` and `reports/` are private, Git-ignored and excluded from image builds.
Do not force-add receipts, private hostnames, key material, financial files, image
exports or host scan logs. Publish only separately reviewed summaries. Mobile,
portable and host-recovery helpers are guarded synthetic POC workflows; their
private receipts must be prepared on the target host, never copied from another PC.

## Tool boundaries

| Scope | Files and contract |
| --- | --- |
| Container runtime | Compose, Dockerfiles, Caddyfile, `runtime.py`, `operations.py`; no lab receipts required |
| Windows backup core | `portable_backup.py`, `portable_stream.py`, media/task helpers, `backup_readiness.py`; explicit reviewed config, pinned image and independent key/media |
| Local lab operations | `manage.py` and start/stop/verify/backup wrappers; fixed disposable projects and loopback ports, never a household installer |
| Synthetic acceptance | `validate*.py`, `mobile.py`, `host_recovery.py`, `portable_setup.py`, `rollout_reviewed.py` and task registration; see [lab prerequisites](lab-workflows.md) |

Runtime and management security checks use explicit failures and remain active
with Python optimization. Synthetic acceptance harnesses retain test assertions
and reject optimized Python at import, preventing incomplete tests from producing
a PASS report. The retired BitLocker-only backup route is not supported; use age.
