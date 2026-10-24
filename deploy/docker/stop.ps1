param([ValidateSet('familyfin-m1-synthetic','familyfin-m1-restore')][string]$Project = 'familyfin-m1-synthetic')
. (Join-Path $PSScriptRoot 'common.ps1')
# Removes only this project's containers/network; preserves all volumes.
Invoke-FamilyFin -Arguments @('stop','--project',$Project)
