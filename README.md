<p align="center">
  <img src="docs/assets/banner.svg" alt="DLPaC: Data Loss Prevention as Code" width="100%">
</p>

# DLPaC: Data Loss Prevention as Code

Manage Microsoft Purview DLP policies as version-controlled code. Write policies in a small YAML
language, compile and validate them offline, and deploy them through a reviewable,
simulation-first pipeline.

```yaml
name: block-external-pci-exchange
archetype: group-scoped-simulation
description: Block credit-card data emailed outside the org.
locations:
  exchange: true
rules:
- name: block-external-pci-exchange-Financial
  detect:
    accessScope: NotInOrganization
    groups:
    - name: Financial
      sensitiveTypes:
      - {name: Credit Card Number, confidence: High}
  actions:
    blockAccess: true
    generateIncidentReport: [admin@example.com]
```

That compiles to a deploy manifest with every name resolved to the GUID Purview requires. A name
that is not in the catalog fails the build rather than deploying a policy that silently matches
nothing.

**Why this exists.** DLP is normally managed by clicking through a portal, where a misconfigured
rule does not fail loudly, it just matches nothing, and zero alerts looks exactly like zero
violations. Catching that requires validation, review, and staged rollout before deployment. See
[docs/rationale.md](docs/rationale.md) for the full argument.

## Requirements

To author, compile, and test, which is everything except talking to a tenant:

- Python 3.10 or later (`jsonschema==4.26.0` does not support earlier versions; CI uses 3.12)
- No tenant, credentials, or network access

To deploy to Purview, additionally:

- Windows with PowerShell 5.1, since `Connect-IPPSSession` is Windows-only
- The `ExchangeOnlineManagement` module (the scripts install it if missing)
- An Entra app registration with certificate auth and Purview permissions, plus an Azure Key Vault
  holding the certificate

## Install

```sh
git clone https://github.com/s0undsystem/DLP-as-Code.git
cd DLP-as-Code
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt   # editable install of the project and its deps
```

That installs `dlpac` as a package, so `compiler` and `assistant` import from anywhere and a
`dlpac-compile` command is available. For the Claude backend, `pip install -e '.[claude]'`.

## Quickstart

```sh
python -m compiler.compile          # policies/*.yaml -> build/manifest.json
python tests/test_compiler.py       # 13 tests
python tests/test_assistant.py      # 12 tests
```

`dlpac-compile` and `python compiler/compile.py` do the same thing. It prints the number of
policies compiled and writes `build/manifest.json`. Nothing here
touches a tenant, so this works on macOS, Linux, and Windows alike.

## Writing a policy

Add a YAML file to `policies/`, then recompile. The example above is a complete policy.

- `locations` selects surfaces: `exchange`, `teams`, `sharePoint`, `oneDrive`, `endpoint`,
  `copilot`.
- `scope.group` fences a policy to a group; Copilot uses `scope.users` instead.
- `archetype` inherits shared defaults from `archetypes/`, such as simulation mode plus pilot-group
  scope. Policy keys override archetype keys.
- Sensitive information types, sensitivity labels, groups, and sites are written as human names and
  resolved from `catalog/catalog.json` at build time.

Existing examples in [`policies/`](policies/) cover label-based detection, financial identifiers, a
Copilot-scoped policy, and a `rawAdvancedRule` passthrough for detection the structured form does
not yet express. Full field reference: [docs/dsl-reference.md](docs/dsl-reference.md).

## Deploying to Purview

Set these as repository **variables**:

`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `KEY_VAULT_NAME`, `CERT_NAME`,
`M365_ORGANIZATION`

Four workflows implement the pipeline:

| Workflow | Trigger | Runner | Effect |
|---|---|---|---|
| `validate` | push, pull request | `ubuntu-latest` | compile and test; no tenant access |
| `plan` | pull request | `windows-latest` | read-only diff of manifest against the tenant |
| `deploy` | manual dispatch | `windows-latest` | applies the manifest |
| `drift` | daily cron | `windows-latest` | exports the tenant, opens a PR on divergence |

Enforcement is gated. `deploy` takes an `allow_enforce` input which sets `DLP_ALLOW_ENFORCE`, and
`Invoke-Deploy.ps1` refuses any policy with `Mode: Enable` unless it is `true`, halting the run.
Simulation modes deploy freely. Point `deploy` at a protected environment with required reviewers to
make enforcement a human decision as well as a flagged one.

A run reports `N deployed, N skipped, N failed` and exits non-zero if any failed. Skipped means the
policy was processed but left incomplete, usually a rule still in `PendingDeletion`; re-run once the
service finishes.

Refresh the catalog from your own tenant with `powershell/Update-Catalog.ps1`. The sensitive
information type GUIDs shipped in `catalog/catalog.json` are Microsoft's global built-in
identifiers and are the same in every tenant; groups, sensitivity labels, sites, and custom types
are placeholders that must be replaced.

To run locally rather than in CI, dot-source `powershell/Connect-Dlp.ps1` first so it exports
`DLP_CERT_THUMBPRINT` into the same process, then run `Invoke-Plan.ps1` or `Invoke-Deploy.ps1`.

## The assistant

An optional layer drafts policies from plain English and answers coverage questions. Every draft is
pushed through the same compiler a hand-written policy goes through, and one that does not compile
cannot open a pull request.

```sh
# No model at all: exercises the full path with no key, network, or cost
DLPAC_BRAIN=dry-run python -m assistant.eval

# Local OpenAI-compatible endpoint (Ollama, LM Studio, vLLM)
export DLPAC_BRAIN=local
export DLPAC_LOCAL_BASE_URL=http://localhost:11434/v1
export DLPAC_LOCAL_MODEL=qwen2.5-coder:14b

# Anthropic API
export DLPAC_BRAIN=claude ANTHROPIC_API_KEY=...
export DLPAC_CLAUDE_MODEL=claude-opus-5   # optional; overrides the default model
pip install anthropic       # optional dependency, only for this backend

python -m assistant.eval --show-drafts
```

`eval` reports how many drafts compile. That measures form, not intent: a policy can compile
perfectly and still watch the wrong data type, which is why output is always a pull request for a
human to review. Details in
[docs/architecture.md](docs/architecture.md#the-natural-language-layer).

## Repository layout

```
pyproject.toml packaging: dependencies, entry points, project metadata
compiler/      schema, validator, name-to-GUID resolver, compiler
catalog/       sample catalog (global built-in SIT GUIDs; placeholders elsewhere)
archetypes/    reusable policy defaults
policies/      example policies
powershell/    Connect, Plan, Deploy, Export, Update-Catalog, Remove (Windows only)
assistant/     natural-language layer: brain interface, backends, validator, eval
tests/         unit tests, no tenant access
docs/          rationale, architecture, DSL reference
.github/       validate, plan, deploy, drift workflows
```

## Documentation

| Document | Contents |
|---|---|
| [docs/rationale.md](docs/rationale.md) | Why DLP belongs in code, related work, design principles, portability |
| [docs/architecture.md](docs/architecture.md) | Pipeline contracts, Purview service behaviours, the assistant, safety model, open problems |
| [docs/dsl-reference.md](docs/dsl-reference.md) | Every field in the policy language |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Setup, house rules, what to work on |
| [SECURITY.md](SECURITY.md) | Reporting vulnerabilities, scope, operational notes for forks |

If you are deciding whether to adopt this, read the rationale. If you are extending it, read the
architecture, particularly the substrate findings: several non-obvious Purview behaviours constrain
what the deploy engine is allowed to do.

## Contributing

Issues and pull requests are welcome. The compiler, the assistant, and both test suites run with no
tenant access, so most contributions can be developed and verified entirely offline. See
[CONTRIBUTING.md](CONTRIBUTING.md) for setup and house rules, and
[open problems](docs/architecture.md#open-problems) for the known unsolved work.

Reports of how the Purview service actually behaves are especially welcome. Much of the deploy
engine's shape comes from undocumented service behaviour discovered against a live tenant, and that
knowledge is expensive to rediscover.

## Citing this work

If you build on the methodology or the code, see [CITATION.cff](CITATION.cff). GitHub renders it as
a "Cite this repository" option in the sidebar.

## License

[Apache License 2.0](LICENSE), Copyright 2026 Jared Medeiros. See [NOTICE](NOTICE).

Apache 2.0 permits commercial use, modification, and redistribution, including in closed-source
products. It requires that you preserve the copyright and [NOTICE](NOTICE) attribution, state any
changes you made, and include a copy of the license. It also grants an express patent license from
contributors, and terminates that grant for anyone who initiates patent litigation over the
software.
