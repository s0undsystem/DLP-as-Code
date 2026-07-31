#Requires -Version 5.1
<#
.SYNOPSIS
    Export the live DLP configuration to exports/ as JSON (READ-ONLY).

    Runs under Windows PowerShell 5.1. Requires cert prep by Connect-Dlp.ps1 in the same process.
    Writes exports/dlp-policies.json and exports/dlp-rules.json - the native, faithful config used
    by recon, drift detection, and the importer.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$exportDir = [System.IO.Path]::GetFullPath((Join-Path (Join-Path $PSScriptRoot '..') 'exports'))
New-Item -ItemType Directory -Path $exportDir -Force | Out-Null

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

$policies = @(Get-DlpCompliancePolicy)
$rules = @(Get-DlpComplianceRule)
$policies | ConvertTo-Json -Depth 25 | Set-Content -Path (Join-Path $exportDir 'dlp-policies.json') -Encoding UTF8
$rules | ConvertTo-Json -Depth 25 | Set-Content -Path (Join-Path $exportDir 'dlp-rules.json') -Encoding UTF8
Write-Host "Exported $($policies.Count) policy(ies) and $($rules.Count) rule(s) to $exportDir."
