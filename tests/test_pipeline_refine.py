"""transcribe/pipeline/refine.py — post-decode token refinement, addressed directly.

Two hypothesis token lists in, final PipelineTokens out. Synthetic tokens, a
synthetic audio array, and an injected aligner — no engine, no database, no GPU.
Before this seam existed, asserting that the silence filter or the cue conform
ran at all meant driving the whole pipeline from a temp WAV file.

Run: python -m pytest tests/test_pipeline_refine.py -v
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.contracts import RecognizedToken
from transcribe.pipeline import refine
from transcribe.pipeline.align_force import LinearFallbackAligner
from transcribe.pipeline.engine_run import Hypotheses

_SR = 16000
_AUDIO = np.zeros(10 * _SR, dtype=np.float32)   # 10s of silence; only its length matters


def _tok(text, start_ms, end_ms, script="latin", confidence=0.9):
    return RecognizedToken(text, start_ms, end_ms, confidence, script)


def _run(tokens_a, tokens_b=None, *, timestamps_final=True, config=None, silence_spans=(),
         aligner=None, on_reconciled=None):
    return refine.refine(
        Hypotheses(tokens_a=tokens_a,
                   timestamps_final_a=timestamps_final,
                   tokens_b=tokens_b if tokens_b is not None else []),
        config=config if config is not None else {"drop_tokens_over_silence": False},
        bias_terms=[],
        silence_spans=list(silence_spans),
        audio=_AUDIO,
        sample_rate=_SR,
        aligner=aligner if aligner is not None else LinearFallbackAligner(),
        on_reconciled=on_reconciled,
    )


# ── the select-only invariant survives the seam ─────────────────────────────

def test_refinement_never_invents_text():
    """test_smoke.py::test_reconciler_no_generation's invariant, restated on the
    seam that now owns the reconcile call: every output token's text came from
    one of the two hypotheses."""
    a = [_tok("hello", 0, 500), _tok("world", 500, 1000)]
    b = [_tok("hallo", 0, 500), _tok("word", 500, 1000)]
    out = _run(a, b)
    candidates = {t.text for t in a} | {t.text for t in b}
    assert out, "refinement must produce tokens"
    for t in out:
        assert t.text in candidates, f"invented text: {t.text!r}"


def test_single_hypothesis_passes_through():
    out = _run([_tok("hello", 0, 500)])
    assert [t.text for t in out] == ["hello"]


def test_empty_hypotheses_produce_no_tokens():
    assert _run([], []) == []


# ── the phase-advance hook fires exactly once, at reconciliation ────────────

def test_on_reconciled_is_called_once():
    calls = []
    _run([_tok("hello", 0, 500)], on_reconciled=lambda: calls.append(1))
    assert calls == [1]


def test_on_reconciled_is_optional():
    _run([_tok("hello", 0, 500)], on_reconciled=None)  # must not raise


# ── hallucination filtering ─────────────────────────────────────────────────

def test_repeated_tokens_beyond_the_run_limit_are_dropped():
    tokens = [_tok("um", i * 100, i * 100 + 100) for i in range(8)]
    out = _run(tokens)
    assert len(out) < len(tokens), "a run of 8 identical tokens must be trimmed"


def test_a_looped_token_is_collapsed_in_place():
    out = _run([_tok("wwwww", 0, 500)])
    assert [t.text for t in out] == ["w"]


def test_a_number_that_looks_like_a_loop_is_left_alone():
    out = _run([_tok("2000", 0, 500)])
    assert [t.text for t in out] == ["2000"]


# ── the silence filter is opt-out, and off by default here ──────────────────

def test_silence_filter_drops_a_low_confidence_token_over_vad_silence():
    out = _run(
        [_tok("ghost", 1000, 2000, confidence=0.1)],
        config={"drop_tokens_over_silence": True, "silence_drop_max_confidence": 0.5},
        silence_spans=[(900, 2100)],
    )
    assert out == []


def test_silence_filter_keeps_a_confident_token():
    out = _run(
        [_tok("real", 1000, 2000, confidence=0.99)],
        config={"drop_tokens_over_silence": True, "silence_drop_max_confidence": 0.5},
        silence_spans=[(900, 2100)],
    )
    assert [t.text for t in out] == ["real"]


def test_silence_filter_can_be_disabled():
    out = _run(
        [_tok("ghost", 1000, 2000, confidence=0.1)],
        config={"drop_tokens_over_silence": False},
        silence_spans=[(900, 2100)],
    )
    assert [t.text for t in out] == ["ghost"]


# ── forced alignment is conditional on the engine's own timestamps ──────────

class _RecordingAligner(LinearFallbackAligner):
    def __init__(self):
        self.calls = 0

    def align(self, audio, sr, words):
        self.calls += 1
        return super().align(audio, sr, words)


def test_final_timestamps_skip_word_expansion_and_forced_alignment():
    aligner = _RecordingAligner()
    out = _run([_tok("hello world", 0, 1000)], timestamps_final=True, aligner=aligner)
    assert aligner.calls == 0, "an engine reporting final timestamps must not be re-aligned"
    assert [t.text for t in out] == ["hello world"], "no word expansion either"


def test_non_final_timestamps_expand_to_words_and_force_align():
    aligner = _RecordingAligner()
    out = _run([_tok("hello world", 0, 1000)], timestamps_final=False, aligner=aligner)
    assert aligner.calls == 1
    assert [t.text for t in out] == ["hello", "world"]


# ── cue conform runs on EVERY path, including the timestamps_final one ──────

def test_overlapping_cues_are_conformed_even_when_forced_alignment_is_skipped():
    """The regression this guards: the aligner used to be the only place the
    no-overlap invariant was enforced, so on the active whole-file engine path it
    was enforced nowhere and overlapping cues reached the exported SRT."""
    out = _run([_tok("first", 0, 3000), _tok("second", 1000, 4000)], timestamps_final=True)
    assert len(out) == 2
    assert out[0].end_ms <= out[1].start_ms, f"cues still overlap: {[(t.start_ms, t.end_ms) for t in out]}"


def test_cues_are_clamped_to_the_audio_duration():
    out = _run([_tok("runaway", 0, 999_000)], timestamps_final=True)
    duration_ms = int(len(_AUDIO) * 1000 / _SR)
    assert out[0].end_ms <= duration_ms


def test_token_indices_are_contiguous_from_zero():
    out = _run([_tok("a", 0, 100), _tok("b", 200, 300), _tok("c", 400, 500)])
    assert [t.idx for t in out] == list(range(len(out)))
