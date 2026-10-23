param(
    [ValidateSet('inspect','create','check','private-create','private-check','identity-check')][string]$Action,
    [Parameter(Mandatory)][string]$Directory,
    [string]$ExpectedVolumeId,
    [string]$ExpectedDiskId,
    [string]$Token
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# Windows PowerShell launched by PowerShell 7 must use its own system modules.
$env:PSModulePath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\Modules'
$path = [IO.Path]::GetFullPath($Directory)
if ($path -notmatch '^[A-Za-z]:\\' -or $path.TrimEnd('\').Length -le 3) { throw 'A local subdirectory is required.' }
$userSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$trusted = @($userSid.Value,'S-1-5-18','S-1-5-32-544')
function Assert-NoRedirect([string]$candidate) {
    $item = Get-Item -LiteralPath $candidate -Force
    while ($null -ne $item) {
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Redirected paths forbidden.' }
        if ($item -is [IO.DirectoryInfo]) { $item = $item.Parent } else { $item = $item.Directory }
    }
}
function Assert-Private([string]$candidate) {
    Assert-NoRedirect $candidate
    $acl = [IO.Directory]::GetAccessControl($candidate)
    if (-not $acl.AreAccessRulesProtected) { throw 'Protected directory ACL required.' }
    $observed = @($acl.Access | Where-Object {$_.AccessControlType -eq 'Allow'} | ForEach-Object {$_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value}) | Sort-Object -Unique
    if (@(Compare-Object ($trusted | Sort-Object) $observed).Count) { throw 'Unexpected directory access principals.' }
    $owner = ([Security.Principal.NTAccount]$acl.Owner).Translate([Security.Principal.SecurityIdentifier]).Value
    if ($trusted -notcontains $owner) { throw 'Unexpected owner.' }
}
function New-Private([string]$candidate) {
    if (Test-Path -LiteralPath $candidate) { throw 'Refusing to change an existing directory.' }
    Assert-NoRedirect ([IO.Path]::GetDirectoryName($candidate))
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true,$false)
    $acl.SetOwner($userSid)
    foreach ($sid in $trusted) {
        $principal = New-Object Security.Principal.SecurityIdentifier($sid)
        $rule = New-Object Security.AccessControl.FileSystemAccessRule($principal,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
        $acl.AddAccessRule($rule)
    }
    [IO.Directory]::CreateDirectory($candidate,$acl) | Out-Null
    Assert-Private $candidate
}
if ($Action -eq 'private-create') { New-Private $path; return }
if ($Action -eq 'private-check') { Assert-Private $path; return }
if ($Action -eq 'identity-check') {
    Assert-NoRedirect $path
    Assert-Private ([IO.Path]::GetDirectoryName($path))
    $acl = [IO.File]::GetAccessControl($path)
    foreach ($rule in $acl.Access) {
        if ($rule.AccessControlType -eq 'Allow' -and $trusted -notcontains $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value) { throw 'Recovery identity file grants untrusted access.' }
    }
    $partition = Get-Partition -DriveLetter $path.Substring(0,1)
    $keyDisk = Get-Disk -Number $partition.DiskNumber
    if (-not $ExpectedDiskId -or [string]$keyDisk.UniqueId -eq $ExpectedDiskId) { throw 'Recovery key must remain on a different physical disk from backup archives.' }
    return
}
$drive = $path.Substring(0,1)
$volume = Get-Volume -DriveLetter $drive
$partition = Get-Partition -DriveLetter $drive
$systemPartition = Get-Partition -DriveLetter $env:SystemDrive.Substring(0,1)
$disk = Get-Disk -Number $partition.DiskNumber
if ($partition.DiskNumber -eq $systemPartition.DiskNumber -or $volume.FileSystem -ne 'NTFS' -or [string]$disk.BusType -match 'Virtual|Spaces' -or $disk.IsOffline -or $disk.IsReadOnly) { throw 'Independent available NTFS physical media required.' }
$identity = [pscustomobject]@{VolumeId=[string]$volume.UniqueId;DiskId=[string]$disk.UniqueId;DiskNumber=$partition.DiskNumber;BusType=[string]$disk.BusType;Directory=$path;FreeBytes=$volume.SizeRemaining}
if ($Action -eq 'inspect') { $identity | ConvertTo-Json -Compress; return }
if (-not $ExpectedVolumeId -or -not $ExpectedDiskId -or $volume.UniqueId -ne $ExpectedVolumeId -or $disk.UniqueId -ne $ExpectedDiskId) { throw 'Backup media identity mismatch.' }
if ($Token -notmatch '^[0-9a-f]{32}$') { throw 'Media marker identity required.' }
if ($Action -eq 'create') {
    New-Private $path
    $bytes = [Text.Encoding]::UTF8.GetBytes(($identity | Select-Object VolumeId,DiskId,@{Name='Token';Expression={$Token}} | ConvertTo-Json -Compress))
    $stream = [IO.File]::Open((Join-Path $path '.familyfin-portable-media.json'),'CreateNew','Write','None')
    try { $stream.Write($bytes,0,$bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
}
Assert-Private $path
$marker = Get-Content -LiteralPath (Join-Path $path '.familyfin-portable-media.json') -Raw | ConvertFrom-Json
if ($marker.VolumeId -ne $ExpectedVolumeId -or $marker.DiskId -ne $ExpectedDiskId -or $marker.Token -ne $Token) { throw 'Backup marker mismatch.' }
$identity | ConvertTo-Json -Compress
