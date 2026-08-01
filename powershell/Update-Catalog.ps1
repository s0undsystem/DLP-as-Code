#Requires -Version 5.1
# Copyright 2026 Jared Medeiros
# SPDX-License-Identifier: Apache-2.0
# Part of DLPaC (https://github.com/s0undsystem/DLP-as-Code). See NOTICE.

<#
.SYNOPSIS
    Refresh catalog/catalog.json with all resolvable reference data (READ-ONLY).

    Runs under Windows PowerShell 5.1. Requires cert prep by Connect-Dlp.ps1 in the same process.

.DESCRIPTION
    Pulls, each guarded independently so one permission gap doesn't sink the rest:
      - sensitiveInfoTypes   (Get-DlpSensitiveInformationType)  + customSensitiveInfoTypes
      - sensitivityLabels    (Get-Label)
      - keywordDictionaries  (Get-DlpKeywordDictionary)
      - trainableClassifiers (Get-DlpTrainableClassifier, if available)
    Groups and sites are PRESERVED from the existing catalog (curated / Graph-sourced). Reports
    which pulls succeeded or were unavailable so permission gaps are visible.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$catalogPath = [System.IO.Path]::GetFullPath((Join-Path (Join-Path $PSScriptRoot '..') 'catalog/catalog.json'))

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
Write-Host "Connected app-only to Security & Compliance for '$env:M365_ORGANIZATION'.`n"

$notes = New-Object System.Collections.Generic.List[string]

# --- Sensitive info types ---
$sits = [ordered]@{}
$custom = New-Object System.Collections.Generic.List[string]
try {
    foreach ($t in (Get-DlpSensitiveInformationType | Sort-Object Name)) {
        $sits["$($t.Name)"] = "$($t.Id)"
        if ("$($t.Publisher)" -notmatch 'Microsoft') { $custom.Add("$($t.Name)") }
    }
    Write-Host "sensitiveInfoTypes: $($sits.Count) ($($custom.Count) custom)"
}
catch { $notes.Add("sensitiveInfoTypes unavailable: $($_.Exception.Message)") }

# --- Sensitivity labels ---
$labels = [ordered]@{}
try {
    foreach ($l in (Get-Label | Sort-Object DisplayName)) {
        $key = if ("$($l.DisplayName)") { "$($l.DisplayName)" } else { "$($l.Name)" }
        $labels[$key] = "$($l.Guid)"
    }
    Write-Host "sensitivityLabels: $($labels.Count)"
}
catch { $notes.Add("sensitivityLabels unavailable: $($_.Exception.Message)") }

# --- Keyword dictionaries ---
$dicts = [ordered]@{}
try {
    foreach ($d in (Get-DlpKeywordDictionary | Sort-Object Name)) {
        $dicts["$($d.Name)"] = "$($d.Identity)"
    }
    Write-Host "keywordDictionaries: $($dicts.Count)"
}
catch { $notes.Add("keywordDictionaries unavailable: $($_.Exception.Message)") }

# --- Trainable classifiers (cmdlet may not exist in all tenants) ---
$classifiers = [ordered]@{}
try {
    foreach ($c in (Get-DlpTrainableClassifier | Sort-Object Name)) {
        $classifiers["$($c.Name)"] = "$($c.Identity)"
    }
    Write-Host "trainableClassifiers: $($classifiers.Count)"
}
catch { $notes.Add("trainableClassifiers unavailable: $($_.Exception.Message)") }

# --- Preserve curated groups / sites ---
$existing = $null
if (Test-Path $catalogPath) { $existing = Get-Content -Path $catalogPath -Raw | ConvertFrom-Json }
function Copy-Map($obj, $name) {
    $m = [ordered]@{}
    if ($null -ne $obj -and $obj.PSObject.Properties.Name -contains $name -and $null -ne $obj.$name) {
        foreach ($p in $obj.$name.PSObject.Properties) { $m[$p.Name] = $p.Value }
    }
    return $m
}
$groups = Copy-Map $existing 'groups'
$sites = Copy-Map $existing 'sites'
Write-Host "groups (preserved): $($groups.Count) | sites (preserved): $($sites.Count)"

$catalog = [ordered]@{
    '_comment'               = 'name<->id reference catalog for the DLP compiler. SITs/labels/keyword dictionaries/classifiers refreshed by Update-Catalog.ps1; groups (name->GUID) and sites (name->URL) are curated. customSensitiveInfoTypes are org-custom.'
    sensitiveInfoTypes       = $sits
    sensitivityLabels        = $labels
    keywordDictionaries      = $dicts
    trainableClassifiers     = $classifiers
    groups                   = $groups
    sites                    = $sites
    customSensitiveInfoTypes = @($custom | Sort-Object -Unique)
}
$catalog | ConvertTo-Json -Depth 6 | Set-Content -Path $catalogPath -Encoding UTF8
Write-Host "`nWrote $catalogPath."

if ($notes.Count -gt 0) {
    Write-Host "`n=== NOTES (pulls that need attention) ==="
    foreach ($n in $notes) { Write-Host "  - $n" }
}
