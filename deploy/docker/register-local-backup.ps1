param(
    [Parameter(Mandatory)][string]$Config,
    [Parameter(Mandatory)][string]$Python
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$configPath = (Resolve-Path -LiteralPath $Config).Path
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
& $pythonPath (Join-Path $PSScriptRoot 'local_backup.py') status --config $configPath
if ($LASTEXITCODE -ne 0) { throw 'Create and verify the first local backup before registering the task.' }
$taskName = 'FamilyFin-LocalBackup'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw 'Local backup task already exists; inspect it instead of overwriting it.'
}
# Install a self-contained stdlib runner outside Git, so branch switches are safe.
$installDirectory = Join-Path $env:LOCALAPPDATA 'FamilyFin\LocalBackup'
if (Test-Path -LiteralPath $installDirectory) {
    if ((Get-Item -LiteralPath $installDirectory -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Redirected install directory is not supported.' }
} else { New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null }
$runnerFiles = @('local_backup.py','portable_backup.py','portable_stream.py','backup_readiness.py','manage.py','local-backup-task.ps1')
foreach ($name in $runnerFiles) {
    if (Test-Path -LiteralPath (Join-Path $installDirectory $name)) { throw 'Runner already installed; inspect it before updating.' }
}
$sourceDirectory = [IO.Path]::GetDirectoryName($configPath)
$installedConfig = Join-Path $installDirectory 'config.json'
if ($configPath -ne $installedConfig) {
    if (Test-Path -LiteralPath $installedConfig) { throw 'Installed config already exists; refusing overwrite.' }
    Copy-Item -LiteralPath $configPath -Destination $installedConfig
    foreach ($name in @('local-last-run.json','previous-external-task.xml')) {
        $source = Join-Path $sourceDirectory $name
        if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination (Join-Path $installDirectory $name) }
    }
}
foreach ($name in $runnerFiles) {
    $source = Join-Path $PSScriptRoot $name
    $destination = Join-Path $installDirectory $name
    Copy-Item -LiteralPath $source -Destination $destination
    if ((Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $destination).Hash) { throw 'Runner copy verification failed.' }
}
$configPath = $installedConfig
$scriptPath = Join-Path $installDirectory 'local-backup-task.ps1'
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -WindowStyle Hidden -File "' + $scriptPath + '" -Python "' + $pythonPath + '" -Config "' + $configPath + '"') -WorkingDirectory $installDirectory
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
    $previousXml = Join-Path $installDirectory 'previous-external-task.xml'
    if (-not (Test-Path -LiteralPath $previousXml)) { Export-ScheduledTask -TaskName $oldName | Set-Content -LiteralPath $previousXml -Encoding Unicode }
    Disable-ScheduledTask -TaskName $oldName | Out-Null
}
[pscustomobject]@{Task=$taskName;DailyLocalTime='03:00';SignInCatchUp=$true;Keep=7;ExternalDriveRequired=$false;RunnerDirectory=$installDirectory;Config=$configPath} | ConvertTo-Json -Compress
