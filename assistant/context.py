"""Assemble the repo facts a brain needs to answer or author — pure file I/O, no model.

A RepoContext is a read-only snapshot of what the pipeline already knows: the DSL schema,
the reference catalog (which SITs / labels / groups / sites actually resolve), the archetypes
available, and every policy currently under management. A query brain reads it to answer
"do we cover X"; an authoring brain reads it to draft a policy that will survive the compiler.
"""
import glob
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))


@dataclass
class PolicyDoc:
    """One policy file as it sits on disk (unmerged with its archetype)."""
    name: str
    path: str
    raw: Dict[str, Any]


@dataclass
class RepoContext:
    root: str
    schema: Dict[str, Any]
    catalog: Dict[str, Any]
    policies: List[PolicyDoc] = field(default_factory=list)
    archetypes: List[str] = field(default_factory=list)

    # --- catalog views (the names a brain is allowed to pick; the resolver enforces) ---
    def sit_names(self) -> List[str]:
        return sorted(self.catalog.get("sensitiveInfoTypes", {}).keys())

    def label_names(self) -> List[str]:
        return sorted(self.catalog.get("sensitivityLabels", {}).keys())

    def group_names(self) -> List[str]:
        return sorted(self.catalog.get("groups", {}).keys())

    def site_names(self) -> List[str]:
        return sorted(self.catalog.get("sites", {}).keys())

    def custom_sit_names(self) -> List[str]:
        return sorted(self.catalog.get("customSensitiveInfoTypes", []))

    def policy_names(self) -> List[str]:
        return [p.name for p in self.policies]

    @classmethod
    def load(cls, root: str = ROOT) -> "RepoContext":
        schema_path = os.path.join(root, "compiler", "schema", "policy.schema.json")
        catalog_path = os.path.join(root, "catalog", "catalog.json")
        with open(schema_path, encoding="utf-8") as f:
            schema = json.load(f)
        # utf-8-sig: the catalog may carry a BOM (Windows PowerShell writes one).
        with open(catalog_path, encoding="utf-8-sig") as f:
            catalog = json.load(f)

        policies: List[PolicyDoc] = []
        pol_dir = os.path.join(root, "policies")
        for path in sorted(glob.glob(os.path.join(pol_dir, "*.yaml")) + glob.glob(os.path.join(pol_dir, "*.yml"))):
            with open(path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            if not raw:
                continue  # skip empty placeholder files
            policies.append(PolicyDoc(name=raw.get("name", os.path.basename(path)), path=path, raw=raw))

        arch_dir = os.path.join(root, "archetypes")
        archetypes = sorted(
            os.path.splitext(os.path.basename(p))[0]
            for p in glob.glob(os.path.join(arch_dir, "*.yaml")) + glob.glob(os.path.join(arch_dir, "*.yml"))
        )
        return cls(root=root, schema=schema, catalog=catalog, policies=policies, archetypes=archetypes)
