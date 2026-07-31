# Architecture

DLPaC is a compile-then-deploy pipeline. The authoring and validation half is pure and
provider-agnostic; only the tenant-facing half is Microsoft Purview / Windows specific.

## Stages

1. **Author** — policies in `policies/*.yaml`, optionally inheriting `archetypes/*.yaml`.
2. **Compile** (`compiler/compile.py`) — merge archetype, validate against the JSON Schema, resolve
   friendly names to GUIDs, and emit `build/manifest.json` describing the cmdlet parameters and the
   AdvancedRule JSON for each rule. No tenant access.
3. **Plan** (`powershell/Invoke-Plan.ps1`) — diff the compiled desired state against a live export.
   Read-only.
4. **Deploy** (`powershell/Invoke-Deploy.ps1`) — idempotent create/reconcile via Security & Compliance
   PowerShell. Simulation-first; enforcement is gated. Policies are create-or-update; rules are
   create-or-leave (see below).
5. **Drift** — scheduled export + diff; opens a PR when the tenant diverges from the committed state.

## Why a resolver, and why fail-closed

Purview matches on GUIDs, but humans think in names. Sensitive-info-types are referenced by name
(with a GUID), and sensitivity labels are referenced by GUID. A build-time resolver maps names →
GUIDs from `catalog/catalog.json`. If a name isn't in the catalog the build **fails** rather than
emitting a policy that silently matches nothing — the most dangerous failure mode for DLP.

Built-in SIT GUIDs are global (identical in every tenant); groups, sensitivity labels, sites, and
custom SITs are tenant-specific and are populated into the catalog from your tenant via
`Update-Catalog.ps1`.

## Safety model

- **Simulation-first:** authored policies use `TestWithoutNotifications` / `TestWithNotifications`.
  Flipping to `Enable` requires the explicit, separately-gated enforcement run.
- **Human-in-the-loop:** every change lands through a pull request; the deploy environment can
  require reviewers.
- **Fail-closed resolution:** unknown references break the build.
- **Least privilege auth:** GitHub OIDC → `azure/login` → certificate in Key Vault →
  `Connect-IPPSSession` (app-only). No secrets in the repo.

## Purview behaviours the deploy engine encodes

These are service constraints observed against a live tenant, not stylistic choices. The deploy
engine is shaped around them:

- **`Set-DlpComplianceRule -AdvancedRule` is rejected** with a generic server side error. An
  existing AdvancedRule rule can never be updated in place.
- **`Remove-DlpComplianceRule` is asynchronous.** A removed rule lingers in `Mode=PendingDeletion`,
  and re-creating the same name while it lingers fails with "already exists" - so remove-and-recreate
  is not a safe substitute for update either.

  Together these make rule reconciliation **create-or-leave**: a rule that already exists is left
  untouched. To change detection logic, give the rule a new name. A rule found in `PendingDeletion`
  is skipped, the policy is reported incomplete, and pruning is suppressed so a policy is never
  stranded with no rules.
- **Policy and rule names are case-insensitive.** All name matching uses case-insensitive lookups.
- **Microsoft 365 Copilot uses a different create shape.** Instead of an `-XLocation` parameter it
  takes a `-Locations` JSON blob (`Workload=Applications`, `Location=Copilot.M365`, one
  `IndividualResource` inclusion per user) plus `-EnforcementPlanes @("CopilotExperiences")`.
- **A Copilot rule must carry a restrict action** or creation fails with
  `ErrorMissingRestrictActionForCopilotException`. The compiler injects
  `RestrictAccess = @(@{value="Block"})`. The value-only shape is deliberate: adding a `setting` key
  alongside a `HasActivity` condition is rejected with
  `InvalidRestrictAccessActionWithHasActivityCondition`.
- **`.ps1` files must be pure ASCII.** Windows PowerShell 5.1 reads a BOM-less script as ANSI, so a
  stray non-ASCII byte inside a string corrupts parsing.

A failing policy is logged and skipped rather than aborting the run; the enforcement gate is the one
hard stop. The run exits non-zero if any policy failed.

## Why Windows for the tenant half

`Connect-IPPSSession` (Security & Compliance PowerShell) is Windows-only, so `plan`, `deploy`, and
`drift` run on `windows-latest`. The compiler and tests are pure Python and run on any OS — you can
develop and validate offline, and CI runs `validate` on Linux.

## The assistant (v2)

A model-optional layer over the same pipeline. It assembles repo context (schema, catalog, existing
policies), asks a model to answer a question or draft a policy, and pushes any draft through the
**same compiler + fail-closed resolver** before it can open a PR. Backends are pluggable
(`assistant/backends.py`): a local OpenAI-compatible model, Claude, or a no-model dry-run. It is a
preview under active development; the compiler/DSL/deploy core is stable.
