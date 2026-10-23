param(
    [Parameter(Mandatory)][string]$BackupDirectory,
    [Parameter(Mandatory)][string]$ExpectedVolumeId,
    [ValidatePattern('^familyfin-m1(-[a-z0-9-]+)?$')][string]$Project = 'familyfin-m1',
    [Parameter(Mandatory)][ValidatePattern('^[a-zA-Z0-9_.-]+$')][string]$ReleaseTag,
    [switch]$Approved
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $Approved) { throw 'Production media use requires explicit approval; see windows-deployment.md.' }
& python -c "import sys; sys.path.insert(0,sys.argv[1]); from manage import engine,assert_owned; engine(); assert_owned(sys.argv[2])" $PSScriptRoot $Project
if ($LASTEXITCODE -ne 0) { throw 'Local Docker engine / project ownership verification failed.' }
$target = (Resolve-Path -LiteralPath $BackupDirectory).Path
if ($target -notmatch '^[A-Za-z]:\\' -or $target.StartsWith($env:SystemDrive, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Use an existing directory on a separate local backup drive.'
}
$drive = $target.Substring(0,1)
$directoryInfo = Get-Item -LiteralPath $target -Force
if (-not $directoryInfo.PSIsContainer) { throw 'Backup destination must be an existing directory.' }
while ($null -ne $directoryInfo) {
    if (($directoryInfo.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'Reparse points are forbidden in the backup path.'
    }
    $directoryInfo = $directoryInfo.Parent
}
$volume = Get-Volume -DriveLetter $drive
if ($volume.UniqueId -ne $ExpectedVolumeId) { throw 'Backup media identity does not match.' }
$partition = Get-Partition -DriveLetter $drive
$systemPartition = Get-Partition -DriveLetter $env:SystemDrive.Substring(0,1)
if ($partition.DiskNumber -eq $systemPartition.DiskNumber) { throw 'Backup media must be on a separate physical disk.' }
$disk = Get-Disk -Number $partition.DiskNumber
if ([string]$disk.BusType -match 'Virtual|Spaces') { throw 'Cannot attest independent physical media for a virtual disk.' }
# If this Windows edition cannot attest encryption, fail closed.
$encryption = Get-BitLockerVolume -MountPoint ($drive + ':')
if ($encryption.VolumeStatus -ne 'FullyEncrypted' -or $encryption.LockStatus -ne 'Unlocked' -or $encryption.ProtectionStatus -ne 'On') {
    throw 'Verified active BitLocker protection and unlocked encrypted media required.'
}
$acl = Get-Acl -LiteralPath $target
if (-not $acl.AreAccessRulesProtected) { throw 'Backup directory must have protected, reviewed ACLs.' }
$userSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$trusted = @($userSid, 'S-1-5-18', 'S-1-5-32-544')
foreach ($rule in $acl.Access) {
    if ($rule.AccessControlType -eq 'Allow') {
        $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
        if ($trusted -notcontains $sid) { throw 'Backup ACL grants access outside the operator/SYSTEM/Administrators.' }
    }
}
$owner = ([Security.Principal.NTAccount]$acl.Owner).Translate([Security.Principal.SecurityIdentifier]).Value
if ($trusted -notcontains $owner) { throw 'Backup owner is outside the trusted operator principals.' }
& docker volume inspect ($Project + '_financial') --format '{{index .Labels "com.docker.compose.project"}}' | ForEach-Object {
    if ($_ -ne $Project) { throw 'Financial volume ownership mismatch.' }
}
if ($LASTEXITCODE -ne 0) { throw 'Existing financial volume required; refusing to create a fresh empty one.' }
$oldBackup = $env:FAMILYFIN_ENCRYPTED_BACKUP_DIR
$oldRelease = $env:FAMILYFIN_IMAGE_TAG
try {
    $env:FAMILYFIN_ENCRYPTED_BACKUP_DIR = $target
    $env:FAMILYFIN_IMAGE_TAG = $ReleaseTag
    & docker compose --project-name $Project --project-directory $PSScriptRoot --file (Join-Path $PSScriptRoot 'compose.yaml') --file (Join-Path $PSScriptRoot 'compose.encrypted-backup.yaml') run --rm --no-deps operations operations backup
    if ($LASTEXITCODE -ne 0) { throw 'Verified backup failed.' }
} finally {
    $env:FAMILYFIN_ENCRYPTED_BACKUP_DIR = $oldBackup
    $env:FAMILYFIN_IMAGE_TAG = $oldRelease
}
