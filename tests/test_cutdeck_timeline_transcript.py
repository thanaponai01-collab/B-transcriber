"""Timeline transcript: source words mapped through hand-built clip lists, in exact ticks."""
from types import SimpleNamespace

import pytest

from cutdeck import timeline_transcript as tt

T = tt.TICKS_PER_MS  # ticks per millisecond
TPF = 8467200000     # 30 fps


def clip(cid, start_ms, in_ms, out_ms, media="a.mp4", **extra):
    return {"id": cid, "start_ticks": str(start_ms * T), "end_ticks": str((start_ms + out_ms - in_ms) * T),
            "in_ticks": str(in_ms * T), "out_ticks": str(out_ms * T), "media": media,
            "disabled": False, "speed": 1, "reversed": False, **extra}


def timeline(*clips, muted=False, extra_tracks=()):
    return {"name": "seq", "sequence_id": "x", "ticks_per_frame": str(TPF),
            "tracks": [{"id": "V1", "kind": "video", "clips": []}, *extra_tracks,
                       {"id": "A1", "kind": "audio", "muted": muted, "clips": list(clips)}]}


# Source: three cues. "hello world" 1.0-2.0 s, "สวัสดี ครับ" 3.0-4.0 s, "bye" 6.0-6.5 s.
WORDS = [("hello", 1000, 1400), ("world", 1500, 2000), ("สวัสดี", 3000, 3600), ("ครับ", 3600, 4000),
         ("bye", 6000, 6500)]
CUES = [{"text": "hello world", "start_ms": 1000, "end_ms": 2000},
        {"text": "สวัสดีครับ", "start_ms": 3000, "end_ms": 4000},
        {"text": "bye", "start_ms": 6000, "end_ms": 6500}]
SOURCE = tt.source_word_list([SimpleNamespace(text=t, start_ms=s, end_ms=e) for t, s, e in WORDS], CUES)


def run(tl, **kw):
    return tt.build(tl, lookup=lambda media: (7, SOURCE), **kw)


def test_reorder_maps_each_piece_to_its_place(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"")
    media = str(tmp_path / "a.mp4")
    # "bye" first at 0, then "hello world" at 1 s: a reordered rough cut.
    r = run(timeline(clip("A1@0", 0, 5800, 6800, media), clip("A1@1", 1000, 800, 2200, media)))
    assert [ln["text"] for ln in r["lines"]] == ["bye", "hello world"]
    bye, hello = r["lines"]
    assert int(bye["start_ticks"]) == 200 * T            # 6000 - 5800
    assert int(hello["start_ticks"]) == (1000 + 200) * T  # 1000 - 800 after the clip start
    assert int(hello["end_ticks"]) == (1000 + 1200) * T
    assert hello["src_s"] == [1.0, 2.0]
    assert r["edges_inside_words"] == []
    assert r["missing"] == [] and r["sources"] == [{"media": media, "transcript_job_id": 7}]


def test_same_source_twice(tmp_path):
    media = str(tmp_path / "a.mp4"); (tmp_path / "a.mp4").write_bytes(b"")
    r = run(timeline(clip("A1@0", 0, 2900, 4100, media), clip("A1@1", 5000, 2900, 4100, media)))
    assert [ln["text"] for ln in r["lines"]] == ["สวัสดีครับ", "สวัสดีครับ"]
    assert [ln["clip"] for ln in r["lines"]] == ["A1@0", "A1@1"]


def test_cut_through_a_word_is_flagged_and_reported(tmp_path):
    media = str(tmp_path / "a.mp4"); (tmp_path / "a.mp4").write_bytes(b"")
    # Out at 1.7 s cuts "world" (1.5-2.0) 300 ms short; In at 3.3 s cuts the head of "สวัสดี".
    r = run(timeline(clip("A1@0", 0, 900, 1700, media), clip("A1@1", 800, 3300, 4100, media)))
    assert r["lines"][0]["clipped_words"] == ["world"]
    assert int(r["lines"][0]["end_ticks"]) == 800 * T   # the word stops where the clip stops
    assert r["lines"][1]["clipped_words"] == ["สวัสดี"]
    got = [(e["clip"], e["side"], e["word"], e["cut_ms"]) for e in r["edges_inside_words"]]
    assert got == [("A1@0", "out", "world", 300), ("A1@1", "in", "สวัสดี", 300)]


def test_tolerance_ignores_a_cut_inside_word_timing_noise(tmp_path):
    media = str(tmp_path / "a.mp4"); (tmp_path / "a.mp4").write_bytes(b"")
    r = run(timeline(clip("A1@0", 0, 900, 1980, media)))  # 20 ms short of "world"'s end
    assert r["edges_inside_words"] == []
    assert "clipped_words" not in r["lines"][0]


def test_cue_split_by_a_cut_becomes_two_lines_and_cut_away_words_are_gone(tmp_path):
    media = str(tmp_path / "a.mp4"); (tmp_path / "a.mp4").write_bytes(b"")
    # Keep "hello" and "bye"; "world" and the Thai cue are cut away.
    r = run(timeline(clip("A1@0", 0, 900, 1450, media), clip("A1@1", 550, 5900, 6600, media)))
    assert [ln["text"] for ln in r["lines"]] == ["hello", "bye"]


def test_find_spans_a_cut_and_ignores_spaces(tmp_path):
    media = str(tmp_path / "a.mp4"); (tmp_path / "a.mp4").write_bytes(b"")
    r = run(timeline(clip("A1@0", 0, 900, 2100, media), clip("A1@1", 1200, 2900, 4100, media)),
            query="world สวัสดี")
    (m,) = r["matches"]
    assert m["clips"] == ["A1@0", "A1@1"]
    assert int(m["start_ticks"]) == 600 * T and int(m["end_ticks"]) == (1200 + 700) * T
    assert m["text"] == "world สวัสดี"


def test_gap_track_choice_and_skips(tmp_path):
    media = str(tmp_path / "a.mp4"); (tmp_path / "a.mp4").write_bytes(b"")
    other = {"id": "A2", "kind": "audio", "muted": False, "clips": []}
    tl = timeline(clip("A1@0", 0, 900, 2100, media), clip("A1@9", 9000, 900, 2100, media, speed=2),
                  clip("A1@20", 20000, 900, 2100, media, disabled=True))
    tl["tracks"].append(other)
    r = run(tl)
    assert r["track"] == "A1" and r["clips"] == 1
    assert [s["clip"] for s in r["skipped"]] == ["A1@9", "A1@20"]
    with pytest.raises(ValueError, match="no audio track A7"):
        run(tl, track="A7")


def test_missing_transcript_and_offline_media_are_listed(tmp_path):
    media = str(tmp_path / "a.mp4"); (tmp_path / "a.mp4").write_bytes(b"")
    r = tt.build(timeline(clip("A1@0", 0, 900, 2100, media), clip("A1@1", 1200, 0, 500, "Z:/gone.mp4")),
                 lookup=lambda m: None)
    assert [m["media"] for m in r["missing"]] == [media, "Z:/gone.mp4"]
    assert r["lines"] == []


def test_paging_range_and_full_file(tmp_path):
    media = str(tmp_path / "a.mp4"); (tmp_path / "a.mp4").write_bytes(b"")
    tl = timeline(clip("A1@0", 0, 0, 7000, media))
    r = run(tl, limit=2, out_dir=tmp_path / "out")
    assert r["line_count"] == 3 and len(r["lines"]) == 2 and r["next_offset"] == 2
    assert (tmp_path / "out").exists() and r["full_path"].endswith("seq-A1.json")
    r = run(tl, from_ticks=2500 * T, to_ticks=5000 * T)
    assert [ln["text"] for ln in r["lines"]] == ["สวัสดีครับ"]


def test_timecode_and_join():
    assert tt.timecode(TPF * (30 * 61 + 5), TPF) == "00:01:01:05"
    assert tt.join_words(["Max", "Verstappen", "ชนะ", "F1"]) == "Max Verstappen ชนะ F1"


def test_latest_transcript_job_any_engine(tmp_path):
    from transcribe.db import store
    db = tmp_path / "t.db"
    store.init_db(db)
    conn = store.connect(db)
    media_id = store.create_media(conn, "x.mp4", sha256="abc")
    assert store.latest_transcript_job(conn, "abc") is None
    job_id = store.create_job(conn, media_id, "faster_whisper", "passthrough", "v1")
    store.create_token(conn, job_id, 0, "hi", 0, 100, "latin", None, "a")
    conn.execute("UPDATE job SET status='done', job_phase='written' WHERE id=?", (job_id,))
    conn.commit()
    assert store.latest_transcript_job(conn, "abc").id == job_id
    assert store.latest_transcript_job(conn, "other") is None


def test_zero_length_engine_word_is_kept_inside_and_dropped_outside(tmp_path):
    media = str(tmp_path / "a.mp4"); (tmp_path / "a.mp4").write_bytes(b"")
    words = tt.source_word_list([SimpleNamespace(text="นะ", start_ms=1500, end_ms=1500),
                                 SimpleNamespace(text="hello", start_ms=1000, end_ms=1500)], CUES[:1])
    keep = tt.build(timeline(clip("A1@0", 0, 900, 2100, media)), lookup=lambda m: (1, words))
    assert keep["lines"][0]["text"] == "hello นะ"
    gone = tt.build(timeline(clip("A1@0", 0, 1600, 2100, media)), lookup=lambda m: (1, words))
    assert gone["lines"] == []
