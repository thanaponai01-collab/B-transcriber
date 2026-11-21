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
    assert r["cuts_in_sound"] == []
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
    got = [(e["clip"], e["side"], e["word"], e["cut_ms"]) for e in r["cuts_in_sound"]]
    assert got == [("A1@0", "out", "world", 300), ("A1@1", "in", "สวัสดี", 300)]


def test_tolerance_ignores_a_cut_inside_word_timing_noise(tmp_path):
    media = str(tmp_path / "a.mp4"); (tmp_path / "a.mp4").write_bytes(b"")
    r = run(timeline(clip("A1@0", 0, 900, 1980, media)))  # 20 ms short of "world"'s end
    assert r["cuts_in_sound"] == []
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
    tl = timeline(clip("A1@0", 0, 900, 2100, media), clip("A1@9", 9000, 900, 2100, media, reversed=True),
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


def test_tighten_pulls_word_edges_in_to_the_sound():
    import numpy as np
    levels = np.full(100, -70.0, dtype=np.float32)  # 1 s of room tone at -70 dB (floor clamps to -65)
    levels[30:52] = -30.0                            # sound 300-520 ms
    words = [tt.SourceWord("ครับ", 100, 900, 0),     # engine span runs far into the pause
             tt.SourceWord("เงียบ", 600, 800, 0),    # nothing audible inside: left alone
             tt.SourceWord("นะ", 400, 400, 0)]       # zero length: left alone
    a, b, c = tt.tighten(words, levels)
    assert (a.start_ms, a.end_ms) == (300, 520)
    assert (b.start_ms, b.end_ms) == (600, 800)
    assert (c.start_ms, c.end_ms) == (400, 400)


def test_level_db_windows():
    import numpy as np
    audio = np.concatenate([np.zeros(160, np.float32), np.full(160, 0.5, np.float32)])
    levels = tt.level_db(audio, 16000)
    assert len(levels) == 2 and levels[0] < -150 and abs(levels[1] - (-6.02)) < 0.01


def test_edge_in_a_pause_inside_an_engine_word_is_not_a_bad_cut(tmp_path):
    import numpy as np
    media = str(tmp_path / "a.mp4"); (tmp_path / "a.mp4").write_bytes(b"")
    levels = np.full(800, -70.0, dtype=np.float32)
    levels[100:140] = -30.0   # 1.00-1.40 s sound
    levels[160:200] = -30.0   # 1.60-2.00 s sound; 1.40-1.60 is a pause
    words = [tt.SourceWord("helloworld", 1000, 2000, 0)]  # one engine word across the pause
    lookup = lambda m: (1, words, levels)
    pause = tt.build(timeline(clip("A1@0", 0, 900, 1500, media)), lookup=lookup)
    assert pause["cuts_in_sound"] == []
    sound = tt.build(timeline(clip("A1@0", 0, 900, 1300, media)), lookup=lookup)
    (edge,) = sound["cuts_in_sound"]
    assert edge["side"] == "out" and edge["cut_ms"] == 700
    assert edge["nearest_quiet_ms"] == 105  # the pause starts at 1.40 s; window centre 1.405


def test_rough_cut_maps_stored_source_transcripts_into_the_window(tmp_path, monkeypatch):
    from cutdeck import rough_cut, sequence_model
    media = tmp_path / "a.mp4"; media.write_bytes(b"")
    db = tmp_path / "t.db"; db.write_bytes(b"")
    clip_ = sequence_model.Clip(str(media), 0, 900 * T, 6800 * T, True)  # plays source 0.9-6.8 s at 0
    seq = sequence_model.Sequence(TPF, 5900 * T, (sequence_model.Track(0, False, (clip_,)),))
    monkeypatch.setattr(tt, "source_words", lambda m, d, levels_dir=None: (5, SOURCE, None))
    window = (30, 120)  # frames: 1.0-4.0 s on the sequence
    job_id, words, tokens = rough_cut._mapped_transcript(seq, None, window, {}, db)
    assert job_id == 5
    # "world" (source 1.5-2.0) is at sequence 0.6-1.1 s: clamped to 0..100 ms in the window's WAV.
    assert [(w.text, w.start_ms, w.end_ms) for w in words] == [
        ("world", 0, 100), ("สวัสดี", 1100, 1700), ("ครับ", 1700, 2100)]
    assert [t.text for t in tokens] == ["world", "สวัสดีครับ"]
    monkeypatch.setattr(tt, "source_words", lambda m, d, levels_dir=None: None)
    assert rough_cut._mapped_transcript(seq, None, window, {}, db) is None


def test_speed_changed_clip_maps_through_premieres_scaled_in_out(tmp_path):
    media = str(tmp_path / "a.mp4"); (tmp_path / "a.mp4").write_bytes(b"")
    # 200% over source 0.9-2.1 s: Premiere reads In 0.45 s, Out 1.05 s, 0.6 s long on the sequence.
    c = clip("A1@0", 0, 450, 1050, media, speed=2)
    r = run(timeline(c))
    (line,) = r["lines"]
    assert line["text"] == "hello world"
    assert int(line["start_ticks"]) == 50 * T and int(line["end_ticks"]) == 550 * T  # (1000-900)/2, (2000-900)/2


def test_cut_into_an_onset_the_engine_timed_late_is_flagged(tmp_path):
    import numpy as np
    media = str(tmp_path / "a.mp4"); (tmp_path / "a.mp4").write_bytes(b"")
    levels = np.full(800, -70.0, dtype=np.float32)
    levels[92:140] = -30.0                           # sound from 0.92 s; the engine says 1.00 s
    words = [tt.SourceWord("รัสเซลล์", 1000, 1400, 0)]
    r = tt.build(timeline(clip("A1@0", 0, 950, 1500, media)), lookup=lambda m: (1, words, levels))
    (edge,) = r["cuts_in_sound"]
    assert edge["side"] == "in" and edge["word"] is None and edge["nearest_quiet_ms"] < 0
    assert edge["severity"] == "sound"
    quiet = tt.build(timeline(clip("A1@0", 0, 850, 1500, media)), lookup=lambda m: (1, words, levels))
    assert quiet["cuts_in_sound"] == []


def test_tighten_grows_an_edge_into_the_pause_to_meet_sound_the_engine_left_out():
    import numpy as np
    levels = np.full(300, -70.0, dtype=np.float32)
    levels[92:140] = -30.0        # sound 0.92-1.40 s; the engine says 1.00-1.30
    levels[200:250] = -30.0       # next word's sound 2.00-2.50 s
    levels[60:62] = -30.0         # a click at 0.60 s, apart from the word: not reached
    words = [tt.SourceWord("รัส", 1000, 1300, 0), tt.SourceWord("เซลล์", 2000, 2500, 0)]
    a, b = tt.tighten(words, levels)
    assert (a.start_ms, a.end_ms) == (920, 1400)
    assert (b.start_ms, b.end_ms) == (2000, 2500)
    # Growth stops at the neighbour: sound running between two words is not taken across.
    levels[140:200] = -30.0
    a, b = tt.tighten(words, levels)
    assert a.end_ms <= b.start_ms


def test_corrections_replace_a_cues_words_and_mark_the_line(tmp_path):
    media = str(tmp_path / "a.mp4"); (tmp_path / "a.mp4").write_bytes(b"")
    same = tt.apply_corrections(SOURCE, {0: "hello there"})        # 2 words for 2: times kept
    assert [(w.text, w.start_ms, w.end_ms, w.corrected) for w in same[:2]] == [
        ("hello", 1000, 1400, True), ("there", 1500, 2000, True)]
    spread = tt.apply_corrections(SOURCE, {2: "ลาก่อนนะ"})           # "bye" -> 2+ Thai words over 6.0-6.5 s
    thai = [w for w in spread if w.cue == 2]
    assert thai[0].start_ms == 6000 and thai[-1].end_ms == 6500 and all(w.corrected for w in thai)
    gone = tt.apply_corrections(SOURCE, {2: "  "})
    assert all(w.cue != 2 for w in gone)
    r = tt.build(timeline(clip("A1@0", 0, 0, 7000, media)), lookup=lambda m: (1, same))
    assert r["lines"][0]["text"] == "hello there" and r["lines"][0]["corrected"] is True
    assert "corrected" not in r["lines"][1]


def test_source_words_reads_the_store_and_its_corrections(tmp_path):
    from transcribe.db import store
    media = tmp_path / "a.wav"; media.write_bytes(b"not really audio")
    db = tmp_path / "t.db"
    store.init_db(db)
    conn = store.connect(db)
    media_id = store.create_media(conn, str(media))
    job_id = store.create_job(conn, media_id, "faster_whisper", "passthrough", "v1")
    store.create_token(conn, job_id, 0, "สวัสดีครับ", 1000, 2000, "thai", None, "a")
    store.create_token(conn, job_id, 1, "ไปละ", 3000, 3500, "thai", None, "a")
    store.create_correction(conn, job_id, 1, "ไปละ", "ไปแล้ว", "a")
    conn.execute("UPDATE job SET status='done', job_phase='written' WHERE id=?", (job_id,))
    conn.commit(); conn.close()
    got_job, words, levels, gaps = tt.source_words(str(media), db)
    assert got_job == job_id and levels is None and gaps == []
    assert [(w.text, w.corrected) for w in words] == [("สวัสดีครับ", False), ("ไป", True), ("แล้ว", True)]
    assert (words[1].start_ms, words[2].end_ms) == (3000, 3500)
    assert tt.source_words(str(media), db)[0] == job_id  # sha256 now comes from the index


def test_untranscribed_speech_is_mapped_and_everything_filters_by_range(tmp_path):
    import numpy as np
    media = str(tmp_path / "a.mp4"); (tmp_path / "a.mp4").write_bytes(b"")
    levels = np.full(800, -70.0, dtype=np.float32)
    levels[440:460] = -30.0                     # sound at 4.4-4.6 s, where clip A1@1 starts
    gaps = [(4500, 5200)]                       # the VAD heard speech no cue covers
    lookup = lambda m: (1, SOURCE, levels, gaps)
    tl = timeline(clip("A1@0", 0, 900, 2100, media), clip("A1@1", 3000, 4500, 6800, media))
    r = tt.build(tl, lookup=lookup)
    (u,) = r["untranscribed"]
    assert u["clip"] == "A1@1" and (u["start_s"], u["end_s"]) == (3.0, 3.7)
    assert any(e["clip"] == "A1@1" for e in r["cuts_in_sound"])
    early = tt.build(tl, lookup=lookup, from_ticks=0, to_ticks=2000 * T)
    assert early["untranscribed"] == [] and all(e["at_s"] < 2 for e in early["cuts_in_sound"])


def test_a_track_that_repeats_a_lower_tracks_clip_is_warned_as_a_later_stream(tmp_path):
    media = str(tmp_path / "a.mp4"); (tmp_path / "a.mp4").write_bytes(b"")
    c = clip("A1@0", 0, 900, 2100, media)
    tl = timeline(c)
    tl["tracks"].append({"id": "A2", "kind": "audio", "muted": False, "clips": [dict(c, id="A2@0")]})
    assert "warnings" not in run(tl)
    (warning,) = run(tl, track="A2")["warnings"]
    assert "A2@0" in warning and "later audio stream" in warning


def test_rough_cut_transcribes_a_mostly_used_source_once_instead_of_its_wav(tmp_path, monkeypatch):
    from cutdeck import rough_cut, sequence_model
    media = tmp_path / "a.mp4"; media.write_bytes(b"")
    db = tmp_path / "t.db"; db.write_bytes(b"")
    clip_ = sequence_model.Clip(str(media), 0, 900 * T, 6800 * T, True)  # 5.9 s of the file
    seq = sequence_model.Sequence(TPF, 5900 * T, (sequence_model.Track(0, False, (clip_,)),))
    stored = []
    monkeypatch.setattr(tt, "source_words", lambda m, d, levels_dir=None: (5, SOURCE, None) if stored else None)
    monkeypatch.setattr(rough_cut, "_transcribe_source", lambda m, d: stored.append(m))
    monkeypatch.setattr(rough_cut, "_media_seconds", lambda m: 60.0)      # 5.9 of 60 s: too little
    assert rough_cut._mapped_transcript(seq, None, None, {}, db, transcribe_sources=True) is None
    assert stored == []
    monkeypatch.setattr(rough_cut, "_media_seconds", lambda m: 8.0)       # 5.9 of 8 s: transcribe it
    job_id, words, tokens = rough_cut._mapped_transcript(seq, None, None, {}, db, transcribe_sources=True)
    assert stored == [str(media)] and job_id == 5 and tokens


def test_timeline_from_a_saved_project_maps_like_the_live_read(tmp_path):
    media = str(tmp_path / "a.mp4"); (tmp_path / "a.mp4").write_bytes(b"")
    seq = {"name": "saved", "audio_tracks": [
        {"index": 0, "muted": False, "clips": [
            {"start": 0.0, "end": 1.2, "source_in": 0.9, "source_out": 2.1, "disabled": False, "media_path": media},
            {"start": 1.2, "end": 1.8, "source_in": 2.9, "source_out": 4.1, "disabled": False, "media_path": media},  # 200%
            {"start": 5.0, "end": 6.0, "source_in": 0.0, "source_out": 1.0, "disabled": True, "media_path": media}]}]}
    tl = tt.timeline_from_prproj(seq, fps=30)
    assert tl["ticks_per_frame"] == str(TPF)
    r = run(tl)
    assert [ln["text"] for ln in r["lines"]] == ["hello world", "สวัสดีครับ"]
    assert int(r["lines"][1]["start_ticks"]) == 1200 * T + 50 * T   # (3000 - 2900) / 2 after the clip start
    assert [s["reason"] for s in r["skipped"]] == ["disabled"]


def test_clipped_flag_needs_sound_at_the_edge_when_levels_are_known(tmp_path):
    import numpy as np
    media = str(tmp_path / "a.mp4"); (tmp_path / "a.mp4").write_bytes(b"")
    levels = np.full(800, -70.0, dtype=np.float32)
    levels[100:140] = -30.0; levels[160:200] = -30.0       # a pause 1.40-1.60 inside one engine word
    words = [tt.SourceWord("helloworld", 1000, 2000, 0)]
    quiet = tt.build(timeline(clip("A1@0", 0, 900, 1500, media)), lookup=lambda m: (1, words, levels))
    assert "clipped_words" not in quiet["lines"][0]
    loud = tt.build(timeline(clip("A1@0", 0, 900, 1300, media)), lookup=lambda m: (1, words, levels))
    assert loud["lines"][0]["clipped_words"] == ["helloworld"]


def test_tighten_keeps_exact_times_where_an_edge_does_not_move():
    import numpy as np
    levels = np.full(30, -30.0, dtype=np.float32)   # sound throughout: nothing to pull in, no pause
    words = [tt.SourceWord("a", 50, 103, 0), tt.SourceWord("b", 105, 108, 0), tt.SourceWord("c", 109, 200, 0)]
    got = [(w.start_ms, w.end_ms) for w in tt.tighten(words, levels)]
    assert got[1] == (105, 108) and got[2][1] >= 200
    assert all(a[1] <= b[0] for a, b in zip(got, got[1:]))


def test_a_through_edit_is_not_a_cut_and_range_filters_on_exact_ticks(tmp_path):
    import numpy as np
    media = str(tmp_path / "a.mp4"); (tmp_path / "a.mp4").write_bytes(b"")
    levels = np.full(800, -70.0, dtype=np.float32)
    levels[:400] = -30.0                                       # sound through the first 4 s
    lookup = lambda m: (1, SOURCE, levels)
    split = timeline(clip("A1@0", 0, 900, 1700, media), clip("A1@1", 800, 1700, 2100, media))  # razor at 0.8 s
    r = tt.build(split, lookup=lookup)
    assert {(e["clip"], e["side"]) for e in r["cuts_in_sound"]} == {("A1@0", "in"), ("A1@1", "out")}
    assert "clipped_words" not in r["lines"][0]
    edge = TPF  # an edge exactly one frame in
    tl = timeline(clip("A1@x", edge, 900, 1700, media))
    tl["tracks"][-1]["clips"][0]["start_ticks"] = str(edge)
    tl["tracks"][-1]["clips"][0]["end_ticks"] = str(edge + 800 * T)
    hit = tt.build(tl, lookup=lookup, from_ticks=edge, to_ticks=edge + 1)
    assert [e["side"] for e in hit["cuts_in_sound"]] == ["in"]


def test_a_half_written_levels_cache_is_decoded_again(tmp_path, monkeypatch):
    import numpy as np
    cache = tmp_path / "x.npy"; cache.write_bytes(b"\x93NUMPY broken")
    class P:
        returncode = 0
        def __init__(self, *a, **k): self.stdout = __import__("io").BytesIO(np.zeros(1600, np.float32).tobytes())
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr("subprocess.Popen", P)
    monkeypatch.setattr("shutil.which", lambda name: "ffmpeg")
    levels = tt.source_levels("a.mp4", cache)
    assert len(levels) == 10 and np.load(cache).shape == (10,)
