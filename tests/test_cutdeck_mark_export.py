"""Issue #19 acceptance — CutPlan -> UXP mark plan exporter.

Pure JSON-generation checks: frame math, no ordering requirement, no-op on
zero CUT spans, VFR refusal, JSON-serializability/stability. Prior art: the
now-retired tests/test_cutdeck_jsx_export.py (removed with jsx_export.py,
issue #23), which this file's structure mirrors.
"""

import json

import pytest

from cutdeck.contracts import CUT, KEEP, CutPlan, CutSpan, Timebase
from cutdeck.export_mode import MODE_MARK, MODE_NEW_SEQUENCE, exporter_for_mode
from cutdeck.mark_export import to_mark_plan
from transcribe.timebase import frame_to_ms, ms_to_frame

NTSC2997 = Timebase(fps_num=30000, fps_den=1001, duration_ms=3_600_000)


def _plan(spans):
    return CutPlan(job_id=42, media_sha256="x" * 64, timebase=NTSC2997, spans=spans)


def test_one_region_per_cut_span_none_for_keep():
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=10_000, action=KEEP, reason="keep"),
        CutSpan(idx=1, src_in_ms=10_000, src_out_ms=12_000, action=CUT, reason="silence"),
        CutSpan(idx=2, src_in_ms=12_000, src_out_ms=20_000, action=KEEP, reason="keep"),
        CutSpan(idx=3, src_in_ms=20_000, src_out_ms=23_000, action=CUT, reason="silence"),
        CutSpan(idx=4, src_in_ms=23_000, src_out_ms=3_600_000, action=KEEP, reason="keep"),
    ]
    mp = to_mark_plan(_plan(spans))

    assert [r["idx"] for r in mp["regions"]] == [1, 3]
    assert all(r["reason"] == "silence" for r in mp["regions"])


def test_frame_numbers_back_convert_to_frame_snapped_ms():
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=10_000, action=KEEP, reason="keep"),
        CutSpan(idx=1, src_in_ms=10_000, src_out_ms=12_000, action=CUT, reason="silence"),
        CutSpan(idx=2, src_in_ms=12_000, src_out_ms=3_600_000, action=KEEP, reason="keep"),
    ]
    mp = to_mark_plan(_plan(spans))
    region = mp["regions"][0]

    assert region["in_frame"] == ms_to_frame(10_000, NTSC2997)
    assert region["out_frame"] == ms_to_frame(12_000, NTSC2997)
    assert frame_to_ms(region["in_frame"], NTSC2997) == frame_to_ms(
        ms_to_frame(10_000, NTSC2997), NTSC2997
    )


def test_no_cut_spans_is_a_valid_noop():
    plan = _plan([CutSpan(idx=0, src_in_ms=0, src_out_ms=3_600_000, action=KEEP, reason="keep")])
    mp = to_mark_plan(plan)
    assert mp["regions"] == []


def test_regions_emitted_in_natural_ascending_order_not_reverse_chronological():
    """Unlike jsx_export.py, nothing ripples during Mark — no reverse-chronological
    ordering is needed since every timestamp stays absolute sequence time."""
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=CUT, reason="a"),
        CutSpan(idx=1, src_in_ms=1000, src_out_ms=2000, action=KEEP, reason="keep"),
        CutSpan(idx=2, src_in_ms=2000, src_out_ms=3000, action=CUT, reason="b"),
        CutSpan(idx=3, src_in_ms=3000, src_out_ms=3_600_000, action=KEEP, reason="keep"),
    ]
    mp = to_mark_plan(_plan(spans))
    assert [r["idx"] for r in mp["regions"]] == [0, 2]


def test_vfr_refuses():
    vfr = Timebase(fps_num=30000, fps_den=1001, duration_ms=5000, is_vfr=True)
    plan = CutPlan(job_id=1, media_sha256="y" * 64, timebase=vfr,
                   spans=[CutSpan(idx=0, src_in_ms=0, src_out_ms=5000, action=KEEP)])
    with pytest.raises(ValueError, match="VFR"):
        to_mark_plan(plan)


def test_output_is_json_serializable_and_stable_across_runs():
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=CUT, reason="silence"),
        CutSpan(idx=1, src_in_ms=1000, src_out_ms=3_600_000, action=KEEP, reason="keep"),
    ]
    plan = _plan(spans)
    first = json.dumps(to_mark_plan(plan), sort_keys=True)
    second = json.dumps(to_mark_plan(plan), sort_keys=True)
    assert first == second


def test_exporter_for_mode_returns_mark_exporter():
    assert exporter_for_mode(MODE_MARK) is to_mark_plan
    assert exporter_for_mode(MODE_NEW_SEQUENCE) is not to_mark_plan


def test_unrecognized_mode_still_raises():
    with pytest.raises(ValueError, match="unrecognized cutdeck.mode"):
        exporter_for_mode("something_else")
