#Requires -Version 5.1
<#
.SYNOPSIS
    Deploy a compiled DLP manifest to the tenant via native S&C cmdlets (idempotent).

    Runs under Windows PowerShell 5.1. Requires cert prep by Connect-Dlp.ps1 in the same
    process (sets $env:DLP_CERT_THUMBPRINT). Reads build/manifest.json (from compile.py).

.DESCRIPTION
    For each policy in the manifest: create it if absent, else update Mode/Comment; then
    create-or-update its rule via -AdvancedRule, and apply actions. Create uses the compiled
    location/scoping parameters (e.g. TeamsLocation = group GUID).

    ENFORCEMENT GATE: a policy with Mode=Enable is refused unless $env:DLP_ALLOW_ENFORCE
    equals 'true'. Simulation modes (TestWithoutNotifications / TestWithNotifications) always
    proceed. This is how "simulation first, enforce is a separate gated run" is enforced.
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
$allowEnforce = ($env:DLP_ALLOW_ENFORCE -eq 'true')

if (-not (Get-Module -ListAvailable -Name ExchangeOnlineManagement)) {
    Install-Module ExchangeOnlineManagement -Force -Scope CurrentUser -AllowClobber
}
Import-Module ExchangeOnlineManagement
Write-Host "Connecting app-only to Security & Compliance for '$env:M365_ORGANIZATION'..."
Connect-IPPSSession -AppId $env:AZURE_CLIENT_ID -CertificateThumbprint $env:DLP_CERT_THUMBPRINT `
    -Organization $env:M365_ORGANIZATION -ShowBanner:$false
Write-Host "Connected."

function ConvertTo-Splat {
    param($obj)
    $h = @{}
    if ($null -ne $obj) {
        foreach ($p in $obj.PSObject.Properties) { $h[$p.Name] = @($p.Value) }
    }
    return $h
}

# JSON objects (e.g. alertProperties) deserialize as PSCustomObject; cmdlet params that expect a
# hashtable need conversion. Recurse so nested objects become nested hashtables.
function ConvertTo-ParamValue {
    param($Value)
    if ($Value -is [System.Management.Automation.PSCustomObject]) {
        $h = @{}
        foreach ($p in $Value.PSObject.Properties) { $h[$p.Name] = (ConvertTo-ParamValue $p.Value) }
        return $h
    }
    return $Value
}

foreach ($pol in $manifest.policies) {
    $name = $pol.name
    $mode = $pol.mode
    if ($mode -eq 'Enable' -and -not $allowEnforce) {
        throw "Policy '$name' requests Mode=Enable, but enforcement is gated. Re-run with DLP_ALLOW_ENFORCE=true to enforce. Refusing."
    }
    $comment = if ($pol.PSObject.Properties.Name -contains 'comment') { [string]$pol.comment } else { '' }

    $existing = Get-DlpCompliancePolicy -Identity $name -ErrorAction SilentlyContinue
    if ($null -eq $existing) {
        $locSplat = ConvertTo-Splat $pol.locations
        if ($locSplat.Count -eq 0) {
            throw "Policy '$name' compiled to no location/scoping parameters (e.g. Copilot user-scoping is not deployable yet). Refusing to create an unscoped policy."
        }
        Write-Host "Creating policy '$name' (Mode=$mode; scope=$($locSplat.Keys -join ','))..."
        New-DlpCompliancePolicy -Name $name -Mode $mode -Comment $comment @locSplat -ErrorAction Stop | Out-Null
    }
    else {
        Write-Host "Updating policy '$name' (Mode=$mode)..."
        Set-DlpCompliancePolicy -Identity $name -Mode $mode -Comment $comment -ErrorAction Stop | Out-Null
        Write-Host "  note: location/scope changes on an existing policy are not auto-reconciled yet (future work)."
    }

    foreach ($rule in $pol.rules) {
        $rname = $rule.name
        # Action params MUST be applied at creation: Purview rejects setting actions on an
        # AdvancedRule-based rule via a follow-up Set (validated 2026-07-27).
        $actSplat = @{}
        if ($rule.PSObject.Properties.Name -contains 'params' -and $null -ne $rule.params) {
            foreach ($a in $rule.params.PSObject.Properties) { $actSplat[$a.Name] = (ConvertTo-ParamValue $a.Value) }
        }
        $existingRule = Get-DlpComplianceRule -Identity $rname -ErrorAction SilentlyContinue
        if ($null -eq $existingRule) {
            Write-Host "  Creating rule '$rname' ($($actSplat.Count) action param(s))..."
            New-DlpComplianceRule -Name $rname -Policy $name -AdvancedRule $rule.advancedRule @actSplat -ErrorAction Stop | Out-Null
        }
        else {
            Write-Host "  Updating rule '$rname'..."
            Set-DlpComplianceRule -Identity $rname -AdvancedRule $rule.advancedRule @actSplat -ErrorAction Stop | Out-Null
        }
    }

    Write-Host "Policy '$name' deployed."
}

Write-Host "DEPLOY COMPLETE ($(@($manifest.policies).Count) policy(ies))."
