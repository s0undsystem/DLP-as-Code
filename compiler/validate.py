"""Validate a (post-archetype-merge) policy dict against the DLP DSL JSON Schema."""
import json
import os

from jsonschema import Draft202012Validator

DEFAULT_SCHEMA = os.path.join(os.path.dirname(__file__), "schema", "policy.schema.json")


def load_schema(path=None):
    path = path or DEFAULT_SCHEMA
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_policy(policy, schema=None):
    """Raise ValueError with all schema violations if the policy is invalid."""
    schema = schema or load_schema()
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(policy), key=lambda e: list(e.path))
    if errors:
        lines = []
        for e in errors:
            loc = "/".join(str(p) for p in e.path) or "(root)"
            lines.append(f"  at {loc}: {e.message}")
        raise ValueError(
            f"Policy '{policy.get('name', '(unnamed)')}' failed schema validation:\n"
            + "\n".join(lines)
        )
