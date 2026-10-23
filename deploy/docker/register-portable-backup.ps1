param(
    [Parameter(Mandatory)][string]$Config,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedXmlSha256,
    [switch]$Approved,
    [switch]$ValidateOnly
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $Approved -and -not $ValidateOnly) { throw 'Explicit approval to register this recurring synthetic task is required.' }
$env:PSModulePath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\Modules'
$configPath = (Resolve-Path -LiteralPath $Config).Path
& powershell.exe -NoProfile -File (Join-Path $PSScriptRoot 'portable-media.ps1') -Action private-check -Directory ([IO.Path]::GetDirectoryName($configPath))
if ($LASTEXITCODE -ne 0) { throw 'Private configuration directory required.' }
$configuration = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
if (-not $configuration.synthetic -or $configuration.project -ne 'familyfin-m1-synthetic') { throw 'This registration helper supports only the reviewed synthetic trial.' }
$xmlPath = Join-Path ([IO.Path]::GetDirectoryName($configPath)) 'proposed-daily-backup.xml'
$bytes = [IO.File]::ReadAllBytes($xmlPath)
$sha = [Security.Cryptography.SHA256]::Create()
try { $actualHash = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant() } finally { $sha.Dispose() }
if ($actualHash -ne $ExpectedXmlSha256.ToLowerInvariant()) { throw 'The proposed task changed after review.' }
$xmlText = [Text.Encoding]::Unicode.GetString($bytes).TrimStart([char]0xfeff)
$service = New-Object -ComObject Schedule.Service
$service.Connect()
$definition = $service.NewTask(0)
$definition.XmlText = $xmlText
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$principal = $definition.Principal.UserId
if ($principal -match '^S-1-') { $principalSid = $principal } else { $principalSid = ([Security.Principal.NTAccount]$principal).Translate([Security.Principal.SecurityIdentifier]).Value }
if ($principalSid -ne $sid -or $definition.Principal.LogonType -ne 3 -or $definition.Principal.RunLevel -ne 0 -or -not $definition.Settings.StartWhenAvailable -or $definition.Actions.Count -ne 1 -or $definition.Triggers.Count -ne 2) { throw 'Unexpected privilege, trigger or action settings.' }
foreach ($trigger in $definition.Triggers) {
    if (-not $trigger.EndBoundary -or [DateTime]$trigger.EndBoundary -le (Get-Date)) { throw 'A future, explicit trial end boundary is required.' }
}
$taskName = 'FamilyFin-M1-SyntheticBackup'
if (Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction SilentlyContinue) { throw 'Task name already exists; refusing overwrite.' }
if ($ValidateOnly) { [pscustomobject]@{Status='PASS_VALIDATE_ONLY';XmlSha256=$actualHash;Registered=$false} | ConvertTo-Json -Compress; return }
# No Force, password, elevation, logoff execution or global scheduler changes.
$task = Register-ScheduledTask -TaskName $taskName -TaskPath '\' -Xml $xmlText -ErrorAction Stop
$receipt = [ordered]@{TaskName=$taskName;TaskPath='\';XmlSha256=$actualHash;UserSid=$sid;RegisteredAt=(Get-Date).ToUniversalTime().ToString('o');SyntheticOnly=$true;ImmediateRun=$false}
$receipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path ([IO.Path]::GetDirectoryName($configPath)) 'registration.json') -Encoding UTF8
$receipt | ConvertTo-Json -Compress
