# DSL reference

A policy is one YAML document. The authoritative contract is
[`compiler/schema/policy.schema.json`](../compiler/schema/policy.schema.json); this page is the
friendly version.

## Policy

| Field | Required | Notes |
|---|---|---|
| `name` | ✅ | Unique policy name. |
| `mode` | ✅* | `TestWithoutNotifications`, `TestWithNotifications`, `Enable`, `Disable`, `PendingDeletion`. *Supplied by an archetype if omitted. `Enable` deploys only through the gated enforcement run. |
| `locations` | ✅ | At least one surface (below). |
| `rules` | ✅ | One or more rules. |
| `archetype` | | Name of a file in `archetypes/` to inherit from (policy keys win). |
| `description` | | Free text; becomes the policy comment. |
| `priority` | | Integer ≥ 0. |
| `scope.group` | | Friendly group name (resolved to a GUID) the policy is fenced to. |
| `scope.users` | | Individual users (used by the Copilot surface). |

### Locations

`exchange`, `teams`, `oneDrive`, `endpoint`, `copilot` are booleans. `sharePoint` is a boolean or a
site name (resolved to a URL via the catalog). Group-scoped surfaces resolve `scope.group` to the
GUID Purview requires.

#### Copilot

`copilot: true` scopes to individuals via `scope.users`, not `scope.group`. It compiles to a
different deploy shape from the other locations - a `-Locations` JSON blob plus
`-EnforcementPlanes ["CopilotExperiences"]` - and the compiler automatically adds a
`RestrictAccess: [{value: Block}]` action to every rule in the policy, which Purview requires.
You do not declare that action yourself. See `policies/example-copilot-secrets.yaml`.

## Rule

A rule is **either** structured `detect` **or** a raw passthrough — exactly one:

| Field | Notes |
|---|---|
| `name` | Unique rule name. |
| `operator` | `And` / `Or` across sub-conditions (default `And`). |
| `hasActivity` | Optional activity condition (e.g. `UploadText`). |
| `detect` | Structured detection (below). |
| `rawAdvancedRule` | A verbatim AdvancedRule JSON string — GUIDs already embedded. Use for detection the structured form doesn't express yet. |
| `actions` | Rule actions (below). |

### `detect`

| Field | Notes |
|---|---|
| `accessScope` | `InOrganization` or `NotInOrganization`. |
| `groups[]` | Each: `name`, optional `operator`, and **either** `sensitiveTypes` **or** `labels`. |
| `groups[].sensitiveTypes[]` | Each: `name` (must be in the catalog), optional `confidence` (`Low`/`Medium`/`High`), `minCount`, `maxCount`. |
| `groups[].labels[]` | Sensitivity-label names (resolved to GUIDs via the catalog). |

### `actions`

`blockAccess` (bool), `blockAccessScope` (`All`/`PerUser`/`PerAnonymousUser`), `notifyUser` (list),
`notifyPolicyTipText`, `notifyEmail.{text,subject}`, `generateAlert` (bool or recipient list),
`alertProperties` (object), `generateIncidentReport` (bool or recipient list),
`incidentReportContent` (list).

> `generateAlert` / `generateIncidentReport` deploy as active parameters only when given a
> **recipient list**; a bare `true` is treated as documentation.

## Name → GUID resolution

`sensitiveTypes[].name`, `labels[]`, `scope.group`, and SharePoint site names are all **friendly
names** resolved to GUIDs/URLs at compile time from [`catalog/catalog.json`](../catalog/catalog.json).
Resolution is **fail-closed**: an unknown name is a hard build error. Refresh the catalog from your
tenant with `powershell/Update-Catalog.ps1`.
