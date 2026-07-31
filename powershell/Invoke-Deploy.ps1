#Requires -Version 5.1
<#
.SYNOPSIS
    Deploy a compiled DLP manifest to the tenant via native S&C cmdlets (idempotent).

    Runs under Windows PowerShell 5.1. Requires cert prep by Connect-Dlp.ps1 in the same
    process (sets $env:DLP_CERT_THUMBPRINT). Reads build/manifest.json (from compile.py).

.DESCRIPTION
    For each policy in the manifest: create it if absent, else update Mode/Comment; then
    reconcile its rules. Create uses the compiled location/scoping parameters (e.g.
    TeamsLocation = group GUID), or the Copilot -Locations blob when the policy targets
    Microsoft 365 Copilot.

    RULE RECONCILIATION IS CREATE-OR-LEAVE, NEVER UPDATE. Two tenant behaviours force this:
      1. Set-DlpComplianceRule -AdvancedRule is rejected with a generic server side error,
         so an existing AdvancedRule rule can never be updated in place.
      2. Remove-DlpComplianceRule is ASYNC. A removed rule lingers in Mode=PendingDeletion,
         and re-creating the same name while it lingers fails with "already exists". So a
         remove-then-recreate cycle is never safe either.
    A rule that already exists is therefore left untouched. To change a rule's detection
    logic, give the rule a new name (or delete it and deploy on a later run, once the
    tenant has finished the async removal).

    DLP policy and rule names are CASE-INSENSITIVE in Purview, so all name matching here
    uses case-insensitive lookups (PowerShell hashtables, which are case-insensitive by
    default) to avoid trying to create a rule the tenant considers a duplicate.

    ENFORCEMENT GATE: a policy with Mode=Enable is refused unless $env:DLP_ALLOW_ENFORCE
    equals 'true'. Simulation modes (TestWithoutNotifications / TestWithNotifications) always
    proceed. This is how "simulation first, enforce is a separate gated run" is enforced.
    The gate is a hard stop for the whole run; per-policy errors are not.

    RESILIENCE: each policy is processed inside try/catch. A policy that errors is recorded
    as failed and the run continues to the next policy. The script prints a summary and
    exits non-zero if any policy failed.
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
# hashtable need conversion. Recurse into objects AND arrays, so an array of objects (such as
# RestrictAccess = [{ value = Block }]) becomes an array of hashtables, matching the cmdlet's
# Hashtable[] parameter type rather than an unusable array of PSCustomObjects.
function ConvertTo-ParamValue {
    param($Value)
    if ($Value -is [System.Management.Automation.PSCustomObject]) {
        $h = @{}
        foreach ($p in $Value.PSObject.Properties) { $h[$p.Name] = (ConvertTo-ParamValue $p.Value) }
        return $h
    }
    if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string]) {
        $items = @()
        foreach ($item in $Value) { $items += , (ConvertTo-ParamValue $item) }
        # Comma-wrap the return so a single-element array is not unrolled to a bare scalar.
        return , $items
    }
    return $Value
}

function Test-HasProperty {
    param($Object, [string] $Name)
    if ($null -eq $Object) { return $false }
    return ($Object.PSObject.Properties.Name -contains $Name)
}

# A rule the tenant is still asynchronously deleting. Re-creating this name would fail.
function Test-PendingDeletion {
    param($Rule)
    if ($null -eq $Rule) { return $false }
    if (-not (Test-HasProperty $Rule 'Mode')) { return $false }
    return ("$($Rule.Mode)" -eq 'PendingDeletion')
}

$deployed = 0
$skipped = 0
$failed = 0
$failedNames = @()

foreach ($pol in $manifest.policies) {
    $name = $pol.name
    $mode = $pol.mode

    # Hard stop for the whole run, deliberately OUTSIDE the per-policy try/catch: an
    # ungated enforcement request is an operator error, not a transient policy failure.
    if ($mode -eq 'Enable' -and -not $allowEnforce) {
        throw "Policy '$name' requests Mode=Enable, but enforcement is gated. Re-run with DLP_ALLOW_ENFORCE=true to enforce. Refusing."
    }

    try {
        $comment = if (Test-HasProperty $pol 'comment') { [string]$pol.comment } else { '' }
        $copilotLocations = ''
        if (Test-HasProperty $pol 'copilotLocations') { $copilotLocations = [string]$pol.copilotLocations }
        $isCopilot = -not [string]::IsNullOrWhiteSpace($copilotLocations)

        $existing = Get-DlpCompliancePolicy -Identity $name -ErrorAction SilentlyContinue
        if ($null -eq $existing) {
            if ($isCopilot) {
                $planes = @()
                if (Test-HasProperty $pol 'enforcementPlanes') { $planes = @($pol.enforcementPlanes) }
                if ($planes.Count -eq 0) { $planes = @('CopilotExperiences') }
                Write-Host "Creating Copilot policy '$name' (Mode=$mode; planes=$($planes -join ','))..."
                New-DlpCompliancePolicy -Name $name -Mode $mode -Comment $comment `
                    -Locations $copilotLocations -EnforcementPlanes $planes -ErrorAction Stop | Out-Null
            }
            else {
                $locSplat = ConvertTo-Splat $pol.locations
                if ($locSplat.Count -eq 0) {
                    throw "Policy '$name' compiled to no location/scoping parameters. Refusing to create an unscoped policy."
                }
                Write-Host "Creating policy '$name' (Mode=$mode; scope=$($locSplat.Keys -join ','))..."
                New-DlpCompliancePolicy -Name $name -Mode $mode -Comment $comment @locSplat -ErrorAction Stop | Out-Null
            }
        }
        else {
            Write-Host "Updating policy '$name' (Mode=$mode)..."
            Set-DlpCompliancePolicy -Identity $name -Mode $mode -Comment $comment -ErrorAction Stop | Out-Null
            Write-Host "  note: location/scope changes on an existing policy are not auto-reconciled yet (future work)."
        }

        # --- Rule reconciliation: create missing rules, leave existing ones alone. ---
        $desiredRules = @($pol.rules)
        $desiredNames = @{}   # case-insensitive set of names this policy should end up with
        foreach ($r in $desiredRules) { $desiredNames[[string]$r.name] = $true }

        # One live fetch per policy, rather than a Get per rule.
        $liveRules = @(Get-DlpComplianceRule -Policy $name -ErrorAction SilentlyContinue)
        $liveByName = @{}
        foreach ($lr in $liveRules) {
            if ($null -ne $lr) { $liveByName[[string]$lr.Name] = $lr }
        }

        $allRulesInPlace = $true
        foreach ($rule in $desiredRules) {
            $rname = [string]$rule.name

            if ($liveByName.ContainsKey($rname)) {
                $liveRule = $liveByName[$rname]
                if (Test-PendingDeletion $liveRule) {
                    # Async removal still in flight; creating this name now would fail with
                    # "already exists". Leave it for a later run.
                    Write-Warning "  Rule '$rname' is in Mode=PendingDeletion (async removal in flight); skipping. Re-run once the tenant finishes deleting it."
                    $allRulesInPlace = $false
                    continue
                }
                Write-Host "  = rule '$rname' already exists; leaving untouched (AdvancedRule rules cannot be updated in place)."
                continue
            }

            # Action params MUST be applied at creation: Purview rejects setting actions on an
            # AdvancedRule-based rule via a follow-up Set.
            $actSplat = @{}
            if ((Test-HasProperty $rule 'params') -and $null -ne $rule.params) {
                foreach ($a in $rule.params.PSObject.Properties) { $actSplat[$a.Name] = (ConvertTo-ParamValue $a.Value) }
            }
            Write-Host "  + Creating rule '$rname' ($($actSplat.Count) action param(s))..."
            New-DlpComplianceRule -Name $rname -Policy $name -AdvancedRule $rule.advancedRule @actSplat -ErrorAction Stop | Out-Null
        }

        # --- Prune: drop live rules this policy no longer declares. ---
        # Only safe once every desired rule is actually in place; otherwise a partially
        # reconciled policy could be stripped down to no rules at all.
        if ($allRulesInPlace) {
            foreach ($lr in $liveRules) {
                if ($null -eq $lr) { continue }
                $lrName = [string]$lr.Name
                if ($desiredNames.ContainsKey($lrName)) { continue }
                if (Test-PendingDeletion $lr) { continue }
                Write-Host "  - Removing rule '$lrName' (no longer in the manifest)..."
                Remove-DlpComplianceRule -Identity $lr.Identity -Confirm:$false -ErrorAction Stop | Out-Null
            }
        }
        else {
            Write-Warning "  Skipping prune for '$name': not all declared rules are in place yet."
        }

        if ($allRulesInPlace) {
            Write-Host "Policy '$name' deployed."
            $deployed++
        }
        else {
            Write-Warning "Policy '$name' deployed INCOMPLETELY (one or more rules pending). Re-run later."
            $skipped++
        }
    }
    catch {
        # Per-policy resilience: one bad policy must not abandon the rest of the manifest.
        Write-Warning "Policy '$name' FAILED: $($_.Exception.Message)"
        $failed++
        $failedNames += $name
        continue
    }
}

Write-Host ""
Write-Host "DEPLOY SUMMARY: $deployed deployed, $skipped skipped, $failed failed."
if ($failed -gt 0) {
    Write-Host "Failed policies: $($failedNames -join ', ')"
    exit 1
}
exit 0
