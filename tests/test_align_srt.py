"""Acceptance tests for the diff-srt flywheel path (align_srt.py).

Covers the connected-components-over-overlap grouping (no-edit, merge, split,
deletion, insertion), the timebase-divergence guard, and the DB write path.
"""

import tempfile
from pathlib import Path

import pytest

from transcribe.flywheel import align_srt
from transcribe.flywheel.align_srt import TimebaseMismatch, align_tokens_to_cues, write_corrections


def _orig(idx, text, start_ms, end_ms, source_engine="a"):
    return {"idx": idx, "text": text, "start_ms": start_ms, "end_ms": end_ms, "source_engine": source_engine}


def _final(text, start_ms, end_ms):
    return {"text": text, "start_ms": start_ms, "end_ms": end_ms}


# ── grouping cases ────────────────────────────────────────────────────────────

def test_no_edit_produces_no_correction():
    original = [_orig(0, "hello", 0, 1000), _orig(1, "world", 1000, 2000)]
    final = [_final("hello", 0, 1000), _final("world", 1000, 2000)]
    result = align_tokens_to_cues(original, final)
    assert result.pairs == []
    assert result.summary.matched_original == 2
    assert result.summary.matched_final == 2
    assert result.summary.unmatched_original == 0
    assert result.summary.unmatched_final == 0


def test_one_to_one_text_edit():
    original = [_orig(0, "ChatGBT is neat", 0, 1000)]
    final = [_final("ChatGPT is neat", 0, 1000)]
    result = align_tokens_to_cues(original, final)
    assert len(result.pairs) == 1
    p = result.pairs[0]
    assert p.token_idx == 0
    assert p.raw_text == "ChatGBT is neat"
    assert p.corrected_text == "ChatGPT is neat"
    assert p.reason == "srt_reimport"
    assert p.source_engine == "a"


def test_merge_two_originals_into_one_final():
    original = [
        _orig(0, "hello", 0, 1000, source_engine="a"),
        _orig(1, "there world", 1000, 2000, source_engine="a"),
    ]
    final = [_final("hello there, world", 0, 2000)]
    result = align_tokens_to_cues(original, final)
    assert len(result.pairs) == 1
    p = result.pairs[0]
    assert p.token_idx == 0  # lowest original idx owns the row
    assert p.raw_text == "hello there world"
    assert p.corrected_text == "hello there, world"
    assert result.summary.matched_original == 2
    assert result.summary.matched_final == 1


def test_split_one_original_into_two_finals():
    original = [_orig(5, "hello there world", 0, 2000)]
    final = [_final("hello there,", 0, 1000), _final("world!", 1000, 2000)]
    result = align_tokens_to_cues(original, final)
    assert len(result.pairs) == 1
    p = result.pairs[0]
    assert p.token_idx == 5
    assert p.corrected_text == "hello there, world!"
    assert result.summary.matched_final == 2


def test_split_with_no_text_change_produces_no_correction():
    """A pure re-timing split (text unchanged once rejoined) is not a text
    correction — the flywheel biases text, not timing."""
    original = [_orig(5, "hello there world", 0, 2000)]
    final = [_final("hello there", 0, 1000), _final("world", 1000, 2000)]
    result = align_tokens_to_cues(original, final)
    assert result.pairs == []
    assert result.summary.matched_final == 2


def test_deletion_original_with_no_overlapping_final():
    original = [
        _orig(0, "keep me", 0, 1000),
        _orig(1, "hallucinated filler", 1000, 2000),
        _orig(2, "keep me too", 2000, 3000),
    ]
    final = [_final("keep me", 0, 1000), _final("keep me too", 2000, 3000)]
    result = align_tokens_to_cues(original, final)
    assert len(result.pairs) == 1
    p = result.pairs[0]
    assert p.token_idx == 1
    assert p.raw_text == "hallucinated filler"
    assert p.corrected_text == ""
    assert result.summary.unmatched_original == 1


def test_insertion_final_with_no_overlapping_original_is_reported_not_synthesized():
    original = [_orig(0, "hello", 0, 1000)]
    final = [_final("hello", 0, 1000), _final("[TITLE CARD]", 5000, 6000)]
    result = align_tokens_to_cues(original, final)
    assert result.pairs == []  # no source token to attribute a correction to
    assert result.summary.unmatched_final == 1
    assert result.summary.unmatched_final_texts == ["[TITLE CARD]"]


def test_plurality_source_engine_for_merged_group():
    original = [
        _orig(0, "a", 0, 1000, source_engine="a"),
        _orig(1, "b", 1000, 2000, source_engine="a"),
        _orig(2, "c", 2000, 3000, source_engine="b"),
    ]
    final = [_final("a b c edited", 0, 3000)]
    result = align_tokens_to_cues(original, final)
    assert result.pairs[0].source_engine == "a"  # 2 vs 1


def test_no_original_tokens_raises():
    with pytest.raises(ValueError):
        align_tokens_to_cues([], [_final("x", 0, 1000)])


# ── timebase divergence guard ─────────────────────────────────────────────────

def test_timebase_mismatch_raises_when_almost_nothing_overlaps():
    # 5 original tokens spread across 0-10s (a realistic multi-cue job) against
    # a final SRT timed entirely against a disjoint region of a (likely
    # different) file — nothing overlaps at all.
    original = [_orig(i, f"word{i}", i * 2000, i * 2000 + 2000) for i in range(5)]
    final = [_final(f"word{i}", 500_000 + i * 2000, 500_000 + i * 2000 + 2000) for i in range(5)]
    with pytest.raises(TimebaseMismatch):
        align_tokens_to_cues(original, final)


def test_timebase_small_drift_is_tolerated():
    original = [_orig(i, f"word{i}", i * 2000, i * 2000 + 2000) for i in range(5)]
    # Every cue shifted 300ms late — real clock drift, not a wrong file — each
    # still overlaps its corresponding original token.
    final = [_final(f"word{i}", i * 2000 + 300, i * 2000 + 2300) for i in range(5)]
    result = align_tokens_to_cues(original, final)  # must not raise
    assert result.summary.matched_original == 5


def test_timebase_trailing_title_card_is_tolerated():
    """A normal edit that adds an outro/title card well past the last real
    token must not look like a wrong-file mismatch just because it stretches
    the final SRT's outer timestamp."""
    original = [_orig(i, f"word{i}", i * 2000, i * 2000 + 2000) for i in range(5)]
    final = [_final(f"word{i}", i * 2000, i * 2000 + 2000) for i in range(5)]
    final.append(_final("[OUTRO CARD]", 60_000, 65_000))  # far past the last token
    result = align_tokens_to_cues(original, final)  # must not raise
    assert result.summary.matched_original == 5
    assert result.summary.unmatched_final == 1


# ── DB write path ─────────────────────────────────────────────────────────────

def test_write_corrections_lands_in_db_with_correct_attribution():
    from transcribe.db import store

    d = Path(tempfile.mkdtemp())
    media_file = d / "clip.wav"
    media_file.write_bytes(b"not real audio, only sha256_of_file reads this")
    db_path = d / "test.db"
    store.init_db(db_path)
    conn = store.connect(db_path)

    media_id = store.create_media(conn, str(media_file))
    job_id = store.create_job(conn, media_id, "faster_whisper", "passthrough", "v1")
    store.create_token(conn, job_id, 0, "hello", 0, 1000, "latin", 0.9, "a")
    store.create_token(conn, job_id, 1, "there world", 1000, 2000, "latin", 0.9, "a")

    original = [
        {"idx": t.idx, "text": t.text, "start_ms": t.start_ms, "end_ms": t.end_ms,
         "source_engine": t.source_engine}
        for t in store.get_tokens(conn, job_id)
    ]
    final = [_final("hello there, world", 0, 2000)]  # merged + punctuation fix

    result = align_tokens_to_cues(original, final)
    n_written = write_corrections(conn, job_id, result.pairs)
    assert n_written == 1

    corrections = store.get_corrections(conn, job_id)
    assert len(corrections) == 1
    c = corrections[0]
    assert c.token_idx == 0
    assert c.raw_text == "hello there world"
    assert c.corrected_text == "hello there, world"
    assert c.source_engine == "a"
    assert c.reason == "srt_reimport"

    conn.close()
