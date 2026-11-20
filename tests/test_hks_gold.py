"""Gold reader for HKS day folders (cutdeck/hks_gold.py)."""

from pathlib import Path

import pytest

from cutdeck.hks_gold import Cut, SourceRange, body, gold_from_project, read_day
from cutdeck.prproj_reader import read_project

FOOT = "Show Full.mp4"


def clip(start, end, src_in, media=FOOT, *, disabled=False, scale=150.0, width=1280, src_out=None):
    """A clip; ``scale=None`` leaves Motion out, as Premiere does at its defaults."""
    motion = [{"name": "Motion", "match_name": "AE.ADBE Motion",
               "params": {"scale": {"value": scale}, "position": {"value": [0.5, 0.5]}}}]
    return {
        "name": media, "start": start, "end": end, "source_in": src_in,
        "source_out": src_in + (end - start) if src_out is None else src_out,
        "disabled": disabled, "media_path": f"D:\\elsewhere\\{media}",
        "source_frame": [width, width * 9 // 16], "effects": motion if scale is not None else [],
    }


def seq(name, video=(), audio=()):
    return {"name": name,
            "video_tracks": [{"index": i, "muted": False, "clips": list(c)} for i, c in enumerate(video)],
            "audio_tracks": [{"index": i, "muted": False, "clips": list(c)} for i, c in enumerate(audio)]}


def show(video, dialogue, *, end=100.0, hook=10.0, name="1 YOUTUBE D1"):
    """A show: footage on the given tracks, a hook SFX and an end logo that sets the show end."""
    sfx = [clip(hook, hook + 0.6, 0, "Transition Complex 14 #e7.wav")] if hook is not None else []
    return seq(name, video=[*video, [clip(end - 5, end, 0, "END LOGO.mp4")]], audio=[dialogue, sfx])


def gold(*sequences, footage=(FOOT.upper(),), **kw):
    return gold_from_project({"path": "x.prproj", "sequences": list(sequences)}, list(footage), **kw)


def outputs(yt):
    return [yt, show([[clip(0, 60, 0)]], [clip(0, 60, 0)], end=60, name="2 FACEBOOK D1"),
            show([[clip(0, 30, 0)]], [clip(0, 30, 0)], end=30, name="3 SQUARE SELECT D1")]


def test_show_end_stops_before_the_pool_and_keeps_come_from_audio():
    # Main picture moves to V2 for 40-60; V1 has a gap there. The pool sits at 500+.
    v1 = [clip(0, 40, 100), clip(60, 90, 300), clip(500, 600, 0)]
    v2 = [clip(40, 60, 200)]
    a1 = [clip(0, 40, 100), clip(40, 60, 200), clip(60, 90, 300), clip(500, 600, 0)]
    yt = gold(*outputs(show([v1, v2], a1))).yt
    assert yt.show_end == 100.0
    assert yt.length == 600.0
    assert yt.hook_end == 10.0
    assert yt.keeps == [SourceRange(FOOT, 100, 140, 0, 40), SourceRange(FOOT, 200, 220, 40, 60),
                        SourceRange(FOOT, 300, 330, 60, 90)]


def test_cut_is_uncovered_only_when_the_main_shot_jumps_on_both_sides():
    a1 = [clip(0, 20, 100), clip(20, 40, 150), clip(40, 60, 200), clip(60, 80, 300), clip(80, 95, 400)]
    v1 = [clip(0, 20, 100), clip(20, 40, 150), clip(40, 60, 200), clip(60, 80, 300), clip(80, 95, 400)]
    v2 = [clip(15, 25, 900),            # B-roll over the cut at 20
          clip(60, 80, 300),            # main shot on V2, in sync: the cut at 60 still shows
          clip(80, 95, 400, scale=288)]  # zoomed insert of the same footage at 80
    yt = gold(*outputs(show([v1, v2], a1))).yt
    assert yt.cuts == [Cut(20, 30, True), Cut(40, 30, False), Cut(60, 80, False), Cut(80, 80, True)]
    assert yt.covers == [SourceRange(FOOT, 900, 910, 15, 25)]


def test_a_full_hd_file_at_default_scale_frames_like_a_720p_file_at_150():
    # 20261112: file (1) is 1280x720 at 150 %, the others 1920x1080 with Motion left out.
    a1 = [clip(0, 20, 100), clip(20, 40, 0, "Show (2).mp4")]
    v1 = [clip(0, 20, 100), clip(20, 40, 0, "Show (2).mp4", scale=None, width=1920)]
    yt = gold(*outputs(show([v1], a1)), footage=[FOOT, "Show (2).mp4"]).yt
    assert yt.cuts == [Cut(20, None, False)]


def test_continuous_source_and_a_muted_censor_are_not_cuts():
    a1 = [clip(0, 20, 100), clip(20, 30, 120),                  # split, source continues
          clip(30, 30.24, 130, disabled=True), clip(30.24, 50, 130.24)]  # bleep, same sync
    v1 = [clip(0, 50, 100)]
    yt = gold(*outputs(show([v1], a1))).yt
    assert yt.cuts == []
    assert sum(k.tl_end - k.tl_start for k in yt.keeps) == pytest.approx(49.76)


def test_min_jump_frames_ignores_short_jumps():
    a1 = [clip(0, 20, 100), clip(20, 40, 120.12), clip(40, 60, 200)]
    v1 = [clip(0, 20, 100), clip(20, 40, 120.12), clip(40, 60, 200)]
    sequences = outputs(show([v1], a1))
    assert [c.tl for c in gold(*sequences).yt.cuts] == [20, 40]
    assert [c.tl for c in gold(*sequences, min_jump_frames=4).yt.cuts] == [40]


def test_jump_across_media_has_no_size_and_slow_motion_tail_is_a_cover():
    # A day split into several footage files (20261112), then a slowed-down last shot.
    a1 = [clip(0, 20, 100), clip(20, 40, 0, "Show (2).mp4")]
    v1 = [clip(0, 20, 100), clip(20, 40, 0, "Show (2).mp4"), clip(40, 42.84, 500, src_out=500.36)]
    yt = gold(*outputs(show([v1], a1, end=50)), footage=[FOOT, "show (2).MP4"]).yt
    assert [c.jump for c in yt.cuts] == [None]
    assert [k.media for k in yt.keeps] == [FOOT, "Show (2).mp4"]
    assert yt.covers == [SourceRange(FOOT, 500, 500.36, 40, 42.84)]


def test_body_starts_after_the_hook():
    a1 = [clip(0, 5, 900), clip(5, 10, 950), clip(10, 30, 100), clip(30, 50, 300)]
    yt = gold(*outputs(show([a1], a1))).yt
    keeps, cuts = body(yt)
    assert [k.tl_start for k in keeps] == [10, 30]
    assert [c.tl for c in cuts] == [30]
    assert [c.tl for c in yt.cuts] == [5, 10, 30]


def test_missing_hook_missing_and_conflicting_sequences_are_problems():
    a1 = [clip(0, 20, 100)]
    yt = show([a1], a1, hook=None)
    fb = show([a1], a1, name="2 FACEBOOK D2")
    fb_other = show([a1], [clip(0, 20, 999)], name="2 FACEBOOK D1")
    day = gold(yt, fb, fb_other, seq("3 SQUARE SELECT D1"), show([a1], a1, name="3 SQUARE SELECT D1 Copy 01"))
    assert day.yt.hook_end is None
    assert body(day.yt)[0] == day.yt.keeps
    assert day.fb is None and day.square is None
    assert len(day.problems) == 3
    assert day.edit_drops is None


def test_identical_duplicates_and_a_later_suffix_are_fine():
    a1 = [clip(0, 20, 100)]
    day = gold(seq("1 YOUTUBE D1"), show([a1], a1, name="1 YOUTUBE D2"), *outputs(show([a1], a1))[1:],
               outputs(show([a1], a1))[1])
    assert day.yt.sequence == "1 YOUTUBE D2"
    assert day.fb is not None
    assert day.problems == []


def test_edit_drops_merge_touching_v1_pieces():
    edit = seq("Edit", video=[[clip(0, 10, 0), clip(30, 40, 30), clip(40, 45, 40)], [clip(10, 30, 10)]])
    day = gold(edit, *outputs(show([[clip(0, 20, 100)]], [clip(0, 20, 100)])))
    assert day.edit_drops == [(0, 10), (30, 45)]


def test_read_day_reports_a_folder_without_project_or_footage(tmp_path):
    day = read_day(tmp_path)
    assert day.project is None and day.yt is None
    assert len(day.problems) == 2


# --- real projects (gitignored / local drive) ---------------------------------------------------

P9 = Path("test_projects/hks_20261120/p9.prproj")
FINAL = Path("G:/Me/Works/20261120 - โหนกระแส/4. PROJECTS/1. PREMIERE PRO/20261120 - โหนกระแส.prproj")
FOOTAGE_1120 = ["HKS Facebook 201169 Full.mp4"]


@pytest.mark.skipif(not P9.exists(), reason="20261120 18:12 snapshot not present")
def test_p9_snapshot_matches_the_measured_edit():
    project = read_project(P9)
    day = gold_from_project(project, FOOTAGE_1120)
    assert day.edit_drops == pytest.approx(
        [(0, 22.68), (824.56, 877.20), (2004.88, 2069.32), (3947.00, 4407.48), (4428.24, 4447.96)], abs=0.05)
    yt = day.yt
    assert yt.hook_end is None  # the hook was built after this save
    # V1 holds 1065.16 s; audio leaves out a 0.24 s censor (491.72) and the 2.84 s video-only tail.
    assert sum(k.tl_end - k.tl_start for k in yt.keeps) == pytest.approx(1062.08, abs=0.01)
    assert (len(yt.cuts), sum(c.covered for c in yt.cuts)) == (159, 135)
    yt4 = gold_from_project(project, FOOTAGE_1120, min_jump_frames=4).yt
    assert (len(yt4.cuts), sum(c.covered for c in yt4.cuts)) == (155, 131)


@pytest.mark.skipif(not FINAL.exists(), reason="20261120 day project not present")
def test_final_20261120_project():
    day = gold_from_project(read_project(FINAL), FOOTAGE_1120)
    assert day.problems == []
    yt = day.yt
    assert (yt.show_end, yt.hook_end) == pytest.approx((1095.80, 25.84))
    assert (len(yt.cuts), sum(c.covered for c in yt.cuts)) == (165, 140)
    keeps, cuts = body(yt)
    assert (len(cuts), sum(c.covered for c in cuts)) == (159, 135)
    assert (day.fb.show_end, day.square.show_end) == pytest.approx((179.96, 59.96))
