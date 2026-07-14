"""Phase 3 — LLM reconciler tiebreak, backed by a local Ollama model.

No external API, no network egress, no per-token billing: this calls a model
served by `ollama serve` on localhost. `reconcile._pick()` already wraps any
call to `llm_fn` in try/except and falls back to `_script_fallback` on
failure, so this module raises freely on bad input/output instead of hiding
errors — a silent misparse here would look like a confident decision.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from transcribe.contracts import RecognizedToken

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """Two Thai speech-recognition engines disagree on one word in a transcript.
Engine A heard: "{a_text}"
Engine B heard: "{b_text}"
{bias_line}Reply with exactly one character and nothing else: 0 if Engine A is correct, 1 if Engine B is correct."""


def _build_prompt(ta: RecognizedToken, tb: RecognizedToken, bias_terms: list[str]) -> str:
    bias_line = ""
    if bias_terms:
        bias_line = "Known correct terms/names in this transcript: " + ", ".join(bias_terms[:30]) + "\n"
    return _PROMPT_TEMPLATE.format(a_text=ta.text, b_text=tb.text, bias_line=bias_line)


def _parse_index(reply: str) -> int:
    for ch in reply.strip():
        if ch in ("0", "1"):
            return int(ch)
    raise ValueError(f"Ollama reply had no 0/1 index: {reply!r}")


def make_llm_fn(ollama_cfg: dict):
    """Build a callable(ta, tb, bias_terms) -> int backed by a local Ollama server.

    ollama_cfg is config["reconciler"]["ollama"], e.g.
        {"host": "http://localhost:11434", "model": "qwen2.5:7b-instruct", "timeout_s": 10}
    `model` is required — there's no sane default local model to assume is pulled.
    """
    host = ollama_cfg.get("host", "http://localhost:11434")
    model = ollama_cfg["model"]
    timeout_s = float(ollama_cfg.get("timeout_s", 10))
    url = host.rstrip("/") + "/api/generate"

    def llm_fn(ta: RecognizedToken, tb: RecognizedToken, bias_terms: list[str]) -> int:
        prompt = _build_prompt(ta, tb, bias_terms)
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return _parse_index(body["response"])

    return llm_fn
