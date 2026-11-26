"""hks_piece_ends lists every body piece end and checks a do-confirm answer against that list."""

from cutdeck.hks_piece_ends import check_answers, piece_ends
from cutdeck.timeline_transcript import SourceWord

SRC = "G:\\day\\show.mp4"


def clip(start, end, src_in):
    return {"start": start, "end": end, "source_in": src_in, "source_out": src_in + end - start,
            "disabled": False, "media_path": SRC}


def word(text, a, b):
    return SourceWord(text, int(a * 1000), int(b * 1000), 0)


# Running speech over source 0-6 s ending on "ก็" at 5 s; a finished line at 100-103.5 s, then a pause.
WORDS = [word(f"w{i}", i * 0.5, i * 0.5 + 0.5) for i in range(9)] + [word("ก็", 4.5, 5.0), word("x", 5.0, 6.0)] + \
        [word("ครับ", 103.0, 103.5), word("y", 104.0, 104.5)]
SOURCES = {SRC: (WORDS, None)}


def test_lists_one_end_per_jump_with_through_edits_merged():
    a1 = [clip(0, 3, 100), clip(3, 3.5, 103), clip(3.5, 8.5, 0)]  # 100-103 and 103-103.5 play on
    ends = piece_ends(a1, SOURCES)
    assert [(e["at_s"], e["src_s"]) for e in ends] == [(3.5, 103.5), (8.5, 5.0)]
    assert ends[0]["last_words"].endswith("ครับ")


def test_flags_an_end_in_running_speech_on_a_connective():
    end = piece_ends([clip(0, 5, 0)], SOURCES)[0]
    assert end["in_speech"] and end["continuation"] == "ก็"


def test_an_end_in_a_pause_is_not_flagged():
    end = piece_ends([clip(0, 3.5, 100)], SOURCES)[0]
    assert not end["in_speech"] and end["continuation"] is None


def test_ends_before_the_body_are_left_out():
    assert [e["src_s"] for e in piece_ends([clip(0, 3.5, 100), clip(3.5, 8.5, 0)], SOURCES, body_from=3.5)] == [5.0]


def test_every_end_needs_a_verdict():
    ends = piece_ends([clip(0, 3.5, 100), clip(3.5, 8.5, 0)], SOURCES)
    assert len(check_answers(ends, {103.5: {"verdict": "finished"}})) == 1
    assert check_answers(ends, {103.5: {"verdict": "finished"}, 5.0: {"verdict": "unfinished"}}) == []


def test_finished_on_a_flagged_end_needs_a_reason():
    ends = piece_ends([clip(0, 5, 0)], SOURCES)
    assert "no reason" in check_answers(ends, {5.0: {"verdict": "finished"}})[0]
    assert check_answers(ends, {5.0: {"verdict": "finished", "reason": "the host cuts in"}}) == []
