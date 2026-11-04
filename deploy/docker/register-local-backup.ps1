param(
    [Parameter(Mandatory)][string]$Config,
    [Parameter(Mandatory)][string]$Python
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$configPath = (Resolve-Path -LiteralPath $Config).Path
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$scriptPath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'local-backup-task.ps1')).Path
& $pythonPath (Join-Path $PSScriptRoot 'local_backup.py') status --config $configPath
if ($LASTEXITCODE -ne 0) { throw 'Create and verify the first local backup before registering the task.' }
$taskName = 'FamilyFin-LocalBackup'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw 'Local backup task already exists; inspect it instead of overwriting it.'
}
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -WindowStyle Hidden -File "' + $scriptPath + '" -Python "' + $pythonPath + '" -Config "' + $configPath + '"') -WorkingDirectory $PSScriptRoot
$daily = New-ScheduledTaskTrigger -Daily -At '03:00'
# An offset-free boundary follows Windows local wall time across DST changes.
$daily.StartBoundary = (Get-Date).Date.AddHours(3).ToString("yyyy-MM-dd'T'HH:mm:ss")
$logon = New-ScheduledTaskTrigger -AtLogOn -User $principal.UserId
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($daily,$logon) -Settings $settings -Principal $principal -Description 'Verified daily local FamilyFin backup; keep seven copies. Requires user sign-in and Docker Desktop.' | Out-Null
# Keep the old definition and history, but avoid two backup writers.
$oldName = 'FamilyFin-M1-SyntheticBackup'
$oldTask = Get-ScheduledTask -TaskName $oldName -ErrorAction SilentlyContinue
if ($oldTask) {
    Export-ScheduledTask -TaskName $oldName | Set-Content -LiteralPath (Join-Path ([IO.Path]::GetDirectoryName($configPath)) 'previous-external-task.xml') -Encoding Unicode
    Disable-ScheduledTask -TaskName $oldName | Out-Null
}
[pscustomobject]@{Task=$taskName;DailyLocalTime='03:00';SignInCatchUp=$true;Keep=7;ExternalDriveRequired=$false} | ConvertTo-Json -Compress
