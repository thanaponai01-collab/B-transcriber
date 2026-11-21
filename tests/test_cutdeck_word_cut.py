"""Cut by words: cuts land in the pauses around the removed words, in whole frames."""
import pytest

from cutdeck import word_cut
from cutdeck.timeline_transcript import TimelineWord

MS = 254016000
TPF = 8467200000  # 30 fps: 33.3 ms


def w(text, s, e):
    return TimelineWord(text, s * MS, e * MS, "A1@0", "a.mp4", s, e, 0, None)


# "one" 0.0-0.4, pause 600 ms, "two three" 1.0-1.8, pause 400 ms, "four" 2.2-2.6, "five" 2.6-3.0
WORDS = [w("one", 0, 400), w("two", 1000, 1400), w("three", 1400, 1800), w("four", 2200, 2600),
         w("five", 2600, 3000)]
END = 4000 * MS


def frames_s(cut):
    return [round(f * TPF / MS) for f in cut]


def test_cut_sits_in_the_pauses_and_keeps_a_natural_pause():
    p = word_cut.plan(WORDS, [{"text": "two three"}], TPF, END, keep_ms=250)
    (cut,) = p["cuts_frames"]
    a, b = frames_s(cut)
    assert 400 <= a <= 1000 and 1800 <= b <= 2200          # never into "one" or "four"
    kept_pause = (a - 400) + (2200 - b)
    assert 200 <= kept_pause <= 300                          # ~250 ms left at the join
    assert p["removals"][0]["pause_before_ms"] == 600 and p["removals"][0]["pause_after_ms"] == 400


def test_touching_words_cut_exactly_at_the_boundary_and_are_flagged_tight():
    p = word_cut.plan(WORDS, [{"text": "four"}], TPF, END)
    a, b = frames_s(p["cuts_frames"][0])
    assert 1800 <= a <= 2200 and b <= 2600 + 34              # ends at "five"'s start, within a frame
    assert p["removals"][0]["tight"] is True


def test_occurrence_and_errors():
    words = WORDS + [w("two", 3500, 3700)]
    with pytest.raises(ValueError, match="said 2 times"):
        word_cut.plan(words, [{"text": "two"}], TPF, END)
    p = word_cut.plan(words, [{"text": "two", "occurrence": 2}], TPF, END)
    assert frames_s(p["cuts_frames"][0])[0] >= 3000
    with pytest.raises(ValueError, match="not said"):
        word_cut.plan(WORDS, [{"text": "six"}], TPF, END)


def test_tick_span_and_overlapping_removals_merge():
    p = word_cut.plan(WORDS, [{"from_ticks": 950 * MS, "to_ticks": 1450 * MS}, {"text": "three"}], TPF, END)
    assert len(p["cuts_frames"]) == 1


def test_count():
    assert word_cut.count(WORDS, "two three") == 1 and word_cut.count(WORDS, "six") == 0


def test_a_phrase_inside_a_longer_word_is_not_cut():
    words = WORDS + [w("ten", 3500, 3700)]
    with pytest.raises(ValueError, match="inside longer words"):
        word_cut.plan(WORDS, [{"text": "hre"}], TPF, END)          # inside "three"
    p = word_cut.plan(words + [w("te", 3800, 3900)], [{"text": "te"}], TPF, END)  # "ten" skipped
    assert frames_s(p["cuts_frames"][0])[0] >= 3700


def test_cut_moves_to_the_quiet_frame_in_the_pause():
    # Sound in the pause after "one" until 0.75 s (a breath the engine did not time).
    level_at = lambda ticks: 10.0 if ticks < 750 * MS or 1000 * MS <= ticks < 1800 * MS else -10.0
    p = word_cut.plan(WORDS, [{"text": "two three"}], TPF, END, keep_ms=250, level_at=level_at)
    a, b = frames_s(p["cuts_frames"][0])
    assert a >= 750 and b >= 1800 and "no_quiet" not in p["removals"][0]
    loud = word_cut.plan(WORDS, [{"text": "two three"}], TPF, END, level_at=lambda t: 5.0)
    assert loud["removals"][0]["no_quiet"] == ["start", "end"]
