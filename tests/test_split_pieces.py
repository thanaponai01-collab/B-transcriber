"""split_pieces: each clip on the split's keeper track is one question, its colour who answers."""
from cutdeck.split_pieces import pieces

S = 254016000000
FRAME_25 = S // 25


def _clip(start, end, label=None):
    return {"start": start, "end": end, **({"label": label} if label is not None else {})}


SPLIT = {"name": "Editing", "video_tracks": [
    {"clips": [_clip(0, 22.48, 14), _clip(967.52, 1026.04, 14)]},  # drops stay on V1
    {"clips": [_clip(205.44, 360.96, 1), _clip(61.4, 205.44, 8), _clip(1026.04, 1039.88, 1),
               _clip(360.96, 967.52, 4), _clip(1039.88, 1050.0, 7)]},
]}


def test_each_keeper_clip_is_a_question_with_its_colour_in_timeline_order():
    got = pieces(SPLIT, fps=25)
    assert [(p["n"], p["colour"], p["meaning"]) for p in got] == [
        (1, "green", "host"), (2, "pink", "first guest"), (3, "blue", "lawyer"),
        (4, "pink", "first guest"), (5, "teal", "caller")]
    assert (got[0]["from_ticks"], got[0]["to_ticks"]) == (str(1535 * FRAME_25), str(5136 * FRAME_25))
    assert got[0]["start_tc"] == "00:01:01:10"


def test_after_drop_marks_a_piece_that_follows_dropped_material():
    assert [p["after_drop"] for p in pieces(SPLIT, fps=25)] == [False, False, False, True, False]


def test_an_unlabelled_or_unknown_colour_has_no_meaning():
    seq = {"name": "Edit", "video_tracks": [{"clips": []}, {"clips": [_clip(0, 1), _clip(1, 2, 12)]}]}
    assert [(p["colour"], p["meaning"]) for p in pieces(seq, fps=25)] == [(None, None), ("grey", None)]


def test_a_sequence_without_the_keeper_track_is_refused():
    try:
        pieces({"name": "YT", "video_tracks": [{"clips": []}]}, fps=25)
    except ValueError as e:
        assert "V2" in str(e)
    else:
        raise AssertionError("read a sequence with no V2")
