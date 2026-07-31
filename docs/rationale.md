# Rationale

Why this project exists, what it claims, and how it relates to work that came before. This is the
argument; [architecture.md](architecture.md) is the mechanism and the [README](../README.md) is how
to run it.

## 1. Position

A data loss prevention policy is a predicate over data flows. It decides, for every message, file,
upload, and prompt crossing a boundary, whether that flow is permitted. That is a program. It is
almost universally authored by clicking through a web form.

The usual objection to portal administration is ergonomic: no version history, no peer review, no
diff. Those complaints are true and they are not the interesting ones. The interesting problem is
that DLP has no natural failure signal.

Consider what happens when a rule is wrong. A misconfigured firewall drops traffic and someone
files a ticket within the hour. A misconfigured DLP rule matches nothing, and nothing happens.
No error is raised, no alert fires, no user is blocked, and the dashboard shows zero policy
violations, which is exactly what a correctly functioning policy over clean traffic also shows.
The two states are observationally identical from the console. A control whose failure mode is
silence cannot be validated by watching it run, and an organization can hold a policy it believes
is protecting a data class for years without that belief ever being tested.

This is why the feedback loops that eventually discipline other kinds of configuration never
engage here. There is no failing test to notice, no page at 3am, no user complaint. The only
mechanisms that can catch a wrong DLP policy are the ones applied before it is deployed: static
validation, review by someone other than the author, and an explicit staged rollout. All three are
properties of a build pipeline, and none of them are properties of a web form.

There is a second, quieter cost. Purview's unified audit log records that a policy changed and who
changed it, which is genuinely useful for forensics and useless for review. It captures the
mutation and discards the reasoning. Six months later the question is never "who edited this rule"
but "why is the confidence threshold Medium here and High everywhere else", and that answer was
never written down, because the interface that accepted the change had nowhere to put it. A commit
message and a pull request discussion are not process overhead; they are the only durable record
of intent that the system will ever have.

The position of this project follows from those two observations. A data protection control plane
should be a compiler target, not a user interface. Policies should be written in a language with a
schema, checked by a validator that fails loudly, stored where they can be diffed and reviewed,
and applied by a machine that does exactly and only what the source says. The portal becomes a
read-only view of a state that is authored somewhere else.

Purview is where that claim is demonstrated here. It is not what the claim is about.

## 2. Related work

The idea is an application of a pattern, not an invention. Infrastructure moved to code with CFEngine
and later Terraform and Pulumi. Detection engineering moved with Sigma and the detection-as-code
tooling built around it. Authorization policy moved with Open Policy Agent and Kyverno. Compliance
benchmarking moved with OpenSCAP and InSpec. Each transition followed the same arc: a domain
administered through consoles, a growing gap between what operators believed was configured and
what was, and eventually a declarative source of truth with a compiler and a diff.

Data loss prevention has been unusually resistant to this transition, and it is worth being precise
about the closest existing work rather than claiming empty territory.

[Microsoft365DSC](https://microsoft365dsc.com/) is the most direct prior art. It exposes DLP through
PowerShell Desired State Configuration resources, including
[`SCDLPCompliancePolicy`](https://microsoft365dsc.com/resources/security-compliance/SCDLPCompliancePolicy/)
and [`SCDLPComplianceRule`](https://microsoft365dsc.com/resources/security-compliance/SCDLPComplianceRule/),
and it can export and reapply tenant configuration. Anyone evaluating DLPaC should evaluate it
first, because for broad tenant configuration management it does more.

The difference is one of altitude, and it cuts both ways. Microsoft365DSC is a general-purpose,
resource-oriented mirror of the underlying cmdlet surface across the whole of Microsoft 365: its
DLP resources take the cmdlet parameters more or less as they are. DLPaC is narrow by comparison,
covering DLP alone, and buys three things with that narrowness. Detection is authored structurally
rather than as a hand-built `AdvancedRule` blob, which remains an
[open issue](https://github.com/microsoft/Microsoft365DSC/issues/3455) in the DSC resources.
References are written as human names and resolved to GUIDs at build time, so an unresolvable name
is a build failure rather than a silently inert policy. And simulation is a first-class stage in
the workflow rather than a property you happen to set.

Those are trade-offs, not a verdict. A general resource provider and a domain-specific language are
different tools, and the second is only worth building if the domain has enough structure to
justify a language of its own. The substrate findings in
[architecture.md](architecture.md#notes-on-the-substrate) are the argument that DLP does.

## 3. Design principles

**1. Resolution fails closed.** Purview matches on GUIDs; humans think in names. The compiler maps
names to GUIDs from `catalog/catalog.json`, and a name that is not in the catalog terminates the
build. This is a direct consequence of Section 1: the worst outcome for a DLP policy is not an
error, it is a policy that deploys cleanly and matches nothing. Given the choice between failing at
build time and shipping something inert, the build must fail. Every reference type resolves this
way, including sensitive information types, sensitivity labels, groups, and SharePoint sites.

**2. Simulation is a stage, not a setting.** Purview's test modes exist, but nothing about the portal
makes staged rollout the default path. Here, `TestWithoutNotifications` and `TestWithNotifications`
deploy freely while `Mode: Enable` is refused unless enforcement is explicitly and separately
authorized. The gate is in the deploy engine, not in documentation, so the ordering cannot be
skipped by an operator in a hurry.

**3. The manifest is an intermediate representation.** `build/manifest.json` is not a cache or a log.
It is the IR of a three-stage compiler: YAML source is the front end, the manifest is the IR, and
the PowerShell deploy engine is the code generator for one target. Naming it this way is a design
commitment rather than a metaphor. The manifest is fully determined by the source and the catalog,
it can be inspected and diffed without tenant access, and it is the only interface the backend is
allowed to depend on.

**4. The front end is provider-agnostic; only the backend is not.** The language, schema, resolver,
and compiler contain no Purview API calls and no tenant access. This is what makes the entire
authoring and validation path runnable offline on any operating system, and it is the precondition
for the portability discussed in Section 4.

**5. Nothing reaches the tenant without passing through review.** Every change, whether typed by a
human or drafted by a model, arrives as a pull request. This is the only mechanism that captures
intent, and per Section 1 it is one of the few controls that can catch a wrong policy at all.

## 4. Beyond Purview

Section 1 makes a claim about control planes generally, so the question of whether this generalizes
is fair. Part of the answer is already settled by the architecture and part of it is honestly not.

What is provider-independent today is a matter of fact rather than intent. The language, the JSON
Schema, the resolver, the compiler, and the manifest contain no Purview API calls, no cmdlet
invocations, and no tenant access. The entire front end runs offline on any operating system, and
the tests exercise it without credentials. Everything Purview-specific lives under `powershell/` and
consumes the manifest through a documented contract. A second backend would be a new code generator
reading the same IR, not a fork.

What is not yet general is equally concrete, and lives in the vocabulary rather than the structure.
`rawAdvancedRule` is explicitly a Purview escape hatch and would have no meaning elsewhere. The
catalog is built around Purview's identifiers for sensitive information types and sensitivity
labels. The Copilot surface is a Microsoft product. Some concepts in the language are plainly
universal, including detection over sensitive data types, scoping, enforcement actions, and staged
rollout; others are Purview's model showing through.

The honest statement is that the pipeline architecture generalizes and the language has not yet been
tested against a second target. Writing one backend proves nothing about portability. The plausible
candidates are Google Workspace DLP, endpoint and network vendors such as Netskope or Zscaler, and
cloud-native scanners such as AWS Macie, and doing any of them is what would force the separation of
universal concepts from Purview's. That work is listed under
[open problems](architecture.md#open-problems) rather than claimed here.
