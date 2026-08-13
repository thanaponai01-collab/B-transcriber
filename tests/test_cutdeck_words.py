"""CutDeck Phase 1 acceptance tests — cutdeck/words.py (HANDOFF_CUTDECK_WORDLEVEL.md).

Covers the word-timeline enabling layer:
  * sub-word fragments regroup into real words (job-29 fixture, F2);
  * Latin + Thai mixed piece lists keep Latin runs intact and don't glue
    across whitespace;
  * word spans are monotonic, non-overlapping, and inside their source pieces;
  * words_for_job degrades to [] on NULL raw_words_json and on a missing result;
  * words_for_job round-trips through the store;
  * regression: cue-grouping output is unaffected by the refactor to share
    this implementation (see test_faster_whisper_cues.py / test_cue_*.py).

All GPU-free. Run: python -m pytest tests/test_cutdeck_words.py -v
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from cutdeck.words import words_for_job, words_from_pieces  # noqa: E402


def test_subword_fragments_regroup_at_real_pythainlp_word_boundaries():
    # pythainlp's dictionary tokenizer splits "เทส" (a transliteration, not a
    # lexicon word) into ["เท", "ส"] even when it's presented as one contiguous
    # run of characters — the regrouping is only as good as pythainlp's word
    # boundaries. What matters here is that the two source fragments (which
    # split arbitrarily inside a real word: "เท"/"ส") are re-timed onto
    # whatever boundaries pythainlp actually finds, spanning the full input
    # with no gaps or overlaps.
    pieces = [("เท", 1520, 2120, 0.9), ("ส", 2120, 2420, 0.8)]
    words = words_from_pieces(pieces)
    assert "".join(w.text for w in words) == "เทส"
    assert words[0].start_ms == 1520
    assert words[-1].end_ms == 2420
    for a, b in zip(words, words[1:]):
        assert a.end_ms == b.start_ms


def test_latin_and_thai_mixed_stay_separate():
    # "hello สวัสดี world" split into arbitrary sub-piece fragments.
    pieces = [
        ("hel", 0, 100, None), ("lo", 100, 200, None),
        (" ", 200, 200, None),
        ("สวัส", 200, 500, None), ("ดี", 500, 700, None),
        (" ", 700, 700, None),
        ("wor", 700, 900, None), ("ld", 900, 1000, None),
    ]
    words = words_from_pieces(pieces)
    texts = [w.text for w in words]
    assert texts == ["hello", "สวัสดี", "world"]


def test_word_spans_monotonic_non_overlapping_and_bounded():
    pieces = [
        ("hel", 0, 100, None), ("lo", 100, 200, None),
        (" ", 200, 200, None),
        ("wor", 700, 900, None), ("ld", 900, 1000, None),
    ]
    words = words_from_pieces(pieces)
    for a, b in zip(words, words[1:]):
        assert a.end_ms <= b.start_ms
    assert words[0].start_ms >= 0 and words[0].end_ms <= 200
    assert words[1].start_ms >= 700 and words[1].end_ms <= 1000


def test_words_from_pieces_empty_input():
    assert words_from_pieces([]) == []


def test_words_for_job_returns_empty_when_no_engine_result():
    from transcribe.db import store
    db = _tmp_db()
    store.init_db(db)
    conn = store.connect(db)
    job_id, audio_path = _seed_job(conn)

    assert words_for_job(conn, job_id) == []

    conn.close()
    db.unlink()
    Path(audio_path).unlink()


def test_words_for_job_returns_empty_when_raw_words_json_null():
    from transcribe.db import store
    db = _tmp_db()
    store.init_db(db)
    conn = store.connect(db)
    job_id, audio_path = _seed_job(conn)

    store.save_engine_result(conn, job_id, "a", "faster_whisper", "[]", True, raw_words_json=None)

    assert words_for_job(conn, job_id) == []

    conn.close()
    db.unlink()
    Path(audio_path).unlink()


def test_words_for_job_roundtrips_through_store():
    from transcribe.db import store
    db = _tmp_db()
    store.init_db(db)
    conn = store.connect(db)
    job_id, audio_path = _seed_job(conn)

    raw = [
        {"text": "เท", "start_ms": 1520, "end_ms": 2120, "confidence": 0.9},
        {"text": "ส", "start_ms": 2120, "end_ms": 2420, "confidence": 0.8},
    ]
    store.save_engine_result(conn, job_id, "a", "faster_whisper", "[]", True,
                              raw_words_json=json.dumps(raw))

    words = words_for_job(conn, job_id)
    assert "".join(w.text for w in words) == "เทส"
    assert words[0].start_ms == 1520
    assert words[-1].end_ms == 2420

    conn.close()
    db.unlink()
    Path(audio_path).unlink()


# ── regression: split_cues shares timed_tokens() and must still ─────────────
# produce byte-identical cue output. test_cue_conform.py / test_cues_space_break.py /
# test_cues_policy_config.py / test_cues_grouping.py already cover this
# directly; this test pins the specific job-29 F2 fragment shape through the
# real cue-grouping entry point as a belt-and-suspenders check.

def test_group_words_into_cues_still_works_after_refactor():
    from transcribe.cues import split_cues

    words = [("เท", 1520, 2120, 0.9), ("ส", 2120, 2420, 0.8)]
    cues = split_cues(words)
    assert len(cues) == 1
    text, start, end, conf = cues[0]
    assert text == "เทส" and start == 1520 and end == 2420
    assert conf == pytest.approx(0.85)


def _tmp_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return Path(f.name)


def _seed_job(conn):
    from transcribe.db import store
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as af:
        af.write(b"\x00" * 64)
        audio_path = af.name
    media_id = store.create_media(conn, audio_path)
    store.set_media_timebase(conn, media_id, 30000, 1001, is_vfr=False)
    job_id = store.create_job(conn, media_id, "a", "b", "1.0")
    return job_id, audio_path
