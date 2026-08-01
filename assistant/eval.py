# Copyright 2026 Jared Medeiros
# SPDX-License-Identifier: Apache-2.0
# Part of DLPaC (https://github.com/s0undsystem/DLP-as-Code). See NOTICE.

"""Measure whether a brain can actually author policies — run requests, compile the drafts.

Point this at any brain (local model, dry-run, later Claude) and it runs each golden-example
request through `author_policy` and pushes the result through the REAL compiler. It reports:

  * compile rate  — of the drafts produced, how many survive schema + fail-closed resolution
  * asked         — requests where the brain asked a clarifying question instead of drafting
  * failures      — with the stage + error, so you can see WHY a model's draft was rejected

Compile rate measures FORM (does it deploy), not INTENT (does it match the ask) — the drafts are
printed so a human can eyeball intent. This is how you decide if a local model is good enough for
authoring before standing up any hosting.

    DLPAC_BRAIN=local DLPAC_LOCAL_BASE_URL=http://localhost:11434/v1 \
        DLPAC_LOCAL_MODEL=qwen2.5-coder:14b .venv/bin/python -m assistant.eval
"""
import argparse
import sys
from dataclasses import dataclass
from typing import List, Optional

from .backends import make_brain
from .brain import Brain
from .context import RepoContext
from .prompts import load_examples
from .validator import validate_draft


@dataclass
class EvalRow:
    request: str
    produced_draft: bool
    ok: bool
    stage: str
    detail: str
    draft: Optional[str] = None


def run_eval(brain: Brain, ctx: RepoContext, requests: Optional[List[str]] = None) -> List[EvalRow]:
    reqs = requests if requests is not None else [ex.request for ex in load_examples()]
    rows: List[EvalRow] = []
    for req in reqs:
        result = brain.author_policy(req, ctx)
        if result.needs_input:
            rows.append(EvalRow(req, produced_draft=False, ok=False,
                                stage="asked_question", detail=result.follow_up_question or ""))
            continue
        verdict = validate_draft(result.yaml_text or "")
        rows.append(EvalRow(
            req, produced_draft=True, ok=verdict.ok, stage=verdict.stage,
            detail="" if verdict.ok else "; ".join(verdict.errors),
            draft=result.yaml_text,
        ))
    return rows


def format_report(rows: List[EvalRow], show_drafts: bool = False) -> str:
    drafted = [r for r in rows if r.produced_draft]
    compiled = [r for r in drafted if r.ok]
    asked = [r for r in rows if not r.produced_draft]
    lines = ["=== DLPaC authoring eval ==="]
    for r in rows:
        mark = "PASS" if r.ok else ("ASK " if not r.produced_draft else "FAIL")
        lines.append(f"[{mark}] {r.request}")
        if r.detail:
            lines.append(f"        {r.stage}: {r.detail}")
        if show_drafts and r.draft:
            lines.append("        --- draft ---")
            lines.extend("        " + ln for ln in r.draft.rstrip().splitlines())
    rate = (len(compiled) / len(drafted) * 100) if drafted else 0.0
    lines.append("")
    lines.append(f"compiled {len(compiled)}/{len(drafted)} drafts ({rate:.0f}%); "
                 f"{len(asked)} asked a question; {len(rows)} requests total")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate a brain's authoring compile-rate.")
    ap.add_argument("--brain", default=None, help="dry-run | local | claude (default: $DLPAC_BRAIN)")
    ap.add_argument("--show-drafts", action="store_true", help="print each produced draft")
    args = ap.parse_args(argv)

    brain = make_brain(args.brain)
    ctx = RepoContext.load()
    rows = run_eval(brain, ctx)
    print(format_report(rows, show_drafts=args.show_drafts))
    # Non-zero exit if any produced draft failed to compile (useful as a CI gate later).
    return 1 if any(r.produced_draft and not r.ok for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
