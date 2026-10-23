# Synthetic acceptance workflows

These workflows test this POC's documented topology. They are not a production
installer and cannot adopt arbitrary household data. Keeping their code in Git
allows tests and review; private results, receipts and keys remain ignored.

Fresh localhost deployment and candidate validation generate their own disposable
fixtures and receipts. Mobile/restart/scheduler acceptance then consume explicitly
prepared host evidence. Missing private files mean prerequisites are incomplete;
never copy another host's receipt or manufacture a PASS to proceed.

| Workflow | Required input / prerequisite |
| --- | --- |
| `validate.py` | Fresh financial volumes; generates the two-user synthetic fixture and state comparison |
| `validate_candidate.py --tag candidate-NAME --run-id NAME` | Exact image scans, unused ports and fresh volumes |
| `mobile.py prepare --report-name NAME --image-tag TAG` | Prior fixture/evidence, reviewed images plus `tested-configs.json` in the selected report; prepares localhost only |
| `portable_setup.py` | Explicit new state/media folders and reviewed tools; mobile receipt must already exist |
| `host_recovery.py prepare --config CONFIG.json` | Explicit protected synthetic backup config; never reboots Windows |
| `validate_scheduled_backup.py --config CONFIG.json` | Explicit config and previously approved, registered bounded synthetic task |
| `validate_backup_alerts.py --config CONFIG.json` | Explicit config and synthetic fixture; creates only its own validation state |
| `rollout_reviewed.py --evidence-directory PATH` | Explicit exact-image drill evidence; synthetic rollout authorization is separate |

Default mobile names are stable neutral names, not dated session identifiers;
an operator may explicitly select a retained report/tag. Backup-config paths are
required arguments instead of references to one historical host directory.
Use the same report/tag arguments for subsequent mobile CLI actions. Reviewed
image configuration identities come from that selected report, not a numbered
historical security-review directory.

The fixture intentionally has `qa-one`/`qa-two` and fixed synthetic counts. The
mobile migration guard requires the documented M0 loopback route on 8088 and the
known POC listener set (8080/8088/8090/8091). These are admission assertions for
this test topology, not a claim that every Windows PC has those services. A new
topology needs a separately reviewed profile/baseline; never relax the checks to
adopt unknown services or data. Existing frozen operational checkouts/receipts are
not rewritten when this source changes.

All workflows reject `python -O` / optimized `PYTHONOPTIMIZE` at import. Mutating
acceptance (task registration, restart testing, image promotion or Serve cutover)
still needs its specific authorization. No acceptance workflow is started by a
container build or by importing configuration.
