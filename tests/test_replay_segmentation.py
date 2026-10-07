import json
import sqlite3

from tools.replay_segmentation import (baseline_settings, find_words, load_config,
                                        replay, score, text_key)

WORDS = [
    ("โ", 0, 200, 0.9), ("อ", 200, 300, 0.9), ("เค", 300, 500, 0.9),
    (" แต", 4000, 4200, 0.9), ("่", 4200, 4250, 0.9), ("ละ", 4250, 4500, 0.9),
]


def cues(*starts):
    return [{"text": "x", "start_ms": s, "end_ms": s + 500} for s in starts]


def test_score_matches_cue_starts_within_300ms():
    s = score(cues(0, 1000, 2000), cues(100, 1400, 2000, 2600))
    assert (s["ref"], s["hyp"], s["matched"], s["delta"]) == (3, 4, 2, 1)
    assert round(s["cue_ber"], 4) == round(1 - 2 * (2 / 4) * (2 / 3) / (2 / 4 + 2 / 3), 4)


def test_score_ignores_hyp_beyond_an_excerpt_recut():
    assert score(cues(0, 1000), cues(0, 1000, 60000))["hyp"] == 2


def test_replay_closes_gaps_without_touching_text_or_starts():
    config = load_config()
    base = baseline_settings(config)
    open_gaps = replay(WORDS, dict(base, max_close_gap_ms=0), config)
    closed = replay(WORDS, dict(base, max_close_gap_ms=5000), config)
    assert score(open_gaps, open_gaps)["gaps"] == 1
    assert score(closed, closed)["gaps"] == 0
    assert text_key(open_gaps) == text_key(closed) == "โอเคแต่ละ"
    assert [c["start_ms"] for c in open_gaps] == [c["start_ms"] for c in closed]


def test_find_words_picks_latest_job_with_matching_media_path():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE media (id INTEGER PRIMARY KEY, path TEXT);
        CREATE TABLE job (id INTEGER PRIMARY KEY, media_id INTEGER);
        CREATE TABLE engine_result (job_id INTEGER, engine_slot TEXT, raw_words_json TEXT);""")
    conn.execute("INSERT INTO media VALUES (1, 'F:\\Works\\CFD 9\\a.mp3'), (2, 'other.mp3')")
    conn.executemany("INSERT INTO job VALUES (?, ?)", [(1, 1), (2, 1), (3, 2)])
    for job_id, text in [(1, "old"), (2, "new"), (3, "z")]:
        raw = json.dumps([{"text": text, "start_ms": 0, "end_ms": 9, "confidence": None}])
        conn.execute("INSERT INTO engine_result VALUES (?, 'a', ?)", (job_id, raw))
    job_id, words = find_words(conn, "CFD 9/a.mp3")
    assert (job_id, words) == (2, [("new", 0, 9, None)])
    assert find_words(conn, "missing") is None
