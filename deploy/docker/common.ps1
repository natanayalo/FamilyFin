Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:DeployRoot = $PSScriptRoot
function Invoke-FamilyFin {
    param([string[]]$Arguments)
    & python (Join-Path $script:DeployRoot 'manage.py') @Arguments
    if ($LASTEXITCODE -ne 0) { throw "FamilyFin operation failed (exit $LASTEXITCODE)." }
}
