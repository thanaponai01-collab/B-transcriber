"""Phase 3 — LLM reconciler tiebreak, backed by a local Ollama model.

No external API, no network egress, no per-token billing: this calls a model
served by `ollama serve` on localhost. `reconcile._pick()` already wraps any
call to `llm_fn` in try/except and falls back to `_script_fallback` on
failure, so this module raises freely on bad input/output instead of hiding
errors — a silent misparse here would look like a confident decision.

2026-07-16 fix: two defects found by instrumenting real disagreements.
(1) The prompt said "disagree on one word" — stale since tokens became
phrase cues (5.4); the model was shown two full sentences while told to
expect one word. Rewritten below to describe segment-level candidates.
(2) With a fixed ta=slot-0 / tb=slot-1 mapping, qwen2.5:3b-instruct picked
slot 0 on 11 of 11 real disagreements — not credible as genuine judgment.
`make_llm_fn` now randomizes, per call, which of (ta, tb) is shown in which
prompt slot, and translates the model's slot choice back to ta/tb — a model
with real positional bias then decorrelates from actual accuracy (~50/50
"wrong" by construction) instead of silently, deterministically favoring one
engine every time. This doesn't fix a biased model; it makes the bias show
up as noise instead of a systematic Engine-A advantage, and — critically —
makes the bias measurable (see TODO_LEDGER.md for the before/after probe).
"""

from __future__ import annotations

import json
import logging
import random
import urllib.error
import urllib.request

from transcribe.contracts import RecognizedToken

logger = logging.getLogger(__name__)

# Slots are neutrally labelled "Candidate 0"/"Candidate 1", never "Engine
# A"/"Engine B" — a model can carry a first-position or "A"-reads-as-primary
# bias independent of which engine actually produced the text, and the whole
# point of randomizing slot assignment (below) is to decorrelate the model's
# answer from prompt position. The candidates are explicitly framed as a
# spoken segment, not a single word, matching actual phrase-cue granularity.
_PROMPT_TEMPLATE = """Two automatic-speech-recognition engines produced different transcriptions of the same spoken Thai segment (a phrase or sentence, not a single word). Decide which candidate more accurately reflects what was actually said.
Candidate 0: "{text0}"
Candidate 1: "{text1}"
{bias_line}Reply with exactly one character and nothing else: 0 if Candidate 0 is more accurate, 1 if Candidate 1 is more accurate."""


def _build_prompt(text0: str, text1: str, bias_terms: list[str]) -> str:
    bias_line = ""
    if bias_terms:
        bias_line = "Known correct terms/names in this transcript: " + ", ".join(bias_terms[:30]) + "\n"
    return _PROMPT_TEMPLATE.format(text0=text0, text1=text1, bias_line=bias_line)


def _parse_index(reply: str) -> int:
    """The candidate SLOT (0 or 1) the model chose — not yet mapped back to
    ta/tb. That mapping happens in llm_fn, after undoing the position swap."""
    for ch in reply.strip():
        if ch in ("0", "1"):
            return int(ch)
    raise ValueError(f"Ollama reply had no 0/1 index: {reply!r}")


def make_llm_fn(ollama_cfg: dict, rand: random.Random | None = None):
    """Build a callable(ta, tb, bias_terms) -> int backed by a local Ollama server.

    ollama_cfg is config["reconciler"]["ollama"], e.g.
        {"host": "http://localhost:11434", "model": "qwen2.5:7b-instruct", "timeout_s": 10}
    `model` is required — there's no sane default local model to assume is pulled.

    `rand`: source of randomness for per-call slot assignment (needs only a
    `.random() -> float` method, matching `random.Random`/the `random` module
    itself). Injectable for deterministic tests; defaults to the module-level
    `random`. The returned callable's contract is unchanged: 0 picks ta,
    1 picks tb — the slot randomization is entirely internal.
    """
    host = ollama_cfg.get("host", "http://localhost:11434")
    model = ollama_cfg["model"]
    timeout_s = float(ollama_cfg.get("timeout_s", 10))
    url = host.rstrip("/") + "/api/generate"
    rand = rand if rand is not None else random

    def llm_fn(ta: RecognizedToken, tb: RecognizedToken, bias_terms: list[str]) -> int:
        swap = rand.random() < 0.5
        text0, text1 = (tb.text, ta.text) if swap else (ta.text, tb.text)
        prompt = _build_prompt(text0, text1, bias_terms)
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
        slot_idx = _parse_index(body["response"])
        # Undo the swap: slot 0/1 maps to whichever of ta/tb was placed there.
        return (1 - slot_idx) if swap else slot_idx

    return llm_fn
