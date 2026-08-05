# Copyright 2026 Jared Medeiros
# SPDX-License-Identifier: Apache-2.0
# Part of DLPaC (https://github.com/s0undsystem/DLP-as-Code). See NOTICE.

"""Run a candidate policy draft through the REAL compiler and report pass/fail.

This is the guardrail that makes any brain safe. A draft is only trustworthy if it survives
the exact same path a hand-written policy takes: YAML parse -> archetype merge -> JSON-Schema
validation -> fail-closed name->GUID resolution -> AdvancedRule construction. `compile_policy`
already chains all of that and raises loudly on any failure, so we wrap one call to it.

No tenant access and no model involved — this runs anywhere the compiler runs (incl. the Mac).
"""
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

from compiler.compile import compile_policy
from compiler.resolver import Catalog, ResolutionError, load_catalog

_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_ARCHETYPE_DIR = os.path.join(_ROOT, "archetypes")
_DEFAULT_CATALOG = os.path.join(_ROOT, "catalog", "catalog.json")

# Stages, in the order the pipeline runs them. `stage` on a failure names where it stopped.
STAGE_PARSE = "yaml_parse"
STAGE_COMPILE = "schema_and_resolve"  # compile_policy does schema validation + resolution together
STAGE_OK = "ok"


@dataclass
class DraftResult:
    """Outcome of pushing one draft through the compiler."""
    ok: bool
    stage: str
    errors: List[str] = field(default_factory=list)
    manifest_entry: Optional[Dict[str, Any]] = None  # the compiled policy, present only when ok

    def summary(self) -> str:
        if self.ok:
            return f"PASS ({self.stage}): draft compiles and every reference resolves."
        return f"FAIL ({self.stage}):\n" + "\n".join(f"  - {e}" for e in self.errors)


def validate_draft(yaml_text: str,
                   catalog: Optional[Catalog] = None,
                   archetype_dir: str = _ARCHETYPE_DIR) -> DraftResult:
    """Push a single-policy YAML draft through the compiler; report where (if) it fails.

    A model's authored draft is only allowed to open a PR if this returns ok=True.
    """
    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        return DraftResult(ok=False, stage=STAGE_PARSE, errors=[f"YAML parse error: {e}"])
    if not isinstance(raw, dict):
        return DraftResult(ok=False, stage=STAGE_PARSE,
                           errors=["Draft is not a single YAML mapping (one policy document expected)."])

    if catalog is None:
        catalog = load_catalog(_DEFAULT_CATALOG)

    try:
        entry = compile_policy(raw, catalog, archetype_dir)
    except ValueError as e:
        # Schema violations (validate_policy) and archetype problems surface as ValueError.
        return DraftResult(ok=False, stage=STAGE_COMPILE, errors=[str(e)])
    except ResolutionError as e:
        # A SIT/label/group/site name not in the catalog — the fail-closed guarantee.
        return DraftResult(ok=False, stage=STAGE_COMPILE, errors=[str(e)])

    return DraftResult(ok=True, stage=STAGE_OK, manifest_entry=entry)
