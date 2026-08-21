"""transcribe/audio/decode.py — decode_windows composition (issue #13).

The headline new test for the windows/stitch merge: `decode_windows` did not
exist as a directly-testable unit before this ticket, because the
window-decode-offset-stitch loop was inline inside `faster_whisper.py` and
`pipeline/engine_run.py`. No GPU, no model, no real VAD — windows are
constructed by hand and `decode_fn` returns canned tokens per window, so this
exercises exactly the composition (offset + stitch), not detection.

Run: python -m pytest tests/test_audio_decode.py -v
"""

import numpy as np

from transcribe.audio import AudioWindow, decode_windows
from transcribe.contracts import RecognizedToken


def _tok(text, start_ms, end_ms, conf=0.9, script="latin"):
    return RecognizedToken(text, start_ms, end_ms, conf, script)


def test_decode_fn_called_once_per_window_in_order():
    calls = []

    def decode_fn(win_audio):
        calls.append(len(win_audio))
        return []

    windows = [
        AudioWindow(np.zeros(10, dtype=np.float32), 0, 100),
        AudioWindow(np.zeros(20, dtype=np.float32), 100, 300),
        AudioWindow(np.zeros(30, dtype=np.float32), 300, 600),
    ]
    decode_windows(windows, decode_fn, seam_window_ms=1000)
    assert calls == [10, 20, 30]


def test_offsets_local_timestamps_to_global():
    """decode_fn's tokens come back window-LOCAL; decode_windows must offset
    them by each window's own start_ms before the caller ever sees them."""
    windows = [
        AudioWindow(np.zeros(1, dtype=np.float32), 0, 1000),
        AudioWindow(np.zeros(1, dtype=np.float32), 5000, 6000),
    ]
    results = iter([
        [_tok("hello", 0, 400), _tok("there", 400, 800)],
        [_tok("world", 100, 500)],
    ])

    def decode_fn(win_audio):
        return next(results)

    out = decode_windows(windows, decode_fn, seam_window_ms=200)
    assert [(t.text, t.start_ms, t.end_ms) for t in out] == [
        ("hello", 0, 400),
        ("there", 400, 800),
        ("world", 5100, 5500),
    ]


def test_overlap_produces_a_seam_duplicate_that_gets_deduped():
    """A policy with overlap_s > 0 routed through decode_windows must dedupe
    — the property that motivated this ticket, now assertable directly
    instead of only trusted."""
    # Two windows sharing a 1000ms overlap (1000ms-2000ms global); both decode
    # the same word sitting inside that shared audio, each seeing it at a
    # different LOCAL offset (as two independent decodes of the same speech
    # typically do). Window 0's copy sits near ITS right edge (shallow,
    # interiority 100); window 1's copy sits deep in window 1 (interiority
    # 950) — the deeper copy must survive.
    windows = [
        AudioWindow(np.zeros(1, dtype=np.float32), 0, 2000),
        AudioWindow(np.zeros(1, dtype=np.float32), 1000, 3000),
    ]
    results = iter([
        [_tok("มา", 1850, 1950, script="thai")],  # global 1850-1950, near window 0's edge
        [_tok("มา", 900, 1000, script="thai")],    # global 1900-2000, deep in window 1
    ])

    def decode_fn(win_audio):
        return next(results)

    out = decode_windows(windows, decode_fn, seam_window_ms=1000)
    assert [t.text for t in out] == ["มา"], "seam duplicate must be deduped, not doubled"
    # The more-interior copy (window 1's) wins.
    assert (out[0].start_ms, out[0].end_ms) == (1900, 2000)


def test_no_overlap_no_dedupe_needed_both_words_survive():
    windows = [
        AudioWindow(np.zeros(1, dtype=np.float32), 0, 1000),
        AudioWindow(np.zeros(1, dtype=np.float32), 1000, 2000),
    ]
    results = iter([
        [_tok("มา", 800, 950, script="thai")],
        [_tok("มา", 800, 950, script="thai")],  # global 1800-1950 -- far from the first
    ])

    def decode_fn(win_audio):
        return next(results)

    out = decode_windows(windows, decode_fn, seam_window_ms=0)
    assert [t.start_ms for t in out] == [800, 1800]


def test_single_window_is_a_no_op_pass_through():
    windows = [AudioWindow(np.zeros(1, dtype=np.float32), 500, 1500)]

    def decode_fn(win_audio):
        return [_tok("hi", 0, 200)]

    out = decode_windows(windows, decode_fn, seam_window_ms=4000)
    assert [(t.text, t.start_ms, t.end_ms) for t in out] == [("hi", 500, 700)]
