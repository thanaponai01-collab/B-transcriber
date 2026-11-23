"""5.3 bleeps (cutdeck/hks_bleep.py): swears in kept speech, never Thai compounds that contain one."""

from cutdeck import hks_bleep as b


def test_a_swear_split_across_pieces_is_found_inside_a_keep_only():
    words = [[0.0, 0.3, "ไอ้"], [0.3, 0.6, "เหี้"], [0.6, 0.9, "ย"], [5.0, 5.4, "แม่ง"]]
    assert b.proposals(words, [(0.0, 2.0)]) == [(0.3, 0.9, "เหี้ย")]


def test_compounds_are_not_swears():
    for text in ("ผู้เชี่ยวชาญ", "คนรักสัตว์", "ขี้เหี้ยว"):
        assert b.matches([[0.0, 1.0, text]]) == []
    assert b.matches([[0.0, 1.0, "ไอ้สัตว์"]]) == [(0.0, 1.0, "ไอ้สัตว์")]
