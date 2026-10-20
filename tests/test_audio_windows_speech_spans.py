"""Tests for speech_windows derivation from ingest speech spans (issue #72)."""

import numpy as np
import pytest

import transcribe.audio.windows as windows
from transcribe.audio import Window, WindowPolicy, speech_windows

_AUDIO = np.zeros(60 * 16000, dtype=np.float32)
_NO_SPLIT = WindowPolicy(max_span_s=10_000.0)


def _ranges(wins):
    return [(w.start_s, w.end_s) for w in wins]


def test_speech_spans_skips_vad_call(monkeypatch):
    called = []
    monkeypatch.setattr(windows, '_vad_speech_spans',
                        lambda a, t, m: called.append(True) or [(0.0, 1.0)])
    spans = [(1000, 5000)]
    wins = speech_windows(_AUDIO, _NO_SPLIT, speech_spans=spans)
    assert not called, 'speech_windows must not call VAD when speech_spans is provided'
    # 400ms padding on both sides
    assert _ranges(wins) == [(0.6, 5.4)]


def test_speech_spans_empty_falls_back_to_vad(monkeypatch):
    called = []
    monkeypatch.setattr(windows, '_vad_speech_spans',
                        lambda a, t, m: called.append(True) or [(1.0, 2.0)])
    wins = speech_windows(_AUDIO, _NO_SPLIT, speech_spans=())
    assert called, 'speech_windows must call VAD when speech_spans is empty'
    assert _ranges(wins) == [(1.0, 2.0)]


def test_speech_spans_padding_and_merging():
    # Gap < 800ms (300ms gap between 5000 and 5300) -> midpoint padding -> gap 0 -> merged
    # Gap >= 800ms (2600ms gap between 9000 and 11600) -> 400ms padding each -> remains separated
    spans = [(1000, 5000), (5300, 9000), (11600, 15000)]
    wins = speech_windows(_AUDIO, _NO_SPLIT, speech_spans=spans)
    # Span 1+2 merge to [0.6, 9.4], Span 3 becomes [11.2, 15.4]
    assert _ranges(wins) == [(0.6, 9.4), (11.2, 15.4)]


def test_speech_spans_long_span_split():
    # Long span of 60 seconds on 70s audio
    audio_70s = np.zeros(70 * 16000, dtype=np.float32)
    spans = [(0, 60000)]
    wins = speech_windows(audio_70s, WindowPolicy(max_span_s=25.0, overlap_s=4.0), speech_spans=spans)
    assert len(wins) > 1
    assert wins[0].start_s == 0.0
    assert wins[-1].end_s == 60.4  # 60s + 0.4s padding
    assert all(w.duration_s <= 25.0 for w in wins)


def test_speech_spans_clamped_to_audio_duration():
    # 2-second audio array (32000 samples)
    short_audio = np.zeros(2 * 16000, dtype=np.float32)
    spans = [(100, 1900)]
    wins = speech_windows(short_audio, _NO_SPLIT, speech_spans=spans)
    # Start clamped at 0.0, end clamped at 2.0
    assert _ranges(wins) == [(0.0, 2.0)]
