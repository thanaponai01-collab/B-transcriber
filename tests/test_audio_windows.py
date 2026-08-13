"""transcribe/audio/windows.py — speech windowing through `speech_windows`.

Asserts on the windows that come back: their count, their boundaries, their
overlap. Never on how VAD was invoked. Silero itself is stubbed because it is
an external dependency, not the logic under test — everything downstream of
detection (the zero-gap merge, the over-long split) is exercised for real.

The merge cases are the TODO_LEDGER.md 2026-08-06 incident fix:
faster_whisper.vad.get_speech_timestamps pads real inter-speech silence under
~800ms so it reports as a zero gap between two adjacent VAD spans. Callers used
to treat those as fully independent decodes with no overlap at the seam, and
real content was confirmed lost exactly there on production audio. The merge
closes that seam before any windowing/decoding happens.

Run: python -m pytest tests/test_audio_windows.py -v
"""

import numpy as np
import pytest

import transcribe.audio.windows as windows
from transcribe.audio import Window, WindowPolicy, speech_windows

# Long enough that no test's spans run past the end of the array.
_AUDIO = np.zeros(60 * 16000, dtype=np.float32)


@pytest.fixture
def vad(monkeypatch):
    """Pin what Silero 'detects', so the merge/split steps are what's measured."""
    def _set(spans):
        monkeypatch.setattr(windows, "_vad_speech_spans",
                            lambda audio, threshold, min_silence_ms: list(spans))
    return _set


def _ranges(wins):
    return [(w.start_s, w.end_s) for w in wins]


# ── the zero-gap merge ──────────────────────────────────────────────────────
# A policy with a max_span_s far above any span here, so merging is the only
# thing that can change the output.

_NO_SPLIT = WindowPolicy(max_span_s=10_000.0)


def test_merges_exactly_touching_spans(vad):
    vad([(0.0, 10.0), (10.0, 20.0)])
    assert _ranges(speech_windows(_AUDIO, _NO_SPLIT)) == [(0.0, 20.0)]


def test_merges_near_zero_gap_spans(vad):
    # A 20ms gap is well inside the float-rounding tolerance -- the same
    # "silence under ~800ms got padded to ~0" case the incident traced back
    # to, just not landing on exactly 0.0 due to sample-rate rounding.
    vad([(0.0, 10.0), (10.02, 20.0)])
    assert _ranges(speech_windows(_AUDIO, _NO_SPLIT)) == [(0.0, 20.0)]


def test_preserves_a_genuine_pause(vad):
    # Anything the padding-merge didn't fully absorb is a real >= ~800ms
    # silence -- must stay a separate span.
    vad([(0.0, 10.0), (10.9, 20.0)])
    assert _ranges(speech_windows(_AUDIO, _NO_SPLIT)) == [(0.0, 10.0), (10.9, 20.0)]


def test_merges_a_chain_of_touching_spans(vad):
    vad([(0.0, 10.0), (10.0, 20.0), (20.0, 35.0), (40.0, 50.0)])
    assert _ranges(speech_windows(_AUDIO, _NO_SPLIT)) == [(0.0, 35.0), (40.0, 50.0)]


def test_empty_and_single_span(vad):
    vad([])
    assert speech_windows(_AUDIO, _NO_SPLIT) == []
    vad([(1.0, 2.0)])
    assert _ranges(speech_windows(_AUDIO, _NO_SPLIT)) == [(1.0, 2.0)]


def test_merge_disabled_leaves_adjacent_spans_alone(vad):
    """Pins Qwen3-ASR's preserved behaviour: it never had the merge, and
    `merge_max_gap_s=None` is what keeps it that way. Note `0.0` would NOT —
    a reported gap of exactly 0.0 is the common case the merge catches."""
    vad([(0.0, 10.0), (10.0, 20.0)])
    off = WindowPolicy(max_span_s=10_000.0, merge_max_gap_s=None)
    assert _ranges(speech_windows(_AUDIO, off)) == [(0.0, 10.0), (10.0, 20.0)]

    zero = WindowPolicy(max_span_s=10_000.0, merge_max_gap_s=0.0)
    assert _ranges(speech_windows(_AUDIO, zero)) == [(0.0, 20.0)], (
        "0.0 must still merge exactly-touching spans — that is why None exists"
    )


# ── the over-long split ─────────────────────────────────────────────────────

def test_long_span_becomes_overlapping_windows_covering_it_with_no_hole(vad):
    vad([(0.0, 60.0)])
    wins = speech_windows(_AUDIO, WindowPolicy(max_span_s=25.0, overlap_s=4.0))
    assert len(wins) > 1
    assert wins[0].start_s == 0.0 and wins[-1].end_s == 60.0
    assert all(w.duration_s <= 25.0 for w in wins), "a window may never exceed max_span_s"
    for prev, nxt in zip(wins, wins[1:]):
        assert nxt.start_s < prev.end_s, f"hole between {prev} and {nxt}"
        assert prev.end_s - nxt.start_s == pytest.approx(4.0), "overlap must be the policy's"


def test_zero_overlap_windows_abut_exactly(vad):
    """Qwen3-ASR's policy: no seam-dedupe pass, so overlap would duplicate text."""
    vad([(0.0, 20.0)])
    wins = speech_windows(_AUDIO, WindowPolicy(max_span_s=8.0, overlap_s=0.0,
                                               merge_max_gap_s=None))
    assert _ranges(wins) == [(0.0, 8.0), (8.0, 16.0), (16.0, 20.0)]


def test_short_span_is_one_window(vad):
    vad([(1.0, 9.0)])
    wins = speech_windows(_AUDIO, WindowPolicy(max_span_s=25.0))
    assert _ranges(wins) == [(1.0, 9.0)]


def test_windows_of_one_span_share_a_span_index(vad):
    """A caller stitching overlapping decodes needs to know which windows came
    from the same continuous run of speech."""
    vad([(0.0, 60.0), (70.0, 71.0)])
    wins = speech_windows(_AUDIO, WindowPolicy(max_span_s=25.0, overlap_s=4.0))
    long_run = [w for w in wins if w.span_index == 0]
    short_run = [w for w in wins if w.span_index == 1]
    assert len(long_run) > 1
    assert len(short_run) == 1, "a span short enough to decode whole is one window"


# ── the silence fallback ────────────────────────────────────────────────────

def test_no_speech_returns_nothing_by_default(vad):
    vad([])
    assert speech_windows(_AUDIO, WindowPolicy()) == []


def test_no_speech_can_fall_back_to_the_whole_clip(vad):
    """Qwen3-ASR's policy: it must emit something rather than nothing, and the
    fallback span is windowed like any other."""
    vad([])
    audio = np.zeros(20 * 16000, dtype=np.float32)
    wins = speech_windows(audio, WindowPolicy(max_span_s=8.0, overlap_s=0.0,
                                              whole_clip_on_silence=True))
    assert _ranges(wins) == [(0.0, 8.0), (8.0, 16.0), (16.0, 20.0)]


# ── the unit-safety the Window type exists for ──────────────────────────────

def test_window_second_and_millisecond_accessors_agree():
    w = Window(1.25, 3.5, span_index=0)
    assert w.start_ms == 1250
    assert w.end_ms == 3500
    assert w.duration_s == pytest.approx(2.25)


def test_the_two_adapters_policies_differ_in_the_documented_way():
    """Turns an accident into a decision. Qwen3-ASR's missing zero-gap merge is
    preserved deliberately (see its constructor); enabling it is a behaviour
    change that needs its own harness probe."""
    from transcribe.engines.faster_whisper import FasterWhisperEngine
    from transcribe.engines.qwen3_asr import Qwen3ASREngine

    fw = FasterWhisperEngine(device="cpu")._window_policy
    qwen = Qwen3ASREngine(device="cpu")._window_policy

    assert fw.merge_max_gap_s == 0.05 and qwen.merge_max_gap_s is None
    assert fw.max_span_s == 25.0 and qwen.max_span_s == 8.0
    assert fw.overlap_s == 4.0 and qwen.overlap_s == 0.0
    assert fw.whole_clip_on_silence is False and qwen.whole_clip_on_silence is True
    # The VAD thresholds are deliberately the SAME — both are hand-matched to
    # config.yaml's tuned ingest values (soft Thai sentence-final particles).
    assert fw.vad_threshold == qwen.vad_threshold == 0.35
    assert fw.vad_min_silence_ms == qwen.vad_min_silence_ms == 500
