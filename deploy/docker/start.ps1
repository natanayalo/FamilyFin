param([ValidateSet('familyfin-m1-synthetic','familyfin-m1-restore')][string]$Project = 'familyfin-m1-synthetic', [switch]$Build)
. (Join-Path $PSScriptRoot 'common.ps1')
$arguments = @('start','--project',$Project)
if ($Build) { $arguments += '--build' }
Invoke-FamilyFin -Arguments $arguments
