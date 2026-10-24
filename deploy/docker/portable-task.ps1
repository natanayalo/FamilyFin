param([Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$Config)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
try {
    # Bounded read-only startup wait; never starts Docker or replaces containers.
    & $Python (Join-Path $PSScriptRoot 'portable_backup.py') run --config $Config --if-due --wait-ready
    $result = $LASTEXITCODE
} catch { $result = 1 }
if ($result -ne 0) {
    # Local operator notification only; no email/webhook or external transmission.
    # Task Scheduler also receives the nonzero exit code; private JSON retains status.
    try {
        $notice = New-Object -ComObject WScript.Shell
        $response = $notice.Popup('FamilyFin backup needs attention. Check backup status for recovery or cleanup warnings.',15,'FamilyFin backup',48)
        $alert = [ordered]@{Status='POPUP_RETURNED';Response=$response;At=(Get-Date).ToUniversalTime().ToString('o')}
    } catch { $alert = [ordered]@{Status='POPUP_FAILED';At=(Get-Date).ToUniversalTime().ToString('o')} }
    try { $alert | ConvertTo-Json | Set-Content -LiteralPath (Join-Path ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($Config))) 'last-alert.json') -Encoding UTF8 } catch { }
}
exit $result
