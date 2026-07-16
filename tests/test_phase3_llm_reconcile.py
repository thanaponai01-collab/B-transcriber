"""Phase 3 — LLM reconciler tiebreak (local Ollama, no external API).

Run: python -m pytest tests/test_phase3_llm_reconcile.py -v
"""

import json
from urllib.error import URLError

import pytest


class _FixedRand:
    """Stub matching random.Random's `.random()` interface, for deterministic
    slot-assignment tests (see make_llm_fn's position randomization)."""
    def __init__(self, value: float):
        self._value = value

    def random(self) -> float:
        return self._value


# ── llm_reconcile: prompt/parse helpers, no network ────────────────────────

def test_build_prompt_includes_bias_terms():
    from transcribe.pipeline.llm_reconcile import _build_prompt

    prompt = _build_prompt("ครับ", "คะ", ["สวัสดี"])
    assert "ครับ" in prompt and "คะ" in prompt
    assert "สวัสดี" in prompt


def test_build_prompt_no_bias_line_when_empty():
    from transcribe.pipeline.llm_reconcile import _build_prompt

    prompt = _build_prompt("hello", "halo", [])
    assert "Known correct terms" not in prompt


def test_build_prompt_does_not_claim_single_word():
    """2026-07-16 regression: the old prompt said 'disagree on one word' while
    tokens are actually full phrase cues (5.4) — a stale framing that misled
    a weak local model. Candidates are segment-level, and the prompt must say so."""
    from transcribe.pipeline.llm_reconcile import _build_prompt

    prompt = _build_prompt("วันนี้อากาศดีมากเลยครับ", "some other candidate sentence", [])
    assert "one word" not in prompt.lower()
    assert "segment" in prompt.lower() or "phrase" in prompt.lower() or "sentence" in prompt.lower()


@pytest.mark.parametrize("reply,expected", [
    ("0", 0),
    ("1", 1),
    (" 1 \n", 1),
    ("0 (Engine A is correct)", 0),
])
def test_parse_index_accepts_valid_replies(reply, expected):
    from transcribe.pipeline.llm_reconcile import _parse_index
    assert _parse_index(reply) == expected


def test_parse_index_rejects_junk():
    from transcribe.pipeline.llm_reconcile import _parse_index
    with pytest.raises(ValueError):
        _parse_index("I'm not sure, maybe engine A?")


# ── make_llm_fn: network call mocked out ───────────────────────────────────

def test_make_llm_fn_posts_to_configured_host(monkeypatch):
    from transcribe.contracts import RecognizedToken
    from transcribe.pipeline import llm_reconcile

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return json.dumps({"response": "1"}).encode("utf-8")

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(llm_reconcile.urllib.request, "urlopen", fake_urlopen)

    # rand=_FixedRand(0.9) forces no position swap (0.9 >= 0.5), so this test's
    # slot-0/slot-1 mapping is deterministic: slot 0 == ta, slot 1 == tb.
    llm_fn = llm_reconcile.make_llm_fn(
        {"host": "http://localhost:11434", "model": "qwen2.5:7b-instruct", "timeout_s": 5},
        rand=_FixedRand(0.9),
    )
    ta = RecognizedToken("ครับ", 0, 500, 0.9, "thai")
    tb = RecognizedToken("คะ", 0, 500, 0.8, "thai")
    idx = llm_fn(ta, tb, [])

    assert idx == 1
    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["body"]["model"] == "qwen2.5:7b-instruct"
    assert captured["timeout"] == 5


def test_make_llm_fn_position_randomization_swaps_and_maps_back(monkeypatch):
    """2026-07-16 fix: qwen2.5:3b-instruct picked slot 0 on 11/11 real
    disagreements under a FIXED ta=slot-0 mapping — not credible as genuine
    judgment. make_llm_fn now randomizes which of (ta, tb) lands in which
    prompt slot per call, and must translate the model's slot answer back to
    the correct token. Verify both the swap and no-swap mappings directly."""
    from transcribe.contracts import RecognizedToken
    from transcribe.pipeline import llm_reconcile

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return json.dumps({"response": "1"}).encode("utf-8")  # model always answers slot 1

    def fake_urlopen(req, timeout=None):
        captured["prompt"] = json.loads(req.data.decode("utf-8"))["prompt"]
        return FakeResponse()

    monkeypatch.setattr(llm_reconcile.urllib.request, "urlopen", fake_urlopen)

    ta = RecognizedToken("AAA_TEXT", 0, 500, None, "latin")
    tb = RecognizedToken("BBB_TEXT", 0, 500, None, "latin")

    # No swap (rand >= 0.5): slot 0 = ta, slot 1 = tb. Model says slot 1 -> tb -> idx 1.
    no_swap_fn = llm_reconcile.make_llm_fn(
        {"host": "http://localhost:11434", "model": "m"}, rand=_FixedRand(0.9),
    )
    idx_no_swap = no_swap_fn(ta, tb, [])
    assert idx_no_swap == 1
    assert captured["prompt"].index("AAA_TEXT") < captured["prompt"].index("BBB_TEXT")

    # Swap (rand < 0.5): slot 0 = tb, slot 1 = ta. Model still says slot 1 -> ta -> idx 0.
    swap_fn = llm_reconcile.make_llm_fn(
        {"host": "http://localhost:11434", "model": "m"}, rand=_FixedRand(0.1),
    )
    idx_swap = swap_fn(ta, tb, [])
    assert idx_swap == 0
    assert captured["prompt"].index("BBB_TEXT") < captured["prompt"].index("AAA_TEXT")


def test_llm_fn_failure_falls_back_to_script(monkeypatch):
    """reconcile._pick() must catch a network failure from llm_fn and fall back —
    this is what lets llm_enabled: true degrade gracefully when Ollama isn't running."""
    from transcribe.contracts import RecognizedToken
    from transcribe.pipeline.align_hyp import AlignSlot
    from transcribe.pipeline.reconcile import reconcile

    def broken_llm(ta, tb, bias):
        raise URLError("Ollama not running")

    slot = AlignSlot(
        candidates_a=[RecognizedToken("ครับ", 0, 500, 0.9, "thai")],
        candidates_b=[RecognizedToken("คะ", 0, 500, 0.8, "thai")],
    )
    results = reconcile([slot], llm_fn=broken_llm)
    # Falls to _script_fallback: confidence differs (0.9 vs 0.8) → picks A.
    assert results[0][0].text == "ครับ"
    assert results[0][1] == "a"


# ── _script_fallback: confidence-first fix (the circularity the doc flags) ─

def test_script_fallback_prefers_confidence_over_script():
    from transcribe.contracts import RecognizedToken
    from transcribe.pipeline.reconcile import _script_fallback

    # Both Thai script, but B is far more confident — confidence should win,
    # not A's self-reported script (the old circular behavior always picked A).
    ta = RecognizedToken("ครับ", 0, 500, 0.3, "thai")
    tb = RecognizedToken("ค่ะ", 0, 500, 0.95, "thai")
    chosen, source = _script_fallback(ta, tb)
    assert source == "b"
    assert chosen.text == "ค่ะ"


def test_script_fallback_uses_script_when_confidence_absent():
    from transcribe.contracts import RecognizedToken
    from transcribe.pipeline.reconcile import _script_fallback

    ta = RecognizedToken("ครับ", 0, 500, None, "thai")
    tb = RecognizedToken("cup", 0, 500, None, "latin")
    chosen, source = _script_fallback(ta, tb)
    assert source == "a"
    assert chosen.text == "ครับ"


# ── run.py wiring: llm_enabled gates whether make_llm_fn is even imported ──

def test_reconciler_disabled_by_default_in_config():
    import yaml
    from pathlib import Path

    cfg = yaml.safe_load(
        (Path(__file__).parent.parent / "transcribe" / "config.yaml").read_text(encoding="utf-8")
    )
    assert cfg["reconciler"]["llm_enabled"] is False
    assert "model" in cfg["reconciler"]["ollama"]
