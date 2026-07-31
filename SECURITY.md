# Security Policy

## Reporting a vulnerability

Please do not open a public issue for a security vulnerability.

Report it through GitHub's private vulnerability reporting on this repository
(Security → Report a vulnerability), which opens a private advisory visible only to the maintainer.

Please include the affected component, what an attacker could achieve, and steps to reproduce.
Expect an initial response within seven days.

## Scope

DLPaC is tooling that manages security policy in a Microsoft 365 tenant, so the interesting failures
are less about memory safety and more about a policy that does not do what its source says. Findings
of the following kinds are in scope:

- A compiled manifest that does not faithfully represent its source policy, particularly any path
  where a policy could deploy narrower than authored, since the result is a control that appears
  present and protects less than intended.
- Any way to bypass the enforcement gate and deploy `Mode: Enable` without `DLP_ALLOW_ENFORCE`.
- Any way to make fail-closed resolution fail open, so an unresolvable name yields a deployable
  policy rather than a build error.
- Credential or certificate handling in `powershell/Connect-Dlp.ps1` and the workflows, including
  anything that would write a thumbprint, certificate, or token into logs or build artifacts.
- Injection through policy YAML into generated cmdlet parameters.
- A path by which the assistant layer could open a pull request containing a policy that did not
  pass the compiler.

Out of scope: vulnerabilities in Microsoft Purview itself, which should go to
[MSRC](https://msrc.microsoft.com/); and anything requiring an attacker who already holds tenant
administrator rights, since such an attacker can edit policy directly in the portal.

## Operational notes

This repository ships no secrets. Deployment authenticates app-only through GitHub OIDC and a
certificate held in Azure Key Vault, so no long-lived credential is stored here. If you fork this
project, note that:

- `catalog/catalog.json` is where tenant-specific GUIDs land once you run
  `powershell/Update-Catalog.ps1`. Group and label GUIDs and site URLs are internal information about
  your organization. Consider whether your fork should be public.
- `build/` and `exports/` are gitignored. `exports/` in particular holds a full dump of your live DLP
  configuration.
- Grant the deploying app registration only the Purview permissions it needs, and protect the
  `deploy` environment with required reviewers.

## Supported versions

The project is pre-1.0 and under active development. Fixes are applied to `main`; there are no
backported release branches.
