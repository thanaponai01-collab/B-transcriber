"""_merge_contiguous_spans — TODO_LEDGER.md 2026-08-06 incident fix.

faster_whisper.vad.get_speech_timestamps pads real inter-speech silence
under ~800ms so it reports as a zero gap between two adjacent VAD spans.
_transcribe_batched used to treat those as fully independent decodes with
no overlap at the seam, and real content was confirmed lost exactly there
on production audio. _merge_contiguous_spans closes that seam before any
windowing/decoding happens.
"""

from transcribe.engines.faster_whisper import _merge_contiguous_spans


def test_merges_exactly_touching_spans():
    spans = [(0.0, 10.0), (10.0, 20.0)]
    assert _merge_contiguous_spans(spans) == [(0.0, 20.0)]


def test_merges_near_zero_gap_spans():
    # A 20ms gap is well inside the float-rounding tolerance -- the same
    # "silence under ~800ms got padded to ~0" case the incident traced back
    # to, just not landing on exactly 0.0 due to sample-rate rounding.
    spans = [(0.0, 10.0), (10.02, 20.0)]
    assert _merge_contiguous_spans(spans) == [(0.0, 20.0)]


def test_preserves_a_genuine_pause():
    # Anything the padding-merge didn't fully absorb is a real >= ~800ms
    # silence -- must stay a separate span.
    spans = [(0.0, 10.0), (10.9, 20.0)]
    assert _merge_contiguous_spans(spans) == [(0.0, 10.0), (10.9, 20.0)]


def test_merges_a_chain_of_touching_spans():
    spans = [(0.0, 10.0), (10.0, 20.0), (20.0, 35.0), (40.0, 50.0)]
    assert _merge_contiguous_spans(spans) == [(0.0, 35.0), (40.0, 50.0)]


def test_empty_and_single_span_unchanged():
    assert _merge_contiguous_spans([]) == []
    assert _merge_contiguous_spans([(1.0, 2.0)]) == [(1.0, 2.0)]
