"""Step 2.1 coverage check: a kept stretch of speech must have words under it."""
from cutdeck.hks_words import LONG_KEEP, MIN_COVERED, coverage

A = "a.mp4"


def test_every_long_keep_with_a_word_passes():
    words = {A: [[10.0, 10.4, "x"], [30.0, 30.5, "y"]]}
    r = coverage([(A, 9.0, 12.0), (A, 29.0, 31.0)], words)
    assert (r["keeps"], r["holes"], r["covered"], r["pass"]) == (2, [], 1.0, True)


def test_a_keep_with_no_word_is_a_hole():
    words = {A: [[10.0, 10.4, "x"]]}
    r = coverage([(A, 9.0, 12.0), (A, 50.0, 55.0)], words)
    assert r["holes"] == [[A, 50.0, 55.0]]
    assert r["covered"] == 0.5 and r["pass"] is False


def test_short_keeps_are_not_counted():
    r = coverage([(A, 9.0, 10.5)], {A: []})
    assert r["keeps"] == 0 and r["pass"] is False  # nothing to judge is not a pass


def test_words_of_another_file_do_not_count():
    r = coverage([("b.mp4", 9.0, 12.0)], {A: [[10.0, 10.4, "x"]]})
    assert r["holes"] == [["b.mp4", 9.0, 12.0]]


def test_a_word_only_touching_the_edge_does_not_count():
    r = coverage([(A, 9.0, 12.0)], {A: [[12.0, 12.3, "x"], [8.5, 9.0, "y"]]})
    assert r["holes"] == [[A, 9.0, 12.0]]


def test_bar_is_97_percent():
    keeps = [(A, i * 10.0, i * 10.0 + 3) for i in range(100)]
    words = {A: [[i * 10.0 + 1, i * 10.0 + 1.2, "w"] for i in range(97)]}
    assert coverage(keeps, words)["pass"] is True
    words = {A: [[i * 10.0 + 1, i * 10.0 + 1.2, "w"] for i in range(96)]}
    assert coverage(keeps, words)["pass"] is False
    assert MIN_COVERED == 0.97


def test_one_long_hole_fails_even_above_the_bar():
    keeps = [(A, i * 10.0, i * 10.0 + 3) for i in range(100)] + [(A, 2000.0, 2000.0 + LONG_KEEP)]
    words = {A: [[i * 10.0 + 1, i * 10.0 + 1.2, "w"] for i in range(100)]}
    r = coverage(keeps, words)
    assert r["covered"] > MIN_COVERED and r["pass"] is False
