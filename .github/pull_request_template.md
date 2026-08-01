## What and why

<!-- What changes, and what problem it solves. Link an issue if there is one. -->

## Type

- [ ] Bug fix
- [ ] New capability (compiler, DSL, deploy engine, assistant)
- [ ] Encodes a Purview service behaviour learned from a live tenant
- [ ] Docs
- [ ] Chore / tooling

## If this encodes tenant behaviour

<!-- What the service did, verbatim error strings, and what the engine now does instead.
     Add it to docs/architecture.md#notes-on-the-substrate so it is not rediscovered. -->

## Checklist

- [ ] `python compiler/compile.py` succeeds
- [ ] `python tests/test_compiler.py` and `python tests/test_assistant.py` pass
- [ ] New or changed compiler behaviour has a test
- [ ] Any new source file carries the SPDX license header
- [ ] `powershell/*.ps1` are still pure ASCII (if touched)
- [ ] No tenant-specific values: GUIDs, site URLs, UPNs, tenant IDs, thumbprints
- [ ] Fail-closed resolution is preserved
