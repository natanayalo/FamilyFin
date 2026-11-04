# Simple local backups on Windows

Use this for a small personal FamilyFin deployment when an external drive is not
always connected. It creates one verified full archive daily at 03:00 local time,
with sign-in catch-up, and retains the newest seven owned, intact copies. A recent
manual backup covers the same 03:00-to-03:00 day. Missing/tampered files cause a new
backup instead of a false successful skip.

Backups contain the database (including users and audit history) and managed
imported files. They exclude the signing key, so recovery requires signing in
again. Archives are ordinary **unencrypted tar files** in a private local folder.
They protect against accidental changes and failed updates; copies on the same
disk do not protect against disk failure. Optionally copy archives and their
receipts to an external drive when it is connected.

## Set up

Use Python 3.12 and the local Docker Desktop Linux engine. The existing API image
is used by short-lived, network-disabled maintenance containers; the running app
is not rebuilt or restarted. Docker Desktop and a signed-in Windows session are
required. The task does not wake the PC or promise availability before sign-in.

Choose a dedicated folder outside the repository, for example
`$env:USERPROFILE\FamilyFinBackups`. Create it with user-only access (plus SYSTEM
and Administrators) before initializing. Do not reuse a folder holding other files.

```powershell
$python = (Get-Command python).Source
$config = Join-Path $PWD 'deploy/docker/.state/local-backup/config.json'
python deploy/docker/local_backup.py init --config $config --directory "$env:USERPROFILE\FamilyFinBackups"
python deploy/docker/local_backup.py run --config $config
python deploy/docker/local_backup.py status --config $config
./deploy/docker/register-local-backup.ps1 -Config $config -Python $python
```

Registration requires a successful first backup. It installs the non-admin,
password-free `FamilyFin-LocalBackup` task, saves the old external task's XML,
and disables that task. It never deletes the old task, external backups or keys.
Task Scheduler records a nonzero result on failure; private details are in
`local-last-run.json` beside the configuration. Check these after a failed run.

## Verify and recover

Select one archive from the configured folder:

```powershell
python deploy/docker/local_backup.py verify --config $config --archive $archive
python deploy/docker/local_backup.py restore-check --config $config --archive $archive
```

Verification extracts only into an owned disposable Linux volume and checks the
application manifest, hashes, schema and database invariants. Restore-check also
restores into a fresh data volume, runs the application audit, then removes its
test volumes. It never writes to the live financial volume.

For an actual recovery, use `restore` in place of `restore-check`. It returns a
new `familyfin-local-recovery-...` volume and retains it for review; it does not
change the running app or its routing. A failed actual restore also retains its
new volume for diagnosis. Use the recorded matching API image for recovery.
After a deliberate app image update, review/update the pinned backup image in
the private config; a changed source release otherwise fails closed.

Retention runs only after a fresh archive has been exported and independently
verified. Only top-level archives with matching ownership receipts and hashes are
eligible for deletion. Unknown, partial or modified files are preserved. Temporary
maintenance volumes are removed after each operation. Historical application
snapshots and old external-drive backups are not pruned by this feature.
