param([ValidateSet('familyfin-m1-synthetic','familyfin-m1-restore')][string]$Project = 'familyfin-m1-synthetic')
. (Join-Path $PSScriptRoot 'common.ps1')
Invoke-FamilyFin -Arguments @('verify','--project',$Project)
