# Linux systemd / Docker security comparison

The Windows path retains application authentication, CSRF, same-origin policy,
security headers, migrations, audited backup and clean recovery. Linux unit files
and their listeners remain unchanged by this deployment change.

| Guarantee | Linux systemd | Windows / WSL2 Docker equivalent and limit |
| --- | --- | --- |
| Dedicated identity | Service user | Distinct non-root API/web/Caddy UIDs |
| Restricted root writes | ProtectSystem / writable path exceptions | Read-only rootfs, explicit bounded tmpfs; API-only named financial volume |
| Privilege restrictions | NoNewPrivileges / capability bounds | no-new-privileges, all capabilities dropped, no privileged containers |
| Service isolation | systemd namespaces and unit policy | Separate containers/internal bridge; no host financial binds or Docker socket |
| Network exposure | Loopback API/web behind proxy | API/web unpublished; only Caddy loopback-published, upstreams use service DNS |
| Resource/process limits | Unit controls | CPU, memory, PID, stop grace and log bounds |
| Process recovery | Restart policy | unless-stopped and health checks after Docker Desktop starts; health alone does not restart an unhealthy process |
| Working data | Restricted Linux data root | Linux-backed named volume with owner-only application paths; no NTFS SQLite bind |
| Transport/authentication | TLS proxy, same-origin auth/CSRF | Existing Tailscale HTTPS terminator, Caddy and unchanged app checks |
| Secret custody | Protected host files | Runtime owner-only signing key, excluded from images/backup; operator-controlled external recovery identity |
| Backups | Application snapshot, audit and verify | Same application services in bounded networkless maintenance containers; independent encrypted export required |
| Recovery | Matching schema/release and reauthentication | New empty volume; pre-copy key/link/special-file rejection, no-follow copy, staged verification/audit, incomplete-restore startup block, new signing key and old-session rejection |
| Verification | Unit health/maintenance checks | Explicit runtime/management errors survive Python optimization; assertion-based lab imports reject optimized Python |
| Snapshot growth | Operator retention policy | Read-only inventory and snapshot admission limits; no automatic deletion; review permanent retention/capacity policy before production |
| Host encryption | Host policy | Separately verify system-volume encryption/recovery; Docker is not an encryption boundary |
| Scheduled work | systemd timer | Explicitly approved least-privilege Windows task; signed-in/Docker/media availability must be tested |

Containers do not reproduce every systemd syscall/address-family restriction.
Docker daemon/Windows administrators can access volumes and are trusted. Desktop
startup depends on the chosen Windows login policy. Independent media/key recovery,
calendar cadence, capacity/retention and unattended failure delivery require explicit
production acceptance. No host or application guarantee follows from a green build.

Pinned images may still contain unpatched OS findings. Scan exact final identities,
retain raw HIGH/CRITICAL/UNKNOWN failures and document applicability/fix availability.
A supervised synthetic exception, if approved, is bounded to exact images, data,
access and expiry; it does not authorize production or later image replacement.
Dependency/candidate changes require new evidence and promotion review.
