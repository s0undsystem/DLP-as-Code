"""DLPaC assistant — the natural-language layer over the DLP-as-code pipeline.

Model-agnostic by design. The three pieces here have NO dependency on any AI model:

  context.py    assemble the repo facts a brain needs (catalog, schema, policies)
  validator.py  run a candidate YAML draft through the real compiler and report pass/fail
  brain.py      the provider seam: a Brain interface + a DryRunBrain that calls nothing

A real model (Claude via the API, or a local model) plugs in as one Brain implementation.
Everything else — context, validation, and eventually the GitHub Action wiring — is
deterministic and survives any decision about which model (or whether any) does the thinking.
"""
