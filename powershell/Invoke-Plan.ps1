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
    For each policy/rule in the manifest, reports whether it would be created, updated, or is
    already in sync with the tenant. AdvancedRule comparison is structural (JSON parsed and
    canonicalized) so cosmetic whitespace differences don't show as drift. Exit code is 0
    regardless of diff (planning is informational); the change count is printed at the end.
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

    foreach ($rule in $pol.rules) {
        $rname = $rule.name
        $liveRule = Get-DlpComplianceRule -Identity $rname -ErrorAction SilentlyContinue
        if ($null -eq $liveRule) {
            Write-Host "      + CREATE rule '$rname'"
            $changes++
        }
        elseif ((Get-Canonical $liveRule.AdvancedRule) -ne (Get-Canonical $rule.advancedRule)) {
            Write-Host "      ~ UPDATE rule '$rname' (AdvancedRule differs)"
            $changes++
        }
        else {
            Write-Host "      = rule '$rname' in sync"
        }
    }
}
Write-Host "`n=== PLAN SUMMARY: $changes change(s) needed ==="
