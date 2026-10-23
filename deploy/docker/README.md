# FamilyFin Windows / WSL2 deployment

Read the [runbook](../../docs/pwa/windows-deployment.md),
[Linux/Docker security comparison](../../docs/pwa/windows-security-assessment.md),
[portable backup procedure](../../docs/pwa/portable-backup.md) and
[validation scope](../../docs/pwa/windows-validation.md).

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
