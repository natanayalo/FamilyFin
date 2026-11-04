param([Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$Config)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
try {
    & $Python (Join-Path $PSScriptRoot 'local_backup.py') run --config $Config --if-due --wait-ready
    exit $LASTEXITCODE
} catch {
    Write-Error 'FamilyFin local backup failed. Inspect local-last-run.json and Task Scheduler.'
    exit 1
}
