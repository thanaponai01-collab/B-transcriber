"""hks_cut_check finds the agent's own HKS cut mistakes in a saved sequence (rules.md, Trims and split edits)."""

from cutdeck.hks_cut_check import check
from cutdeck.timeline_transcript import SourceWord

SRC = "G:\\day\\show.mp4"
BROLL = "G:\\day\\broll.mp4"


def clip(start, end, src_in, media=SRC):
    return {"name": "x", "start": start, "end": end, "source_in": src_in, "source_out": src_in + end - start,
            "disabled": False, "media_path": media}


def word(text, a, b):
    return SourceWord(text, int(a * 1000), int(b * 1000), 0)


# Someone talks without a pause over source 2-8 s and 98-104 s; quiet elsewhere.
WORDS = [word(f"w{i}", i * 0.5, i * 0.5 + 0.5) for i in range(4, 16)] + \
        [word(f"v{i}", 98 + i * 0.5, 98 + i * 0.5 + 0.5) for i in range(12)]
SOURCES = {SRC: (WORDS, None)}


def seq(video, audio):
    return {"name": "t", "video_tracks": [{"clips": v} for v in video], "audio_tracks": [{"clips": audio}]}


def test_a_straight_cut_mid_speech_in_plain_view_is_listed_on_both_sides():
    audio = [clip(0, 5, 0), clip(5, 10, 100)]
    r = check(seq([[clip(0, 5, 0), clip(5, 10, 100)]], audio), SOURCES)
    assert [(e["side"], e["src_s"]) for e in r["visible_cuts_in_speech"]] == [("out", 5.0), ("in", 100.0)]
    assert r["same_frame_cuts"] == [5.0]


def test_the_same_cut_under_a_cover_is_hidden():
    audio = [clip(0, 5, 0), clip(5, 10, 100)]
    r = check(seq([[clip(0, 5, 0), clip(5, 10, 100)], [clip(4, 6, 0, BROLL)]], audio), SOURCES)
    assert r["visible_cuts_in_speech"] == []
    assert r["same_frame_cuts"] == []


def test_a_j_cut_whose_held_picture_shows_someone_talking_is_unsafe():
    # The outgoing picture plays 1 s past the sound cut at 5 s: source 5-6 s, where w10, w11 are said.
    audio = [clip(0, 5, 0), clip(5, 10, 100)]
    r = check(seq([[clip(0, 6, 0), clip(6, 10, 101)]], audio), SOURCES)
    assert len(r["unsafe_holds"]) == 1
    assert r["unsafe_holds"][0]["words_in_picture"] == "w10w11"
    assert r["same_frame_cuts"] == []


def test_a_j_cut_held_on_a_silent_picture_is_safe():
    words = [w for w in WORDS if not 5 <= w.start_ms / 1000 < 6]
    audio = [clip(0, 5, 0), clip(5, 10, 100)]
    r = check(seq([[clip(0, 6, 0), clip(6, 10, 101)]], audio), {SRC: (words, None)})
    assert r["unsafe_holds"] == []


def test_a_cover_never_in_sync_is_not_a_hold():
    audio = [clip(0, 10, 0)]
    r = check(seq([[clip(0, 10, 0)], [clip(2, 8, 98)]], audio), SOURCES)
    assert r["unsafe_holds"] == []


def test_a_cut_in_a_gap_between_words_is_a_pause_even_without_quiet_audio():
    # 0.3 s between w9 (ends 5.0) and the next word: a cut at 5.0 sits in a pause.
    words = [w for w in WORDS if w.start_ms < 5000] + [word("x", 5.3, 5.8)] + [w for w in WORDS if w.start_ms >= 98000]
    audio = [clip(0, 5, 0), clip(5, 10, 100)]
    r = check(seq([[clip(0, 5, 0), clip(5, 10, 100)]], audio), {SRC: (words, None)})
    assert [e["side"] for e in r["visible_cuts_in_speech"]] == ["in"]
