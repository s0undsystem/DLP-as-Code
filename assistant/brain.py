"""The provider seam: the one place a model plugs in.

`Brain` is the interface every model implementation satisfies — query answering and policy
authoring. Swapping Claude for a local model (or vice versa) is a matter of choosing a
different Brain; nothing else in the assistant changes.

`DryRunBrain` implements the interface while calling NO model. It lets the whole flow —
context assembly -> brain -> draft validation -> (eventually) PR — be wired and tested with
no API key, no cost, and no network. It emits a real, schema-valid, resolvable draft so that
`validator.validate_draft` passes on its output, proving the plumbing end to end.

The model-backed implementations live in `backends.py` (LocalBrain, ClaudeBrain), not here:
this module defines the contract, that one satisfies it. Both flow into the exact same
AuthorResult / query-string contract used below.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

from .context import RepoContext


@dataclass
class AuthorResult:
    """A brain's response to an authoring request.

    Exactly one of `yaml_text` or `follow_up_question` is meaningful: the brain either drafts a
    policy or asks the one clarifying question it needs (e.g. scope) before it can. `rationale`
    is human-facing explanation to include in the PR body / issue comment.
    """
    yaml_text: Optional[str] = None
    follow_up_question: Optional[str] = None
    rationale: str = ""
    references_used: List[str] = field(default_factory=list)  # SIT/label/group names the draft relies on

    @property
    def needs_input(self) -> bool:
        return self.yaml_text is None and self.follow_up_question is not None


class Brain(ABC):
    """What any model implementation must provide."""

    @abstractmethod
    def answer_query(self, question: str, ctx: RepoContext) -> str:
        """Layer A: answer a read-only question about current coverage. Returns prose."""

    @abstractmethod
    def author_policy(self, request: str, ctx: RepoContext) -> AuthorResult:
        """Layer B: turn a request into a draft policy, or ask one clarifying question."""


class DryRunBrain(Brain):
    """No-model stub. Deterministic output; proves the pipeline without spending anything."""

    def answer_query(self, question: str, ctx: RepoContext) -> str:
        return (
            "[dry-run brain — no model called]\n"
            f"Question: {question}\n"
            f"Managed policies ({len(ctx.policy_names())}): {', '.join(ctx.policy_names()) or 'none'}\n"
            f"Catalog: {len(ctx.sit_names())} SITs, {len(ctx.label_names())} labels, "
            f"{len(ctx.group_names())} groups.\n"
            "A real brain would search these and answer in prose."
        )

    def author_policy(self, request: str, ctx: RepoContext) -> AuthorResult:
        # Pick references that are guaranteed present so the emitted draft resolves cleanly.
        group = ctx.group_names()[0] if ctx.group_names() else "dlp-pilot-group"
        sit = "ABA Routing Number" if "ABA Routing Number" in ctx.sit_names() else (
            ctx.sit_names()[0] if ctx.sit_names() else "Credit Card Number"
        )
        yaml_text = (
            "# DRY-RUN stub output — no model was called. Safe to discard.\n"
            "name: dlp-DRYRUN-example\n"
            f"description: Dry-run stub for request {request!r}. Not a real policy.\n"
            "mode: TestWithoutNotifications\n"
            "scope:\n"
            f"  group: {group}\n"
            "locations:\n"
            "  exchange: true\n"
            "rules:\n"
            "- name: dlp-DRYRUN-example-rule\n"
            "  detect:\n"
            "    accessScope: NotInOrganization\n"
            "    groups:\n"
            "    - name: Default\n"
            "      sensitiveTypes:\n"
            f"      - name: {sit}\n"
            "        confidence: High\n"
            "  actions:\n"
            "    blockAccess: false\n"
            "    generateIncidentReport: true\n"
        )
        return AuthorResult(
            yaml_text=yaml_text,
            rationale=(
                "Dry-run stub: emitted a simulation-mode, group-scoped Exchange policy using a "
                "known-resolvable SIT so the validator passes. A real brain would infer the "
                "surface, SITs, and scope from the request."
            ),
            references_used=[group, sit],
        )
