"""Truncated-tail recovery for the faster-whisper long-span decode path.

Covers the failure mode where faster-whisper stops generating early within a
long-span window and stretches the last word's timestamp out to the window's
end to fill the gap (see _TRUNCATION_TAIL_MS docs in faster_whisper.py) —
and the fix's own pitfall: a fixed-offset cut can land mid-syllable and
reproduce a stray piece on both sides, since Thai subword pieces don't align
to word boundaries. _find_safe_cut is tested for choosing a real inter-token
gap instead of an arbitrary offset.
"""

import numpy as np

from transcribe.contracts import RecognizedToken
from transcribe.engines.faster_whisper import (
    FasterWhisperEngine,
    _SR,
    _TRUNCATION_LOOKBACK_MS,
)


def _tok(text, start_ms, end_ms):
    return RecognizedToken(text, start_ms, end_ms, 0.9, "thai")


class _FakeWord:
    def __init__(self, word, start, end, probability=0.9):
        self.word = word
        self.start = start
        self.end = end
        self.probability = probability


class _FakeSegment:
    def __init__(self, words):
        self.words = words


# ── _find_safe_cut ──────────────────────────────────────────────────────────

def test_find_safe_cut_picks_largest_gap_not_fixed_offset():
    tokens_before = [_tok("มา", 0, 300), _tok("เขา", 2000, 2300)]
    # anchor 2300ms: the 1700ms gap between the two tokens is the only
    # candidate and should be chosen regardless of any fixed offset.
    idx = FasterWhisperEngine._find_safe_cut(tokens_before, anchor_ms=2300)
    assert idx == 0


def test_find_safe_cut_none_when_fewer_than_two_in_range():
    tokens_before = [_tok("มา", 0, 300)]
    assert FasterWhisperEngine._find_safe_cut(tokens_before, anchor_ms=2300) is None
    assert FasterWhisperEngine._find_safe_cut([], anchor_ms=2300) is None


def test_find_safe_cut_ignores_gaps_outside_lookback():
    # A big early gap sits outside the lookback window from the anchor, so
    # the (smaller) in-range gap must win instead of the biggest gap overall.
    far_gap_end = 0
    tokens_before = [
        _tok("a", far_gap_end, 100),
        _tok("b", 100 + _TRUNCATION_LOOKBACK_MS * 3, 100 + _TRUNCATION_LOOKBACK_MS * 3 + 50),
        _tok("c", 100 + _TRUNCATION_LOOKBACK_MS * 3 + 200, 100 + _TRUNCATION_LOOKBACK_MS * 3 + 260),
    ]
    anchor = tokens_before[-1].end_ms + 10
    idx = FasterWhisperEngine._find_safe_cut(tokens_before, anchor_ms=anchor)
    assert idx == 1  # the b/c gap, not the huge a/b gap far outside lookback


# ── _recover_truncated_tail ─────────────────────────────────────────────────

def test_recovers_dropped_tail_and_cuts_at_real_gap():
    eng = FasterWhisperEngine()
    win_dur_ms = 9000
    tokens = [
        _tok("มา", 0, 300),
        _tok("เขา", 2000, 2300),          # real gap before this = safe cut point
        _tok("อง", 2300, win_dur_ms),      # stretched to fill the window: the bug
    ]
    sub_audio = np.zeros(int(win_dur_ms / 1000 * _SR), dtype=np.float32)

    captured = {}

    def fake_decode(audio_arr, clip_timestamps, vad_filter, common_kwargs, bs):
        captured["len"] = len(audio_arr)
        return [_FakeSegment([_FakeWord(" recovered", 0.0, 1.0)])], bs

    eng._decode = fake_decode
    merged, bs = eng._recover_truncated_tail(tokens, sub_audio, {}, 8, win_dur_ms)

    assert bs == 8
    # kept only "มา" — the cut lands at the real 1700ms gap, not at "เขา"'s
    # own suspicious-adjacent boundary, so "เขา" is dropped from kept and
    # left entirely to the fresh redecode (avoiding a straddled duplicate).
    assert [t.text for t in merged[:1]] == ["มา"]
    recovered = merged[1:]
    assert len(recovered) == 1
    assert recovered[0].text == " recovered"
    # tail redecode started at "เขา"'s own start (2000ms), offset applied
    assert recovered[0].start_ms == 2000
    assert recovered[0].end_ms == 3000
    assert captured["len"] == len(sub_audio) - int(2000 / 1000 * _SR)


def test_no_recovery_when_last_word_duration_is_normal():
    eng = FasterWhisperEngine()
    tokens = [_tok("มา", 0, 300), _tok("เขา", 2000, 2300)]
    eng._decode = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not redecode"))
    merged, bs = eng._recover_truncated_tail(tokens, np.zeros(_SR), {}, 8, 2300)
    assert merged is tokens
    assert bs == 8


def test_no_recovery_when_suspicious_word_does_not_reach_window_end():
    eng = FasterWhisperEngine()
    win_dur_ms = 9000
    tokens = [_tok("มา", 0, 300), _tok("อง", 2300, 5000)]  # ends well short of win_dur_ms
    eng._decode = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not redecode"))
    merged, bs = eng._recover_truncated_tail(tokens, np.zeros(int(win_dur_ms / 1000 * _SR)), {}, 8, win_dur_ms)
    assert merged is tokens
    assert bs == 8


def test_no_recovery_when_no_safe_cut_available():
    eng = FasterWhisperEngine()
    win_dur_ms = 9000
    # Only one token before the suspicious tail -> _find_safe_cut has nothing
    # to compare and returns None -> bail out rather than guess a boundary.
    tokens = [_tok("มา", 0, 300), _tok("อง", 300, win_dur_ms)]
    eng._decode = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not redecode"))
    merged, bs = eng._recover_truncated_tail(tokens, np.zeros(int(win_dur_ms / 1000 * _SR)), {}, 8, win_dur_ms)
    assert merged is tokens
    assert bs == 8


def test_empty_tokens_returns_unchanged():
    eng = FasterWhisperEngine()
    merged, bs = eng._recover_truncated_tail([], np.zeros(_SR), {}, 8, 9000)
    assert merged == []
    assert bs == 8
