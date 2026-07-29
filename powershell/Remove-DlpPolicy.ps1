#Requires -Version 5.1
<#
.SYNOPSIS
    Remove a single named DLP compliance policy (and its rules) from the tenant.

    Runs under Windows PowerShell 5.1. Requires cert prep by Connect-Dlp.ps1 in the same
    process. Target policy name comes from $env:DLP_POLICY_TO_REMOVE.

.NOTES
    Safety: refuses an empty name or any wildcard (* / ?), so it can only ever remove one
    explicitly-named policy. Removing a policy also removes its associated rules.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$target = $env:DLP_POLICY_TO_REMOVE
if ([string]::IsNullOrWhiteSpace($target) -or $target -match '[\*\?]') {
    throw "Refusing to run: DLP_POLICY_TO_REMOVE must be a single explicit policy name (got '$target')."
}
foreach ($n in 'AZURE_CLIENT_ID', 'M365_ORGANIZATION', 'DLP_CERT_THUMBPRINT') {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($n))) {
        throw "Required environment variable '$n' is not set (did Connect-Dlp.ps1 run in this process?)."
    }
}

if (-not (Get-Module -ListAvailable -Name ExchangeOnlineManagement)) {
    Install-Module ExchangeOnlineManagement -Force -Scope CurrentUser -AllowClobber
}
Import-Module ExchangeOnlineManagement
Connect-IPPSSession -AppId $env:AZURE_CLIENT_ID -CertificateThumbprint $env:DLP_CERT_THUMBPRINT `
    -Organization $env:M365_ORGANIZATION -ShowBanner:$false
Write-Host "Connected app-only to Security & Compliance for '$env:M365_ORGANIZATION'."

$p = Get-DlpCompliancePolicy -Identity $target -ErrorAction SilentlyContinue
if ($null -eq $p) {
    Write-Host "Policy '$target' not found (already removed). Nothing to do."
    exit 0
}
Write-Host "Removing policy '$target' (current Mode=$($p.Mode))..."
Remove-DlpCompliancePolicy -Identity $target -Confirm:$false -ErrorAction Stop
Start-Sleep -Seconds 3
$after = Get-DlpCompliancePolicy -Identity $target -ErrorAction SilentlyContinue
if ($null -eq $after) {
    Write-Host "Removed: '$target' is gone."
}
else {
    Write-Host "Remove issued: '$target' is now '$($after.Mode)' (Purview removal is async / PendingDeletion)."
}
