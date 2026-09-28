"""extract_changed_span / diff_corrections contract (transcribe/flywheel/diff.py).

Written from the docstring: short-on-both-sides returns the corrected text; otherwise the
minimal changed word/phrase; never an empty string.
"""
from transcribe.flywheel.diff import (
    _SPAN_THRESHOLD, CorrectionPair, diff_corrections, extract_changed_span,
)

LONG_RAW = "please ask ChatGBT about the weather today"
LONG_FIX = "please ask ChatGPT about the weather today"


def test_both_short_returns_whole_corrected():
    assert extract_changed_span("abc def", "abc xyz") == "abc xyz"


def test_at_threshold_counts_as_short():
    raw = "a" * _SPAN_THRESHOLD
    corrected = "b" * _SPAN_THRESHOLD
    assert extract_changed_span(raw, corrected) == corrected


def test_long_latin_one_word_edit_returns_only_that_word():
    assert extract_changed_span(LONG_RAW, LONG_FIX) == "ChatGPT"


def test_only_one_side_long_still_extracts():
    raw = "aa bb cc dd"                       # 11 chars, short
    corrected = "aa bb cc dd ee ff gg hh"     # 23 chars, long
    assert extract_changed_span(raw, corrected) == "ee ff gg hh"
    back = extract_changed_span(corrected, raw)  # pure deletion, one side long: widened neighbour
    assert back.strip() and back in raw and back != raw


def test_identical_long_text_returns_corrected():
    assert extract_changed_span(LONG_FIX, LONG_FIX) == LONG_FIX


def test_multiple_separate_edits_span_covers_both():
    raw = "one two three four five six seven"
    fix = "one TWO three four five SIX seven"
    span = extract_changed_span(raw, fix)
    assert span.startswith("TWO") and span.endswith("SIX")
    assert "one" not in span and "seven" not in span


def test_pure_deletion_never_returns_empty():
    raw = "the quick brown fox jumps over"
    fix = "the quick fox jumps over"
    span = extract_changed_span(raw, fix)
    assert span.strip() and span in fix and span != fix


def test_deletion_of_last_word_never_returns_empty():
    raw = "the quick brown fox jumps over"
    fix = "the quick brown fox jumps"
    span = extract_changed_span(raw, fix)
    assert span.strip() and span in fix


def test_thai_one_word_edit_is_narrower_than_the_cue():
    raw = "วันนี้อากาศดีมากเลยครับผมไปเดินเล่นที่สวนสาธารณะ"
    fix = "วันนี้อากาศดีมากเลยครับผมไปเดินเล่นที่สวนลุมพินี"
    span = extract_changed_span(raw, fix)
    assert span and span in fix and len(span) < len(fix)
    assert "ลุมพินี" in span or span in "ลุมพินี"


def test_diff_corrections_only_changed_tokens():
    orig = [{"idx": 0, "text": "same", "source_engine": "e1"},
            {"idx": 1, "text": LONG_RAW, "source_engine": "e1"}]
    corr = [{"idx": 0, "text": "same"},
            {"idx": 1, "text": LONG_FIX, "reason": "brand"}]
    pairs = diff_corrections(orig, corr)
    assert pairs == [CorrectionPair(
        token_idx=1, raw_text=LONG_RAW, corrected_text=LONG_FIX,
        source_engine="e1", reason="brand", corrected_span="ChatGPT")]


def test_diff_corrections_skips_unknown_idx_and_defaults_engine():
    orig = [{"idx": 0, "text": "hello"}]
    corr = [{"idx": 0, "text": "hullo"}, {"idx": 9, "text": "ghost"}]
    pairs = diff_corrections(orig, corr)
    assert [p.token_idx for p in pairs] == [0]
    assert pairs[0].source_engine == "unknown" and pairs[0].reason is None
