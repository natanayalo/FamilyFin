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

An archive is finalized only after authenticated decryption into a newly owned Linux
staging volume and application manifest/hash/schema/invariant verification. Extraction
rejects traversal, links, special/sparse/duplicate/secret-key entries and size/count
abuse. Incomplete or unauthenticated stages never become restore sources. Failed
stages/partial files and recovery data are retained. Only verified, labelled, unused
verification stages are eligible for exact-name cleanup; no retention pruning occurs.

The selected destination must be a new dedicated private NTFS directory on a separate
physical disk, with matching volume/disk IDs and marker, no redirects, private ACLs
and at least 8 GiB free. There is no local fallback. Existing drive files/settings
remain untouched. The BitLocker-volume wrapper is separate and still fails closed.
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
verification. The 20-hour duplicate guard also checks media; manual backups can
cause a subsequent daily trigger to skip, so calendar frequency remains a production
policy issue. A missing/locked/wrong disk never falls back to another location.

`last-run.json`, `history.jsonl` and `last-readiness.json` are private diagnostics.
A durable `backup-alert.json` and append-only alert history retain failures across
successful retries. Status distinguishes backup health from unresolved attention.
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
