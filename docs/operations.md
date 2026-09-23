# Local operations

The application stores its SQLite database, immutable import archives, and
rotating JSON-lines event log under `data/local/` (or the directory selected by
`FAMILY_FINANCE_DATA_ROOT`). Event logs contain only event names, timestamps,
durations, aggregate counts, and issue/error codes.

## Local automation

Place manually exported FamilyBiz `.xlsx` files in
`data/local/automation/inbox/` and review a pass with:

    family-finance automate --dry-run
    family-finance automate

Set `FAMILY_FINANCE_AUTOMATION_BACKUP_ROOT` to require a verified backup before
the first commit in a run. Safe files move to `automation/processed/YYYY-MM/`;
invalid, unstable, or ambiguous files move to `automation/needs-review/YYYY-MM/`.
The runner never resolves reconciliation or classification questions.

## Audit and backup

Run the read-only audit before making a backup:

    family-finance audit
    family-finance backup /safe/location/family-finance-backup-2026-09-21
    family-finance verify-backup /safe/location/family-finance-backup-2026-09-21

`backup` uses SQLite's online backup API, copies the content-addressed import
and planning archives, writes a manifest, verifies the temporary sibling, and renames it
into place only after verification. It never overwrites an existing backup.

## Manual restore

There is intentionally no destructive automatic restore command.

1. Stop Streamlit and any other process using the local data directory.
2. Run `family-finance verify-backup BACKUP_DIRECTORY` and require a passing
   result.
3. Preserve the current data directory by renaming it to a timestamped
   recovery directory outside the active path. Do not delete it.
4. Restore the backup's `family_finance.sqlite3`, `imports/`,
   `planning-imports/`, and `net-worth-imports/` directories as a matched set
   into a new `data/local/`
   directory. Keep the backup manifest alongside the restored files for evidence.
5. Set `FAMILY_FINANCE_DATA_ROOT` to the restored directory, run
   `family-finance audit`, and start Streamlit again on localhost.

If the audit or application startup fails, stop and return to the preserved
directory; the original data is still available for investigation.
