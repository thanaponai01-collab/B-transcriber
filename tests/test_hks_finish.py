"""HKS finishing (cutdeck/hks_finish.py): the music bed on synthetic lengths, then against the
user's saved beds when the G: drive is mounted."""

from pathlib import Path

import pytest

from cutdeck import hks_finish as fin

DAY = Path(r"G:\Me\Works\20261120 - โหนกระแส")


def test_the_bed_covers_the_show_and_ends_on_the_show_end():
    bed = fin.music_bed(25.84, 1095.8)
    assert len(bed) == 22                      # 20 slots, the hook split, the end split
    assert all(fin.playing(bed, t / 10) for t in range(10958))
    assert max(p.tl_end for p in bed) == 1095.8
    last = [p for p in bed if p.tl_end == 1095.8]
    assert [p.db for p in last] == [fin.END_DB]
    assert abs(last[0].source_in + last[0].tl_end - last[0].tl_start - fin.PIECE) < 1e-6  # the file's own end
    assert {p.db for p in bed if p.tl_end <= 25.92 + 1e-6} == {fin.HOOK_DB}
    # Overlapping pieces never share a lane.
    for a in bed:
        for b in bed:
            if a is not b and a.lane == b.lane:
                assert a.tl_end <= b.tl_start + 1e-6 or b.tl_end <= a.tl_start + 1e-6


def test_the_level_is_the_proven_linear_scale():
    assert abs(fin.db_of(fin.level(-33)) + 33) < 1e-9
    assert abs(fin.level(-12) - 10 ** (-27 / 20)) < 1e-12


def test_agreement_sees_a_wrong_level():
    bed = fin.music_bed(20.0, 300.0)
    loud = [fin.Piece(p.tl_start, p.tl_end, p.source_in, p.lane, -24.0) for p in bed]
    assert fin.agreement(bed, bed, 300.0) == 1.0
    assert fin.agreement(bed, loud, 300.0) < 0.1


@pytest.mark.skipif(not DAY.exists(), reason="needs the G: day folders")
def test_20261120_bed_matches_the_saved_one():
    r = fin.check_day(DAY)
    assert r["agree"] == 1.0 and r["pieces"] == r["saved"] == 22


def test_blur_follows_the_clock_and_skips_a_zoomed_insert():
    from cutdeck.hks_audit import Layer
    main, zoom = (1920, (0.5, 0.5), False), (5550, (0.78, 0.68), False)
    ls = [Layer(1, 30, 40, "footage", "a.mp4", "a.mp4", 530, zoom, False),   # zoomed insert over the clock
          Layer(0, 0, 100, "footage", "a.mp4", "a.mp4", 500, main, False)]
    clocks = {"a.mp4": [[510, 560]]}  # source 510-560 has the clock: timeline 10-60
    spans = fin.blur_spans(ls, clocks, 0.0, 100.0)
    covered = lambda t: any(a <= t < b for a, b in spans)
    assert len(spans) == 2
    assert all(covered(t) for t in (10, 20, 29.9, 40.1, 50, 59.9))   # every clock second
    assert not any(covered(t) for t in (5, 31, 35, 39, 61, 80))      # not the zoom, not off-clock


@pytest.mark.skipif(not DAY.exists(), reason="needs the G: day folders")
def test_20261120_ending_and_blur_match_the_saved_cut():
    r, b = fin.check_day(DAY), fin.check_blur(DAY)
    assert r["ending_off"] == {} and r["ending_missing"] == []
    assert b["missed"] == 0 and b["planned_s"] < b["gold_blur_s"]
