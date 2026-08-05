# Contributing to DLPaC

Contributions are welcome. Most of this project can be developed and verified with no Microsoft 365
tenant, no credentials, and no network access, so the barrier to a useful first patch is low.

## Getting set up

Python 3.10 or later is required, since `jsonschema==4.26.0` does not support earlier versions. CI
runs 3.12.

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

python -m compiler.compile          # compiles policies/*.yaml to build/manifest.json
python tests/test_compiler.py       # 13 tests
python tests/test_assistant.py      # 12 tests
```

All three must pass before you open a pull request. The `validate` workflow runs exactly these on
every push.

## What to work on

[Open problems](docs/architecture.md#open-problems) lists the known unsolved work, from rule
immutability through to implementing a second, non-Purview backend. Those are the highest-value
contributions. Bug reports with a reproducing policy YAML are also genuinely useful.

Before proposing a change to the deploy engine, read
[notes on the substrate](docs/architecture.md#notes-on-the-substrate). Several behaviours that look
like bugs in `Invoke-Deploy.ps1` are deliberate accommodations of Purview service behaviour, and a
patch that "fixes" one of them will break against a real tenant.

## House rules

**PowerShell files must be pure ASCII.** Windows PowerShell 5.1 reads a script without a byte-order
mark as ANSI, so a single non-ASCII character inside a string literal, typically a typographic dash
pasted from a document, corrupts parsing with an error that points nowhere near the cause. Check
before committing:

```sh
python -c "import glob,sys; bad=[p for p in glob.glob('powershell/*.ps1') if any(b>127 for b in open(p,'rb').read())]; print(bad or 'clean'); sys.exit(1 if bad else 0)"
```

**Never commit tenant-specific values.** Group GUIDs, sensitivity label GUIDs, site URLs, user
principal names, tenant IDs, and certificate thumbprints belong in your own catalog, not in this
repository. Examples use `user@example.com` and zeroed placeholder GUIDs. The sensitive information
type GUIDs in `catalog/catalog.json` are the exception: those are Microsoft's global built-in
identifiers, identical in every tenant, and are safe to ship.

**Resolution must stay fail-closed.** An unresolvable name has to break the build. A change that
makes the compiler tolerate an unknown sensitive information type, label, or group would let a
policy deploy that silently matches nothing, which is the specific failure this project exists to
prevent.

**New source files need a license header.** Three lines at the top, after any shebang or
`#Requires` directive:

```
# Copyright 2026 Jared Medeiros
# SPDX-License-Identifier: Apache-2.0
# Part of DLPaC (https://github.com/s0undsystem/DLP-as-Code). See NOTICE.
```

## Pull requests

Explain what changed and why. If the change encodes something you learned from a live tenant, say so
explicitly and include the error message or behaviour you observed, since that is exactly the kind of
knowledge that is expensive to rediscover and belongs in
[notes on the substrate](docs/architecture.md#notes-on-the-substrate).

Add a test for anything the compiler does differently. Compiler tests are pure transformations
against the sample catalog and need no tenant.

## Licensing of contributions

This project is licensed under [Apache License 2.0](LICENSE). By submitting a pull request you agree
that your contribution is licensed under the same terms, per Section 5 of the license. There is no
separate CLA.
