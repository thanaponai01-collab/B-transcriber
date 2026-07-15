"""Cue target width is config-driven (engines.faster_whisper.cue_target_chars).

_CUE_TARGET_CHARS was hardcoded next to cue_gap_ms/cue_max_ms, which ARE
config-driven. Same 2.3 discipline: a subtitle-line-width change is a YAML
edit, never a code edit. Mirrors the test_phase2_config.py override pattern
(constructor kwargs) plus a capture test proving the value reaches
_group_words_into_cues.

Run: python -m pytest tests/test_cue_target_chars_config.py -v
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

import transcribe.engines.faster_whisper as fw
from transcribe.contracts import EngineInput
from transcribe.engines.registry import get_engine


def test_constructor_accepts_cue_target_chars_override():
    eng = get_engine("faster_whisper", device="cpu", cue_target_chars=28)
    assert eng._cue_target_chars == 28


def test_constructor_default_matches_module_constant():
    eng = get_engine("faster_whisper", device="cpu")
    assert eng._cue_target_chars == fw._CUE_TARGET_CHARS == 42


def test_cue_target_chars_reaches_grouping(monkeypatch):
    """transcribe() must pass the configured width into _group_words_into_cues —
    a stored-but-unused kwarg would be dead config."""
    eng = get_engine("faster_whisper", device="cpu", cue_target_chars=10)

    captured = {}

    def fake_group(words, gap_ms, target_ms, target_chars):
        captured["target_chars"] = target_chars
        return [("สวัสดี", 0, 500, 0.9)]

    monkeypatch.setattr(fw, "_group_words_into_cues", fake_group)
    monkeypatch.setattr(
        eng, "_transcribe_batched",
        lambda audio, hint, prompt: [("สวัสดี", 0, 500, 0.9)],
    )
    eng._model = object()  # satisfy the load() assertion without a GPU

    res = eng.transcribe(EngineInput(audio=np.zeros(1600, dtype=np.float32)))
    assert captured["target_chars"] == 10
    assert res.tokens and res.tokens[0].text == "สวัสดี"


def test_smaller_target_chars_produces_shorter_cues():
    """Functional: shrinking the width really closes cues earlier."""
    # Continuous Latin words, no gaps/sentence breaks, well under target_ms.
    words = [(f"word{i} ", i * 300, i * 300 + 250, 0.9) for i in range(8)]
    wide = fw._group_words_into_cues(words, gap_ms=700, target_ms=60000, target_chars=200)
    narrow = fw._group_words_into_cues(words, gap_ms=700, target_ms=60000, target_chars=12)
    assert len(narrow) > len(wide)
    assert all(len(text) <= 12 + len("word0 ") for text, *_ in narrow), (
        "a cue may overshoot by at most the word that closed it"
    )
