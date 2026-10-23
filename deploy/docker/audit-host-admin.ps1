#Requires -RunAsAdministrator
# Read-only audit. Never retrieves recovery keys, changes encryption or reboots.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$receipt = [ordered]@{
    checked_at = (Get-Date).ToUniversalTime().ToString('o')
    scope = 'Read-only system-drive encryption, Secure Boot and TPM readiness'
}
try {
    $drive = Get-BitLockerVolume -MountPoint $env:SystemDrive -ErrorAction Stop
    $receipt.system_drive = [ordered]@{
        mount_point = $drive.MountPoint
        volume_status = [string]$drive.VolumeStatus
        protection_status = [string]$drive.ProtectionStatus
        lock_status = [string]$drive.LockStatus
        encryption_percentage = $drive.EncryptionPercentage
        encryption_method = [string]$drive.EncryptionMethod
        status = 'FAIL'
    }
    if ($drive.VolumeStatus -eq 'FullyEncrypted' -and $drive.ProtectionStatus -eq 'On' -and $drive.EncryptionPercentage -eq 100) {
        $receipt.system_drive.status = 'PASS'
    }
} catch {
    $receipt.system_drive = @{status='UNVERIFIED'; reason=$_.Exception.Message}
}
try {
    $receipt.secure_boot = @{enabled=[bool](Confirm-SecureBootUEFI -ErrorAction Stop)}
} catch {
    $receipt.secure_boot = @{status='UNVERIFIED'; reason=$_.Exception.Message}
}
try {
    $tpm = Get-Tpm -ErrorAction Stop
    $receipt.tpm = @{present=$tpm.TpmPresent; ready=$tpm.TpmReady; enabled=$tpm.TpmEnabled}
} catch {
    $receipt.tpm = @{status='UNVERIFIED'; reason=$_.Exception.Message}
}
$receipt.limits = @('No recovery-key escrow or recovery drill attested', 'No complete firmware/Windows/WSL vulnerability certification', 'No host settings changed')
$target = Join-Path $PSScriptRoot ('reports/host-admin-audit-' + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssfffZ') + '.json')
if (Test-Path -LiteralPath $target) { throw 'Refusing to overwrite audit evidence.' }
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $target -Encoding utf8
$receipt | ConvertTo-Json -Depth 6
if ($receipt.system_drive.status -ne 'PASS') { exit 1 }
