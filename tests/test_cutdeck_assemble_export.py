"""Acceptance — CutPlan -> UXP assemble plan exporter.

Pure JSON-generation checks: every span placed (not just the CUT ones), the
one-rounding-per-boundary rule, source-time recovery, the tiling guard, VFR
refusal, no-op, and mode dispatch. Prior art: tests/test_cutdeck_mark_export.py,
whose structure this mirrors.

The load-bearing test here is ``test_adjacent_spans_share_one_boundary_frame``.
Everything else in the assemble design rests on placements meeting exactly.
"""

import json

import pytest

from cutdeck.assemble_export import ASSEMBLE_PLAN_VERSION, to_assemble_plan
from cutdeck.contracts import CUT, KEEP, CutPlan, CutSpan, Timebase
from cutdeck.export_mode import (
    MODE_ASSEMBLE,
    MODE_MARK,
    MODE_NEW_SEQUENCE,
    exporter_for_mode,
)
from transcribe.timebase import ms_to_frame

# The two rates this project's own media table actually carries, and the two a
# fabricated 25fps would silently corrupt.
NTSC5994 = Timebase(fps_num=60000, fps_den=1001, duration_ms=3_600_000)
PAL25 = Timebase(fps_num=25, fps_den=1, duration_ms=3_600_000)


def _plan(spans, tb=NTSC5994):
    return CutPlan(job_id=42, media_sha256="x" * 64, timebase=tb, spans=spans)


def _tiled():
    """A contiguous KEEP/CUT/KEEP/CUT/KEEP tiling of [0, 3_600_000)."""
    return [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=10_000, action=KEEP, reason="keep"),
        CutSpan(idx=1, src_in_ms=10_000, src_out_ms=12_000, action=CUT, reason="silence"),
        CutSpan(idx=2, src_in_ms=12_000, src_out_ms=20_000, action=KEEP, reason="keep"),
        CutSpan(idx=3, src_in_ms=20_000, src_out_ms=23_000, action=CUT, reason="silence"),
        CutSpan(idx=4, src_in_ms=23_000, src_out_ms=3_600_000, action=KEEP, reason="keep"),
    ]


def test_every_span_is_placed_not_just_the_cuts():
    """The whole point of the assemble route: CUT spans are placed and disabled,
    never omitted. mark_export.py emitted only CUT regions; this must not."""
    ap = to_assemble_plan(_plan(_tiled()))

    assert [s["idx"] for s in ap["spans"]] == [0, 1, 2, 3, 4]
    assert [s["enabled"] for s in ap["spans"]] == [True, False, True, False, True]
    assert [s["action"] for s in ap["spans"]] == [KEEP, CUT, KEEP, CUT, KEEP]


def test_adjacent_spans_share_one_boundary_frame():
    """No gaps, no overlaps — a span's src/seq out-frame IS its neighbour's
    in-frame, not a separately-rounded value that happens to be close.

    Boundaries chosen to land off the 59.94 frame grid so independent rounding
    would have a real chance to disagree.
    """
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1_033, action=KEEP),
        CutSpan(idx=1, src_in_ms=1_033, src_out_ms=2_067, action=CUT),
        CutSpan(idx=2, src_in_ms=2_067, src_out_ms=3_101, action=KEEP),
        CutSpan(idx=3, src_in_ms=3_101, src_out_ms=4_149, action=CUT),
        CutSpan(idx=4, src_in_ms=4_149, src_out_ms=5_000, action=KEEP),
    ]
    ap = to_assemble_plan(_plan(spans))
    placed = ap["spans"]

    for prev, cur in zip(placed, placed[1:]):
        assert prev["src_out_frame"] == cur["src_in_frame"]
        # Destinations abut exactly: nothing is removed at assemble time, so a
        # span lands precisely where its predecessor ended.
        assert prev["seq_frame"] + (prev["src_out_frame"] - prev["src_in_frame"]) == cur["seq_frame"]


def test_assembled_length_equals_the_source_length():
    """total_frames is what the plugin asserts getEndTime() against after Build."""
    ap = to_assemble_plan(_plan(_tiled()))

    assert ap["total_frames"] == ms_to_frame(3_600_000, NTSC5994)
    assert ap["spans"][0]["seq_frame"] == 0
    last = ap["spans"][-1]
    assert last["seq_frame"] + (last["src_out_frame"] - last["src_in_frame"]) == ap["total_frames"]


def test_source_time_is_recovered_from_the_sequence_time_plan():
    """plan_from_live_clip offsets spans by (clip_start_ms - in_point_ms).
    createSetInOutPointsAction needs source media time, so the exporter must
    invert that — otherwise every placement reads the wrong part of the file."""
    clip_start_ms, in_point_ms = 30_000, 5_000
    offset = clip_start_ms - in_point_ms
    # _clamp_and_offset clamps source spans to [in_point_ms, out_point_ms]
    # before offsetting, so the first span's SOURCE time starts at in_point_ms
    # and its SEQUENCE time starts at clip_start_ms. Build them that way.
    spans = [
        CutSpan(idx=0, src_in_ms=5_000 + offset, src_out_ms=15_000 + offset, action=KEEP),
        CutSpan(idx=1, src_in_ms=15_000 + offset, src_out_ms=17_000 + offset, action=CUT),
    ]
    assert spans[0].src_in_ms == clip_start_ms  # sanity: this is what the pipeline emits

    ap = to_assemble_plan(
        _plan(spans), clip_start_ms=clip_start_ms, in_point_ms=in_point_ms
    )

    # Source frames are relative to the media file: span 0 starts at in_point.
    assert ap["spans"][0]["src_in_frame"] == ms_to_frame(5_000, NTSC5994)
    assert ap["spans"][0]["src_out_frame"] == ms_to_frame(15_000, NTSC5994)
    assert ap["spans"][1]["src_out_frame"] == ms_to_frame(17_000, NTSC5994)
    # Destination frames are relative to the new sequence, which starts at 0 —
    # clip_start_ms does NOT leak into the assembled sequence's positions.
    assert ap["spans"][0]["seq_frame"] == 0
    # Span 1 lands on the DIFFERENCE of the two shared boundary frames, not on
    # a separately-rounded duration. At 59.94 those genuinely disagree:
    #   f(40000) - f(30000) = 2398 - 1798 = 600
    #   ms_to_frame(10000)                = 599   (599.4, rounds down)
    # Asserting the latter would be asserting the one-frame gap this module
    # exists to make impossible. See the one-rounding-per-boundary rule.
    assert ap["spans"][1]["seq_frame"] == (
        ms_to_frame(40_000, NTSC5994) - ms_to_frame(30_000, NTSC5994)
    )
    assert ap["spans"][1]["seq_frame"] != ms_to_frame(10_000, NTSC5994)


def test_frame_numbers_are_frame_snapped_under_both_real_rates():
    """59.94 and 25 are both live in this project's media table; a plan must be
    correct under each rather than under whichever one was tested."""
    for tb in (NTSC5994, PAL25):
        ap = to_assemble_plan(_plan(_tiled(), tb=tb))
        assert ap["timebase"] == {"fps_num": tb.fps_num, "fps_den": tb.fps_den}
        assert ap["spans"][1]["src_in_frame"] == ms_to_frame(10_000, tb)
        assert ap["spans"][1]["src_out_frame"] == ms_to_frame(12_000, tb)


def test_non_tiling_spans_are_refused():
    """A gap would place footage wrong; an overlap would let
    createOverwriteItemAction silently eat a frame. Both refuse."""
    gapped = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=10_000, action=KEEP),
        CutSpan(idx=1, src_in_ms=10_500, src_out_ms=12_000, action=CUT),
    ]
    with pytest.raises(ValueError, match="do not tile"):
        to_assemble_plan(_plan(gapped))

    overlapping = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=10_000, action=KEEP),
        CutSpan(idx=1, src_in_ms=9_500, src_out_ms=12_000, action=CUT),
    ]
    with pytest.raises(ValueError, match="do not tile"):
        to_assemble_plan(_plan(overlapping))


def test_mismatched_descriptor_offsets_are_refused():
    """Wrong clip_start_ms/in_point_ms would read before the media start rather
    than failing — refuse instead of emitting negative source frames."""
    spans = [CutSpan(idx=0, src_in_ms=0, src_out_ms=10_000, action=KEEP)]
    with pytest.raises(ValueError, match="before the start of"):
        to_assemble_plan(_plan(spans), clip_start_ms=60_000, in_point_ms=0)


def test_no_spans_is_a_valid_noop():
    ap = to_assemble_plan(_plan([]))
    assert ap["spans"] == []
    assert ap["total_frames"] == 0
    assert ap["assemble_plan_version"] == ASSEMBLE_PLAN_VERSION


def test_zero_cut_spans_still_places_the_whole_clip():
    """Unlike mark_export (where no CUTs meant an empty region list), a plan with
    nothing to cut still assembles — one enabled span covering everything."""
    ap = to_assemble_plan(
        _plan([CutSpan(idx=0, src_in_ms=0, src_out_ms=3_600_000, action=KEEP)])
    )
    assert len(ap["spans"]) == 1
    assert ap["spans"][0]["enabled"] is True
    assert ap["total_frames"] == ms_to_frame(3_600_000, NTSC5994)


def test_staleness_keys_are_echoed_for_the_plugins_refusal_check():
    ap = to_assemble_plan(
        _plan(_tiled()), media_path="F:/x/Short1.mp3", request_id="req-7"
    )
    assert ap["request_id"] == "req-7"
    assert ap["media_path"] == "F:/x/Short1.mp3"
    assert ap["timebase"] == {"fps_num": 60000, "fps_den": 1001}


def test_vfr_refuses():
    vfr = Timebase(fps_num=30000, fps_den=1001, duration_ms=5000, is_vfr=True)
    plan = CutPlan(job_id=1, media_sha256="y" * 64, timebase=vfr,
                   spans=[CutSpan(idx=0, src_in_ms=0, src_out_ms=5000, action=KEEP)])
    with pytest.raises(ValueError, match="VFR"):
        to_assemble_plan(plan)


def test_output_is_json_serializable_and_stable_across_runs():
    plan = _plan(_tiled())
    first = json.dumps(to_assemble_plan(plan), sort_keys=True)
    second = json.dumps(to_assemble_plan(plan), sort_keys=True)
    assert first == second


def test_exporter_for_mode_returns_assemble_exporter():
    assert exporter_for_mode(MODE_ASSEMBLE) is to_assemble_plan
    assert exporter_for_mode(MODE_MARK) is not to_assemble_plan
    assert exporter_for_mode(MODE_NEW_SEQUENCE) is not to_assemble_plan


def test_unrecognized_mode_still_raises():
    with pytest.raises(ValueError, match="unrecognized cutdeck.mode"):
        exporter_for_mode("split")
