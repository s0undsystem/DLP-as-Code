# Copyright 2026 Jared Medeiros
# SPDX-License-Identifier: Apache-2.0
# Part of DLPaC (https://github.com/s0undsystem/DLP-as-Code). See NOTICE.

"""Backend-agnostic prompt assembly and reply parsing — the shared ~90% of any real brain.

Nothing here knows or cares which model runs. `build_authoring_prompt` / `build_query_prompt`
turn a RepoContext + request into a provider-neutral `Prompt` (system + user text); a backend
maps that onto its own API. `parse_author_reply` turns the model's text back into an
`AuthorResult`. Claude and a local model share every line of this — only the network call differs.
"""
import glob
import json
import os
import re
from dataclasses import dataclass
from typing import Dict, List

import yaml

from .brain import AuthorResult
from .context import RepoContext

_EXAMPLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples")


@dataclass
class Prompt:
    """Provider-neutral prompt. Each backend maps these two strings onto its own API shape."""
    system: str
    user: str


@dataclass
class Example:
    request: str
    draft: str
    notes: str = ""


def load_examples() -> List[Example]:
    out: List[Example] = []
    for path in sorted(glob.glob(os.path.join(_EXAMPLES_DIR, "*.yaml"))):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if data.get("request") and data.get("draft"):
            out.append(Example(request=data["request"], draft=data["draft"], notes=data.get("notes", "")))
    return out


# --- hard rules the assistant must obey; enforced downstream, stated here so the model complies ---
_RULES = """\
Non-negotiable rules:
1. SIMULATION FIRST. `mode` must be TestWithoutNotifications or TestWithNotifications. NEVER
   author `mode: Enable` — enforcement is a separate, human-gated step.
2. ALWAYS SCOPE A DRAFT. Every policy you author must set `scope.group` (or `scope.users` for
   Copilot). Never draft an org-wide policy. The compiler permits org-wide, because it is a
   legitimate end state a human may choose deliberately, and warns when a policy compiles that
   way. It is not a choice you get to make on someone's behalf: if the request seems to call for
   org-wide coverage, ask a QUESTION instead of drafting it.
3. USE ONLY CATALOG NAMES. Every sensitive-info-type, label, group, and site name must appear
   verbatim in the catalog provided below. If the right reference is not in the catalog, do not
   invent one — ask a QUESTION instead.
4. A human reviews and merges every change via pull request. You draft; you never deploy.
"""

_OUTPUT_CONTRACT = """\
Respond in ONE of exactly two forms:
  A) A single fenced ```yaml block containing exactly one policy document and nothing else, OR
  B) A single line beginning `QUESTION:` followed by the one clarification you need (most often
     which group/users to scope to, or which surface). Ask only when you genuinely cannot proceed.
"""


def _catalog_block(ctx: RepoContext) -> str:
    return (
        "Available sensitive-info-type names (use verbatim):\n"
        + json.dumps(ctx.sit_names(), indent=0)
        + "\n\nAvailable sensitivity-label names:\n" + json.dumps(ctx.label_names(), indent=0)
        + "\n\nAvailable group names:\n" + json.dumps(ctx.group_names(), indent=0)
        + "\n\nAvailable SharePoint site names:\n" + json.dumps(ctx.site_names(), indent=0)
    )


def _examples_block() -> str:
    parts = []
    for ex in load_examples():
        parts.append(f"REQUEST: {ex.request}\nDRAFT:\n```yaml\n{ex.draft.rstrip()}\n```")
    return "\n\n".join(parts)


def build_system_prompt(ctx: RepoContext) -> str:
    return (
        "You are the DLPaC authoring assistant. You turn plain-English requests into Microsoft "
        "Purview DLP policies expressed in this repo's YAML DSL. Your drafts are validated by a "
        "compiler and reviewed by a human before anything reaches the tenant.\n\n"
        + _RULES
        + "\nThe DSL JSON Schema (author policies that conform exactly):\n"
        + json.dumps(ctx.schema, indent=2)
        + "\n\n" + _catalog_block(ctx)
        + "\n\nPolicies already under management (avoid duplicating; extend intent instead):\n"
        + json.dumps(ctx.policy_names(), indent=0)
        + "\n\nWorked examples:\n" + _examples_block()
        + "\n\n" + _OUTPUT_CONTRACT
    )


def build_authoring_prompt(request: str, ctx: RepoContext) -> Prompt:
    return Prompt(system=build_system_prompt(ctx), user=f"Author a policy for this request:\n{request}")


def build_query_prompt(question: str, ctx: RepoContext) -> Prompt:
    # Query path is read-only: give the model the managed policies verbatim and ask for prose.
    policies_dump = json.dumps({p.name: p.raw for p in ctx.policies}, indent=2)
    system = (
        "You answer questions about the DLP coverage this repo manages. Answer only from the "
        "policies and catalog provided. Be specific: name the policy, the SITs/labels it matches, "
        "the surface, and the scope. If nothing covers the question, say so plainly.\n\n"
        f"Managed policies:\n{policies_dump}\n\n{_catalog_block(ctx)}"
    )
    return Prompt(system=system, user=question)


_FENCE_RE = re.compile(r"```(?:yaml|yml)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def parse_author_reply(text: str) -> AuthorResult:
    """Turn a model's raw authoring reply into an AuthorResult (draft, or a follow-up question)."""
    m = _FENCE_RE.search(text or "")
    if m:
        return AuthorResult(yaml_text=m.group(1).strip(), rationale=_strip_fence(text).strip())
    q = _extract_question(text or "")
    return AuthorResult(follow_up_question=q or "(model returned neither a draft nor a clear question)")


def _strip_fence(text: str) -> str:
    return _FENCE_RE.sub("", text)


def _extract_question(text: str) -> str:
    for line in text.splitlines():
        if line.strip().upper().startswith("QUESTION:"):
            return line.split(":", 1)[1].strip()
    return text.strip()
