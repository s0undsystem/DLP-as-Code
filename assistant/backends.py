# Copyright 2026 Jared Medeiros
# SPDX-License-Identifier: Apache-2.0
# Part of DLPaC (https://github.com/s0undsystem/DLP-as-Code). See NOTICE.

"""Concrete brains. Each is a thin adapter over the shared prompt/parse layer in prompts.py.

The only thing that differs between backends is `_complete(prompt) -> str`: send the prompt to
a model, return its text. Everything else — building the prompt from the catalog, parsing the
reply into an AuthorResult — is shared. That is why "use Claude or use a local model" is a
config flip (`make_brain`), not a rewrite.

  LocalBrain   any OpenAI-compatible endpoint (Ollama, LM Studio, vLLM). No API key, runs on
               your own hardware.
  ClaudeBrain  the Anthropic API. Bring your own ANTHROPIC_API_KEY.
  DryRunBrain  no model at all (in brain.py) — deterministic, for wiring and tests.

NOTE (v2 / experimental): the natural-language assistant is under active development. The
compiler/DSL/deploy layer is the stable core; treat the assistant as a preview.
"""
import json
import os
import urllib.request
from typing import Optional

from .brain import AuthorResult, Brain, DryRunBrain
from .context import RepoContext
from .prompts import Prompt, build_authoring_prompt, build_query_prompt, parse_author_reply


class LLMBrain(Brain):
    """Base for any real model: build prompt -> _complete -> parse. Subclasses supply _complete."""

    def answer_query(self, question: str, ctx: RepoContext) -> str:
        return self._complete(build_query_prompt(question, ctx))

    def author_policy(self, request: str, ctx: RepoContext) -> AuthorResult:
        return parse_author_reply(self._complete(build_authoring_prompt(request, ctx)))

    def _complete(self, prompt: Prompt) -> str:  # pragma: no cover - abstract
        raise NotImplementedError


class LocalBrain(LLMBrain):
    """OpenAI-compatible chat completions (Ollama `/v1`, LM Studio, vLLM, ...). Stdlib only.

    Example: LocalBrain(base_url="http://localhost:11434/v1", model="qwen2.5-coder:14b").
    """

    def __init__(self, base_url: str, model: str, api_key: Optional[str] = None, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def _complete(self, prompt: Prompt) -> str:
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            "temperature": 0,
            "stream": False,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (trusted, config'd URL)
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


# Default Anthropic model, overridable per call or via DLPAC_CLAUDE_MODEL. Named here so the
# default lives in exactly one place: model lineups move, and an ID pinned in several spots
# goes stale in some of them.
DEFAULT_CLAUDE_MODEL = "claude-opus-5"


class ClaudeBrain(LLMBrain):
    """Anthropic API backend. Requires `pip install anthropic` and an ANTHROPIC_API_KEY.

    Uses adaptive thinking. The model defaults to DEFAULT_CLAUDE_MODEL and can be overridden
    by passing `model=`, or by setting DLPAC_CLAUDE_MODEL when constructed via make_brain.
    Which models an account can reach depends on the API access it has been granted, so
    anything the account cannot use needs the override rather than a code change.
    """

    def __init__(self, model: str = DEFAULT_CLAUDE_MODEL, max_tokens: int = 16000):
        self.model = model
        self.max_tokens = max_tokens

    def _complete(self, prompt: Prompt) -> str:
        try:
            import anthropic
        except ImportError as e:  # keep anthropic an optional dependency
            raise RuntimeError(
                "ClaudeBrain requires the 'anthropic' package: pip install anthropic"
            ) from e
        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
        msg = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            thinking={"type": "adaptive"},
            system=prompt.system,
            messages=[{"role": "user", "content": prompt.user}],
        )
        return next((b.text for b in msg.content if b.type == "text"), "")


def make_brain(kind: Optional[str] = None, **cfg) -> Brain:
    """Select a backend by name. Defaults to $DLPAC_BRAIN, then 'dry-run'.

    kinds: 'dry-run' (no model), 'local' (base_url, model, api_key?), 'claude' (model?).
    """
    kind = (kind or os.getenv("DLPAC_BRAIN") or "dry-run").lower()
    if kind == "dry-run":
        return DryRunBrain()
    if kind == "local":
        return LocalBrain(
            base_url=cfg.get("base_url") or os.environ["DLPAC_LOCAL_BASE_URL"],
            model=cfg.get("model") or os.environ["DLPAC_LOCAL_MODEL"],
            api_key=cfg.get("api_key") or os.getenv("DLPAC_LOCAL_API_KEY"),
        )
    if kind == "claude":
        return ClaudeBrain(
            model=cfg.get("model") or os.getenv("DLPAC_CLAUDE_MODEL") or DEFAULT_CLAUDE_MODEL
        )
    raise ValueError(f"unknown brain kind: {kind!r} (expected dry-run | local | claude)")
