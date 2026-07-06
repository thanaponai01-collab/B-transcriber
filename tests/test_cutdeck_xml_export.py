"""Phase 2 acceptance — FCP7 XML export frame math, structure, and VFR refusal.

Paper-passing is not the real acceptance (that is a clean import into Premiere on
real footage). But these checks fail fast if the frame arithmetic drifts, the
timeline stops being contiguous, or VFR refusal regresses.
"""

from xml.etree import ElementTree as ET

import pytest

from cutdeck.contracts import CUT, KEEP, CutPlan, CutSpan, Timebase
from cutdeck.xml_export import name_key, to_xml
from transcribe.timebase import ms_to_frame

# NTSC 29.97 — the exact case the acceptance cares about.
NTSC2997 = Timebase(fps_num=30000, fps_den=1001, duration_ms=3_600_000)


def _plan(spans):
    return CutPlan(job_id=42, media_sha256="x" * 64, timebase=NTSC2997, spans=spans)


def test_keep_clips_are_frame_accurate_and_contiguous():
    # Two keep spans around a cut; an hour-scale offset to catch drift.
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=10_000, action=KEEP, reason="keep"),
        CutSpan(idx=1, src_in_ms=10_000, src_out_ms=12_000, action=CUT, reason="silence"),
        CutSpan(idx=2, src_in_ms=12_000, src_out_ms=3_600_000, action=KEEP, reason="keep"),
    ]
    root = ET.fromstring(to_xml(_plan(spans), r"C:\Me\footage.mp4", plan_id=7))

    clips = root.find("sequence/media/video/track").findall("clipitem")
    assert len(clips) == 2

    # Source in/out come straight from the timebase, no float fps.
    assert int(clips[0].find("in").text) == ms_to_frame(0, NTSC2997)
    assert int(clips[0].find("out").text) == ms_to_frame(10_000, NTSC2997)
    assert int(clips[1].find("in").text) == ms_to_frame(12_000, NTSC2997)
    assert int(clips[1].find("out").text) == ms_to_frame(3_600_000, NTSC2997)

    # Timeline is gap-free: clip2 starts exactly where clip1 ends, and the cut's
    # 2 s of silence is gone from the timeline (start jumps by clip1's length only).
    end1 = int(clips[0].find("end").text)
    assert int(clips[0].find("start").text) == 0
    assert int(clips[1].find("start").text) == end1
    dur0 = ms_to_frame(10_000, NTSC2997) - ms_to_frame(0, NTSC2997)
    assert end1 == dur0

    # Round-trip key is on the clip name and in comments.
    assert clips[0].find("name").text == name_key(42, 7, 0)
    assert clips[1].find("name").text == name_key(42, 7, 2)

    # Rate expressed as integer timebase 30 + ntsc TRUE (not a float).
    rate = root.find("sequence/rate")
    assert rate.find("timebase").text == "30"
    assert rate.find("ntsc").text == "TRUE"

    # Single file listing: exactly one <file> carries the pathurl, rest are stubs.
    files = root.findall(".//file")
    with_path = [f for f in files if f.find("pathurl") is not None]
    assert len(with_path) == 1
    assert with_path[0].find("pathurl").text.startswith("file://localhost/C%3A/")


def test_vfr_export_refuses():
    vfr = Timebase(fps_num=30000, fps_den=1001, duration_ms=5000, is_vfr=True)
    plan = CutPlan(job_id=1, media_sha256="y" * 64, timebase=vfr,
                   spans=[CutSpan(idx=0, src_in_ms=0, src_out_ms=5000, action=KEEP)])
    with pytest.raises(ValueError, match="VFR"):
        to_xml(plan, "x.mp4", plan_id=1)


def test_no_keep_spans_refuses():
    plan = _plan([CutSpan(idx=0, src_in_ms=0, src_out_ms=5000, action=CUT, reason="silence")])
    # duration mismatch is fine here — to_xml only looks at keep spans.
    with pytest.raises(ValueError, match="no keep"):
        to_xml(plan, "x.mp4", plan_id=1)
