#Requires -Version 5.1
# Copyright 2026 Jared Medeiros
# SPDX-License-Identifier: Apache-2.0
# Part of DLPaC (https://github.com/s0undsystem/DLP-as-Code). See NOTICE.

<#
.SYNOPSIS
    Plan: diff the compiled manifest against the live tenant (READ-ONLY).

    Runs under Windows PowerShell 5.1. Requires cert prep by Connect-Dlp.ps1 in the same
    process. Reads build/manifest.json (from compile.py). Makes no changes.

.DESCRIPTION
    For each policy/rule in the manifest, reports what a deploy would actually do. AdvancedRule
    comparison is structural (JSON parsed and canonicalized) so cosmetic whitespace differences
    don't show as drift. Exit code is 0 regardless of diff (planning is informational); the
    change count is printed at the end.

    PLAN MUST MIRROR DEPLOY. The value of a plan is that it predicts the deploy, so this script
    models the same rule reconciliation Invoke-Deploy.ps1 performs:

      - A rule whose AdvancedRule differs is reported as RENAME REQUIRED, not UPDATE. Purview
        rejects Set-DlpComplianceRule -AdvancedRule, so deploy deliberately leaves such a rule
        untouched. Reporting it as an update would promise a reconciliation that never happens.
      - Live rules absent from the manifest are reported as REMOVE, matching deploy's prune.
        Rules are fetched per policy with -Policy (as deploy does) rather than individually by
        -Identity, which is what makes those orphans visible at all.
      - Pruning is suppressed by deploy unless every desired rule is in place, so when a rule is
        missing or in PendingDeletion the removals are reported as deferred.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$manifestPath = [System.IO.Path]::GetFullPath((Join-Path (Join-Path $PSScriptRoot '..') 'build/manifest.json'))
if (-not (Test-Path $manifestPath)) {
    throw "Manifest not found at $manifestPath. Run 'python compiler/compile.py' first."
}
$manifest = Get-Content -Path $manifestPath -Raw | ConvertFrom-Json

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

function Test-HasProperty {
    param($Object, [string] $Name)
    if ($null -eq $Object) { return $false }
    return ($Object.PSObject.Properties.Name -contains $Name)
}

function Get-Canonical {
    param([string] $Json)
    if ([string]::IsNullOrWhiteSpace($Json)) { return '' }
    try {
        return ($Json | ConvertFrom-Json | ConvertTo-Json -Depth 40 -Compress)
    }
    catch {
        return ($Json -replace '\s', '')
    }
}

$changes = 0
Write-Host "=== PLAN (intended manifest vs live tenant) ==="
foreach ($pol in $manifest.policies) {
    $name = $pol.name
    $live = Get-DlpCompliancePolicy -Identity $name -ErrorAction SilentlyContinue
    if ($null -eq $live) {
        Write-Host "  + CREATE policy '$name' (Mode=$($pol.mode))"
        $changes++
    }
    else {
        if ("$($live.Mode)" -ne "$($pol.mode)") {
            Write-Host "  ~ UPDATE policy '$name' Mode: $($live.Mode) -> $($pol.mode)"
            $changes++
        }
        else {
            Write-Host "  = policy '$name' in sync (Mode=$($pol.mode))"
        }
    }

    # Fetch once per policy, exactly as the deploy engine does. Fetching individually by
    # -Identity would never surface rules the manifest no longer declares.
    $liveRules = @(Get-DlpComplianceRule -Policy $name -ErrorAction SilentlyContinue)
    $liveByName = @{}   # PowerShell hashtables are case-insensitive, matching Purview
    foreach ($lr in $liveRules) {
        if ($null -ne $lr) { $liveByName[[string]$lr.Name] = $lr }
    }
    $desiredNames = @{}
    foreach ($r in $pol.rules) { $desiredNames[[string]$r.name] = $true }

    $allRulesInPlace = $true
    foreach ($rule in $pol.rules) {
        $rname = [string]$rule.name
        if (-not $liveByName.ContainsKey($rname)) {
            Write-Host "      + CREATE rule '$rname'"
            $changes++
            $allRulesInPlace = $false
            continue
        }
        $liveRule = $liveByName[$rname]
        if ((Test-HasProperty $liveRule 'Mode') -and "$($liveRule.Mode)" -eq 'PendingDeletion') {
            Write-Host "      ! rule '$rname' is in PendingDeletion; deploy will skip it until the tenant finishes removing it"
            $allRulesInPlace = $false
            continue
        }
        if ((Get-Canonical $liveRule.AdvancedRule) -ne (Get-Canonical $rule.advancedRule)) {
            # Deliberately NOT reported as an update: Set-DlpComplianceRule -AdvancedRule is
            # rejected by the service, so deploy leaves this rule exactly as it is.
            Write-Host "      ! RENAME REQUIRED rule '$rname' (AdvancedRule differs, and it cannot be updated in place)"
            Write-Host "          deploy will LEAVE THIS RULE UNCHANGED. Give the rule a new name to apply the new detection logic."
            $changes++
        }
        else {
            Write-Host "      = rule '$rname' in sync"
        }
    }

    # Deploy prunes live rules the manifest no longer declares, but only once every desired
    # rule is in place, so a partially reconciled policy is never stripped of all its rules.
    foreach ($lr in $liveRules) {
        if ($null -eq $lr) { continue }
        $lrName = [string]$lr.Name
        if ($desiredNames.ContainsKey($lrName)) { continue }
        if ((Test-HasProperty $lr 'Mode') -and "$($lr.Mode)" -eq 'PendingDeletion') { continue }
        if ($allRulesInPlace) {
            Write-Host "      - REMOVE rule '$lrName' (not in the manifest)"
            $changes++
        }
        else {
            Write-Host "      - REMOVE rule '$lrName' DEFERRED (not in the manifest, but pruning is skipped until every declared rule is in place)"
        }
    }
}
Write-Host "`n=== PLAN SUMMARY: $changes change(s) needed ==="
