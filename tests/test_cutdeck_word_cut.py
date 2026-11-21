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
    assert loud["removals"][0]["no_quiet"] == {"start": 5.0, "end": 5.0}


def test_touching_words_cut_at_the_boundary_and_report_its_level():
    level_at = lambda t: 3.0
    p = word_cut.plan(WORDS, [{"text": "four"}], TPF, END, level_at=level_at)
    end = p["cuts_frames"][0][1]
    assert abs(end * TPF - 2600 * MS) <= TPF and p["removals"][0]["no_quiet"]["end"] == 3.0


def _src(words):
    from cutdeck.timeline_transcript import SourceWord
    return {"a.mp4": [SourceWord(w.text, w.src_start_ms, w.src_end_ms, 0) for w in words]}


def test_plan_pieces_places_edges_in_the_source_pauses_in_the_order_given():
    # On a rough cut "four" sits right after "two three" (pause removed); in the source the
    # pause 1.8-2.2 s is still there. The piece must use the source's pause.
    from dataclasses import replace
    rough = [replace(w(t, a, b), src_start_ms=s, src_end_ms=e) for t, a, b, s, e in
             [("two", 0, 400, 1000, 1400), ("three", 400, 800, 1400, 1800), ("four", 800, 1200, 2200, 2600)]]
    four, = word_cut.plan_pieces(rough, [{"text": "four"}], TPF, _src(WORDS))
    a, b = int(four["in_ticks"]) // MS, int(four["out_ticks"]) // MS
    assert 1800 <= a <= 2200 and 2200 - a >= 50           # starts in the source pause, ~60 ms before
    assert 2600 <= b <= 2600 + 34                          # "five" touches: ends at the boundary
    one, four2 = word_cut.plan_pieces(WORDS, [{"text": "one"}, {"text": "four"}], TPF, _src(WORDS))
    assert int(one["in_ticks"]) == 0 and 450 <= int(one["out_ticks"]) // MS <= 1000


def test_plan_pieces_with_no_pause_ends_at_the_word_boundary():
    level = lambda media, t: 8.0
    (piece,) = word_cut.plan_pieces(WORDS, [{"text": "four"}], TPF, _src(WORDS), level)
    assert abs(int(piece["out_ticks"]) - 2600 * MS) <= TPF and piece["no_quiet"]["end"] == 8.0


def test_plan_pieces_refuses_a_phrase_that_crosses_a_cut_in_its_source():
    from dataclasses import replace
    # "one" then "five" on this timeline, but 2.6 s apart in the source (the cut removed the middle).
    joined = [replace(w("one", 0, 400), src_start_ms=0, src_end_ms=400),
              replace(w("five", 400, 800), src_start_ms=2600, src_end_ms=3000)]
    with pytest.raises(ValueError, match="not one stretch"):
        word_cut.plan_pieces(joined, [{"text": "one five"}], TPF, _src(WORDS))


def test_a_zero_length_last_word_is_removed_with_its_phrase():
    words = [w("ab", 200, 400), w("cd", 400, 400), w("ef", 900, 1200)]
    p = word_cut.plan(words, [{"text": "abcd"}], TPF, END)
    assert p["removals"][0]["pause_after_ms"] == 500   # measured from "cd" to "ef": cd was included


def test_a_pause_shorter_than_a_frame_takes_the_boundary_that_intrudes_least():
    # "x" ends at 1010 ms, "y" (removed) starts at 1020 ms: no frame boundary in the 10 ms pause.
    # Frame 30 = 1000 ms cuts 10 ms into the kept "x"; frame 31 = 1033 ms keeps 13 ms of "y".
    words = [w("x", 500, 1010), w("y", 1020, 1500), w("z", 1600, 2000)]
    p = word_cut.plan(words, [{"text": "y"}], TPF, END, keep_ms=0)
    assert p["cuts_frames"][0][0] == 30


def test_keep_ranges_keeps_the_phrases_in_place_and_cuts_the_rest():
    from cutdeck.timeline_transcript import Clip
    clips = [Clip("A1@0", 0, END, 0, END, "a.mp4")]
    r = word_cut.keep_ranges(WORDS, [{"text": "four"}, {"text": "one"}], TPF, clips, _src(WORDS))
    (one_a, one_b), (four_a, four_b) = r["keep_frames"]
    assert one_a == 0 and 400 <= one_b * TPF // MS <= 1000
    assert 1800 <= four_a * TPF // MS <= 2200 and four_b * TPF // MS <= 2600 + 34
    assert r["cuts_frames"] == [[one_b, four_a], [four_b, END // TPF]]


def test_keep_ranges_never_reaches_past_the_clip_holding_the_edge_word():
    from cutdeck.timeline_transcript import Clip
    from dataclasses import replace
    # A rough cut: clip 1 plays source 2.2-2.6 ("four") at 0; clip 2 plays source 0-0.4 ("one") at 0.4 s.
    clips = [Clip("A1@0", 0, 400 * MS, 2200 * MS, 2600 * MS, "a.mp4"),
             Clip("A1@1", 400 * MS, 800 * MS, 0, 400 * MS, "a.mp4")]
    words = [replace(w("four", 0, 400), clip="A1@0", src_start_ms=2200, src_end_ms=2600),
             replace(w("one", 400, 800), clip="A1@1", src_start_ms=0, src_end_ms=400)]
    r = word_cut.keep_ranges(words, [{"text": "one"}], TPF, clips, _src(WORDS))
    assert r["keep_frames"][0][0] * TPF >= 400 * MS   # the source pause before "one" is not on this timeline


def test_keep_ranges_cuts_to_the_end_of_the_sequence_not_of_the_track():
    from cutdeck.timeline_transcript import Clip
    clips = [Clip("A1@0", 0, END, 0, END, "a.mp4")]
    r = word_cut.keep_ranges(WORDS, [{"text": "one"}], TPF, clips, _src(WORDS), end_ticks=10 * END)
    assert r["cuts_frames"][-1][1] == -(-10 * END // TPF)


def test_keep_ranges_takes_a_span_across_rough_cut_joins_and_places_only_its_outer_edges():
    from cutdeck.timeline_transcript import Clip
    from dataclasses import replace
    # Rough cut: "one" (source 0-0.4) then "four five" (source 2.2-3.0) back to back.
    clips = [Clip("A1@0", 0, 400 * MS, 0, 400 * MS, "a.mp4"),
             Clip("A1@1", 400 * MS, 1200 * MS, 2200 * MS, 3000 * MS, "a.mp4")]
    words = [replace(w("one", 0, 400), clip="A1@0", src_start_ms=0, src_end_ms=400),
             replace(w("four", 400, 800), clip="A1@1", src_start_ms=2200, src_end_ms=2600),
             replace(w("five", 800, 1200), clip="A1@1", src_start_ms=2600, src_end_ms=3000)]
    r = word_cut.keep_ranges(words, [{"text": "one four five"}], TPF, clips, _src(WORDS), end_ticks=2000 * MS)
    (a, b), = r["keep_frames"]
    assert a == 0 and b * TPF == 1200 * MS          # whole span, the join inside untouched
    assert r["cuts_frames"] == [[b, -(-2000 * MS // TPF)]]


def test_a_piece_takes_along_wordless_sound_that_touches_it():
    # A laugh at 0.70-0.95 s, no word on it, 50 ms before "two" (1.0 s); "one" ends at 0.4 s.
    level = lambda media, t: 5.0 if 700 * MS <= t < 950 * MS or 1000 * MS <= t < 1800 * MS else -5.0
    (piece,) = word_cut.plan_pieces(WORDS, [{"text": "two three"}], TPF, _src(WORDS), level)
    assert int(piece["in_ticks"]) <= 700 * MS and int(piece["in_ticks"]) >= 400 * MS   # the laugh is kept, "one" is not
    far = lambda media, t: 5.0 if 450 * MS <= t < 600 * MS or 1000 * MS <= t < 1800 * MS else -5.0
    (piece,) = word_cut.plan_pieces(WORDS, [{"text": "two three"}], TPF, _src(WORDS), far)
    assert int(piece["in_ticks"]) >= 800 * MS          # 400 ms of quiet between: not taken
