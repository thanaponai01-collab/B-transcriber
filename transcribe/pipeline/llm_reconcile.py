from __future__ import annotations

import json
import logging
import random
import urllib.error
import urllib.request

from transcribe.contracts import RecognizedToken

logger = logging.getLogger(__name__)

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
    for ch in reply.strip():
        if ch in ("0", "1"):
            return int(ch)
    raise ValueError(f"Ollama reply had no 0/1 index: {reply!r}")


def make_llm_fn(ollama_cfg: dict, rand: random.Random | None = None):
    """Build a callable(ta, tb, bias_terms) -> int backed by a local Ollama server.

    ollama_cfg is config["reconciler"]["ollama"], e.g.
        {"host": "http://localhost:11434", "model": "qwen2.5:7b-instruct", "timeout_s": 10}
    `model` is required.

    `rand`: source of randomness for per-call slot assignment (needs only a
    `.random() -> float` method, matching `random.Random`/the `random` module
    itself). Injectable for deterministic tests; defaults to the module-level
    `random`. The returned callable's contract: 0 picks ta,
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
        return (1 - slot_idx) if swap else slot_idx

    return llm_fn
