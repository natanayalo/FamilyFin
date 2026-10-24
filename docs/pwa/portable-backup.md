# Portable encrypted application backup

This path is implemented and validated with disposable data. Production key custody,
permanent scheduling and real-data activation require separate decisions. It does
not change an existing drive's encryption, partitions, root ACLs or unrelated files.

## Format and custody

`portable_backup.py` runs the existing application backup/audit/verify services.
It streams SQLite and managed source archives from Linux storage through standard
age encryption into an exclusively created `.tar.age.partial` file. No plaintext
financial tar is written to Windows/external media. The API signing key is excluded.
Snapshots retain financial/users/audit/migration state and managed source files.
The tar stream uses PAX for long and UTF-8 automation filenames. Headers contain
regular-file paths/sizes with fixed ownership, permissions and timestamps; source
filesystem metadata is not carried into the export. Existing USTAR backups remain
readable through the same guarded receiver.

An archive is finalized only after authenticated decryption into a newly owned Linux
staging volume and application manifest/hash/schema/invariant verification. Extraction
rejects traversal, links, special/sparse/duplicate/secret-key entries and size/count
abuse. Incomplete or unauthenticated stages never become restore sources. Failed
stages/partial files and recovery data are retained. Verified, labelled, unused
verification stages and only the snapshot created by the successful export are
eligible for exact-name cleanup. Historical snapshots and ciphertext are never pruned.

The selected destination must be a new dedicated private NTFS directory on a separate
physical disk, with matching volume/disk IDs and marker, no redirects, private ACLs
and at least 8 GiB free. There is no local fallback. Existing drive files/settings
remain untouched. File-encrypted age export is the supported Windows backup path;
the earlier BitLocker-only wrapper is retired. Drive encryption remains useful
additional protection and is not reconfigured by these tools.
The recovery identity requires protected file/directory ACLs and a different physical
disk from the archive. Never keep its only copy beside archives, in chat, Git or an
image. The synthetic identity is disposable; establish independent production custody
and prove recovery using the retained copy before real data.

## Tool build

`age.Dockerfile` builds age 1.3.2 with digest-pinned Go and checksum-locked modules.
It runs upstream age tests, exports Windows/Linux tools and retains their license
notices. Windows executable hashes are checked before use. Rebuilds must be scanned;
a version label alone is not acceptance. Keep notices when distributing tool bundles.
The format has no DPAPI or Windows-profile binding. Keep a reviewed Linux tool image
and matching application release available for independent recovery.

## Operations

Create only new protected synthetic state/media through `portable_setup.py` after
the guarded mobile preparation receipt exists. It refuses to adopt existing folders
or initialize real household data. The helpers intentionally require a host-prepared
receipt; no private receipt/configuration is distributed in this repository.

```powershell
python deploy/docker/portable_backup.py run --config CONFIG.json
python deploy/docker/portable_backup.py status --config CONFIG.json
python deploy/docker/portable_backup.py status --config CONFIG.json --verify-integrity
python deploy/docker/portable_backup.py stage --config CONFIG.json --archive BACKUP.tar.age --key COPIED-IDENTITY.txt --linux-age-image REVIEWED_IMAGE_SHA256
python deploy/docker/portable_backup.py restore --config CONFIG.json --staged VERIFIED-STAGING-RECEIPT.json --project familyfin-m1-portable-recovery-UNIQUE
```

Recovery refuses an existing target volume. Use the exact matching application
release/schema, start the clean recovery on an unused loopback port, audit/verify
and require reauthentication before proposing any route switch. Preserve original
volumes and ciphertext. A replacement-PC boot test is separate from decryption.

`run --if-due --wait-ready` is the task entry point. It holds an OS lock, waits at
most five minutes for the pinned local engine and reviewed healthy API, and never
starts Docker or recreates containers. RUNNING is recorded during work; errors
record FAIL/nonzero and preserve the last-success timestamp. Success requires full
verification. Snapshot cleanup follows saved success evidence; a cleanup failure
keeps that successful backup result but returns nonzero and records a persistent
alert. The duplicate guard uses schedule periods beginning at 03:00 in the Windows
local timezone. It skips only when a successful backup completed in the current
period, no later than the current time, and media plus current archive/key recovery
readiness are available. A manual backup before today's 03:00 cannot suppress
today's scheduled run. A successful manual/catch-up run after 03:00 covers that
period; later logons skip until the next 03:00. Each boundary date is converted
separately, so daylight-saving transitions produce the correct 23/25-hour periods.
Task generation/registration require the same local 03:00 daily time.
Missing recovery inputs fail with a
persisted alert and nonzero task exit, including after startup waiting; the saved
success is not restored over that failure. It does not automatically replace a
missing archive or key. This quick check does not hash ciphertext; use explicit
`status --verify-integrity` for that check. The 26-hour status freshness window is
separate from schedule-period duplicate suppression. A missing/locked/wrong disk
never falls back to another location. Windows local-time changes affect the task
and guard together; review clock/timezone changes operationally. The guard does
not start Docker, wake a sleeping PC or supply a logged-out Windows identity.

`last-run.json`, `history.jsonl` and `last-readiness.json` are private diagnostics.
A durable `backup-alert.json` and append-only alert history retain failures across
successful retries. Status distinguishes the saved `last_backup_successful` result
and its 26-hour freshness from current `recovery_media_available` and
`recovery_key_available`. Every status call rechecks the configured disk/volume
identity, marker, private ACLs, a finalized readable archive and the protected
independent key's matching recipient. An unavailable recovery component produces
`RECOVERY_UNAVAILABLE` and a nonzero exit even when the saved success is recent.
Reading an existing backup does not require the free space reserved for new writes.
Status does not rewrite receipts or acknowledge alerts.

Quick status checks availability; `archive_integrity_verified: null` means no hash
check was performed. `status --verify-integrity` streams the complete encrypted
archive through SHA-256 and compares it to the protected success receipt. A mismatch
fails readiness; this check does not replace authenticated decryption/application
verification or prove independent production key custody. Unacknowledged failures
continue to require attention even when recovery is available.
`plaintext_snapshot_cleanup` records `REMOVED`, `FAILED` or crash-interrupted
`PENDING` in local success/history records. The companion external receipt is
flushed before cleanup and therefore records `PENDING`; it attests to the verified
export, not the later local deletion. Status reports `ATTENTION_REQUIRED` and
nonzero for incomplete cleanup even if the archive is healthy or its alert was
acknowledged. A recent scheduled skip likewise stays nonzero, without retrying
deletion of a prior run's snapshot. A subsequent successful export does not dismiss
unacknowledged warnings about earlier retained snapshots.
After investigating retained entries, a new explicit `run` without `--if-due`
can create another verified backup; review its result before acknowledging alerts.
Review the incident and current health before acknowledging its exact ID:

```powershell
python deploy/docker/portable_backup.py acknowledge-alert --config CONFIG.json --alert-id ID_FROM_STATUS
```

A newer incident invalidates an old acknowledgement. Acknowledgement does not make
an unhealthy backup healthy. The local popup is supplementary; choose a reliable
unattended inspection/delivery policy. Registration requires explicit approval,
reviewed task XML/hash, current operator/least privilege, no saved Windows password
and expiry for synthetic trials. Test actual trigger, failure, recovery and restart
ordering. No recurring task is registered by copying/building these artifacts.

## Plaintext snapshot capacity and retention

Application snapshots in the Linux `backups` volume are plaintext, just like the
active financial database. File encryption protects the exported copies; it does
not encrypt Docker's virtual disk. The API/web/Caddy runtime services do not mount
the backup volume. Use the host-encryption policy for local disk protection.

After each portable export, the tool removes only the snapshot just created by
that run. It first authenticates/decrypts and application-verifies the ciphertext,
checks its snapshot/release identity, publishes the final archive, confirms the
ciphertext hash did not change, and flushes the external success receipt and
atomically saves the local success record. Cleanup then rechecks source volume
ownership/release, exact snapshot name, the manifest hash from the verified export,
application verification and a regular-file/directory-only tree. The Linux helper
mounts only the selected backup volume and requires descriptor-safe deletion;
links and unrelated siblings cannot become cleanup targets. No live financial
volume, Windows path or external file is mounted for deletion. This removes files,
not historical plaintext blocks from Docker storage; it does not securely erase
or compact the virtual disk.

An export/verification/publication/receipt failure never requests snapshot cleanup.
A cleanup error preserves the verified archive and success timestamp and raises
an alert; interruption can leave a partially removed snapshot. Such leftovers,
older/manual snapshots and failed exports require explicit investigation and
retention review. There is no automatic retry or cleanup of historical entries.

Before creating another snapshot, Docker maintenance now refuses when the volume
already holds 32 entries, at least 16 GiB of snapshot content, or has less than
8 GiB free. These conservative admission limits count incomplete/unknown entries
too; the admission checks themselves never delete anything. They are capacity guards, not a filesystem quota:
one newly created snapshot can cross the byte threshold, and concurrent writers
must be excluded by the operational policy. A refusal becomes a backup failure
and persistent alert in the portable task. Inspect the mounted Linux volume with
the reviewed image's `operations inventory` command (read-only); its JSON reports
snapshot names, bytes and filesystem free space.
Any link or special file in this volume blocks inventory and further backups
until investigated. The free-space check measures the Linux filesystem, not
the Windows drive backing Docker's virtual disk; monitor both separately.

Retention review is required for preexisting snapshots and accumulated failures:

1. Identify exact snapshot names from inventory and their matching successful
   ciphertext receipts. Preserve failed/incomplete entries for investigation.
2. Recheck media identity, key availability and ciphertext integrity. Perform a
   clean restore using the independently retained recovery key before declaring
   a local snapshot redundant. Keep at least two independently recoverable
   generations, including one matching the current release/schema.
3. Record the selected generations and obtain approval for exact-name removal
   inside the dedicated Linux backup volume. No historical pruning, Docker prune,
   external-drive deletion or VHD compaction is performed by this implementation.
4. Re-run inventory and the backup/recovery checks, retaining their evidence.

The production cadence, generations, capacity alerts and deletion procedure still
need acceptance before real data. Guard refusal is preferable to silent pruning,
but a refused backup requires operator action and is not production readiness.
