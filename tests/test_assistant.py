"""Assistant spine tests: context -> brain -> real-compiler validation. No model, no network.

The assistant is a v2/experimental preview; these tests exercise the model-agnostic plumbing
(context assembly, prompt build/parse, draft validation) using stub/fake brains.
Run with pytest, or directly: python tests/test_assistant.py
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from assistant.backends import ClaudeBrain, LLMBrain, LocalBrain, make_brain
from assistant.brain import DryRunBrain
from assistant.context import RepoContext
from assistant.prompts import (
    Prompt,
    build_authoring_prompt,
    load_examples,
    parse_author_reply,
)
from assistant.validator import STAGE_COMPILE, STAGE_OK, validate_draft

PILOT_GROUP = "dlp-pilot-group"


def test_context_loads_the_repo():
    ctx = RepoContext.load()
    assert len(ctx.policies) >= 1, "expected example policies to load"
    assert ctx.sit_names(), "expected SITs in the catalog"
    assert PILOT_GROUP in ctx.group_names()


def test_dry_run_draft_survives_the_compiler():
    ctx = RepoContext.load()
    result = DryRunBrain().author_policy("block wire-transfer data leaving the org", ctx)
    assert result.yaml_text and not result.needs_input
    verdict = validate_draft(result.yaml_text)
    assert verdict.ok, f"dry-run draft should compile cleanly, got: {verdict.summary()}"
    assert verdict.stage == STAGE_OK
    assert verdict.manifest_entry["mode"] == "TestWithoutNotifications"


def test_unknown_sit_fails_closed():
    draft = (
        "name: dlp-bogus\n"
        "mode: TestWithoutNotifications\n"
        f"scope: {{group: {PILOT_GROUP}}}\n"
        "locations: {exchange: true}\n"
        "rules:\n"
        "- name: r1\n"
        "  detect:\n"
        "    groups:\n"
        "    - name: Default\n"
        "      sensitiveTypes:\n"
        "      - {name: This SIT Does Not Exist}\n"
    )
    verdict = validate_draft(draft)
    assert not verdict.ok and verdict.stage == STAGE_COMPILE
    assert any("not in the catalog" in e for e in verdict.errors)


def test_schema_violation_is_reported():
    draft = "name: dlp-incomplete\nmode: TestWithoutNotifications\nlocations: {exchange: true}\n"
    verdict = validate_draft(draft)
    assert not verdict.ok and verdict.stage == STAGE_COMPILE


def test_query_brain_sees_managed_policies():
    ctx = RepoContext.load()
    answer = DryRunBrain().answer_query("do we cover credit card numbers?", ctx)
    assert str(len(ctx.policy_names())) in answer


def test_golden_examples_compile():
    examples = load_examples()
    assert len(examples) >= 2, "expected at least two golden examples"
    for ex in examples:
        verdict = validate_draft(ex.draft)
        assert verdict.ok, f"golden example for {ex.request!r} must compile: {verdict.summary()}"


def test_system_prompt_carries_schema_catalog_and_examples():
    ctx = RepoContext.load()
    prompt = build_authoring_prompt("block SSNs over email", ctx)
    assert isinstance(prompt, Prompt)
    assert "U.S. Social Security Number (SSN)" in prompt.system  # a catalog SIT name
    assert "$schema" in prompt.system                             # schema embedded
    assert "REQUEST:" in prompt.system                            # few-shot examples embedded
    assert "block SSNs over email" in prompt.user


def test_parse_reply_extracts_fenced_yaml_that_compiles():
    ex = load_examples()[0]
    reply = f"Here is the policy you asked for:\n\n```yaml\n{ex.draft}```\n\nIt runs in simulation."
    result = parse_author_reply(reply)
    assert result.yaml_text and not result.needs_input
    assert validate_draft(result.yaml_text).ok


def test_parse_reply_detects_follow_up_question():
    result = parse_author_reply("QUESTION: which group should this be scoped to?")
    assert result.needs_input
    assert "group" in result.follow_up_question.lower()


def test_fake_backend_runs_the_shared_path_end_to_end():
    class FakeBrain(LLMBrain):
        def _complete(self, prompt):
            return f"```yaml\n{load_examples()[0].draft}```"

    ctx = RepoContext.load()
    result = FakeBrain().author_policy("block external card data", ctx)
    assert result.yaml_text and validate_draft(result.yaml_text).ok


def test_make_brain_selects_backends():
    assert isinstance(make_brain("dry-run"), DryRunBrain)
    assert isinstance(make_brain("claude"), ClaudeBrain)
    assert isinstance(make_brain("local", base_url="http://x/v1", model="m"), LocalBrain)


def test_eval_scores_backends_correctly():
    from assistant.brain import AuthorResult, Brain
    from assistant.eval import format_report, run_eval

    ctx = RepoContext.load()

    class GoodBrain(LLMBrain):
        def _complete(self, prompt):
            return f"```yaml\n{load_examples()[0].draft}```"

    class JunkBrain(LLMBrain):
        def _complete(self, prompt):
            return "```yaml\nname: nope\n```"

    class AskBrain(Brain):
        def answer_query(self, q, ctx):
            return ""

        def author_policy(self, req, ctx):
            return AuthorResult(follow_up_question="which group?")

    good = run_eval(GoodBrain(), ctx)
    assert good and all(r.ok for r in good)
    junk = run_eval(JunkBrain(), ctx)
    assert junk and all(r.produced_draft and not r.ok for r in junk)
    ask = run_eval(AskBrain(), ctx)
    assert ask and all(not r.produced_draft and r.stage == "asked_question" for r in ask)
    assert "compiled" in format_report(good)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
