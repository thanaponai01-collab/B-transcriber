"""Phase 1 acceptance — in-place JSX export (docs/HANDOFF_CUTDECK_LIVE_SEQUENCE.md).

Pure string-generation checks: frame math, reverse-chronological ordering, no-op
on zero CUT spans, VFR refusal, and the sync-lock confirmation gate. The real
acceptance bar (a clean razor + ripple-delete against a live Premiere sequence) is
Phase 3, human-verified — not testable here.
"""

import re

import pytest

from cutdeck.contracts import CUT, KEEP, CutPlan, CutSpan, Timebase
from cutdeck.jsx_export import to_jsx
from transcribe.timebase import frame_to_ms, ms_to_frame

NTSC2997 = Timebase(fps_num=30000, fps_den=1001, duration_ms=3_600_000)

_SPAN_RE = re.compile(r"CUTDECK_SPAN idx=(\d+) in_frame=(\d+) out_frame=(\d+)")


def _plan(spans):
    return CutPlan(job_id=42, media_sha256="x" * 64, timebase=NTSC2997, spans=spans)


def test_cut_spans_emitted_in_descending_src_in_order_frame_accurate():
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=10_000, action=KEEP, reason="keep"),
        CutSpan(idx=1, src_in_ms=10_000, src_out_ms=12_000, action=CUT, reason="silence"),
        CutSpan(idx=2, src_in_ms=12_000, src_out_ms=20_000, action=KEEP, reason="keep"),
        CutSpan(idx=3, src_in_ms=20_000, src_out_ms=23_000, action=CUT, reason="silence"),
        CutSpan(idx=4, src_in_ms=23_000, src_out_ms=3_600_000, action=KEEP, reason="keep"),
    ]
    jsx = to_jsx(_plan(spans))

    matches = _SPAN_RE.findall(jsx)
    assert len(matches) == 2
    # Reverse chronological: the later cut (idx=3) is emitted before the earlier one (idx=1).
    assert [int(m[0]) for m in matches] == [3, 1]

    idx3, in3, out3 = matches[0]
    assert int(in3) == ms_to_frame(20_000, NTSC2997)
    assert int(out3) == ms_to_frame(23_000, NTSC2997)
    # Frame numbers back-convert to the frame-snapped ms, not the raw unsnapped ms.
    assert frame_to_ms(int(in3), NTSC2997) == frame_to_ms(ms_to_frame(20_000, NTSC2997), NTSC2997)

    idx1, in1, out1 = matches[1]
    assert int(in1) == ms_to_frame(10_000, NTSC2997)
    assert int(out1) == ms_to_frame(12_000, NTSC2997)

    # One cutSpan(...) call per marker, immediately following it.
    calls = re.findall(r"^\s*cutSpan\(\d+, \d+\);", jsx, re.MULTILINE)
    assert len(calls) == 2


def test_no_cut_spans_is_a_valid_noop():
    plan = _plan([CutSpan(idx=0, src_in_ms=0, src_out_ms=3_600_000, action=KEEP, reason="keep")])
    jsx = to_jsx(plan)
    assert "CUTDECK_SPAN" not in jsx
    assert not re.search(r"^\s*cutSpan\(\d+, \d+\);", jsx, re.MULTILINE)
    assert "nothing to do" in jsx
    # Still syntactically a complete IIFE.
    assert jsx.strip().startswith("//")
    assert jsx.rstrip().endswith("})();")


def test_vfr_export_refuses():
    vfr = Timebase(fps_num=30000, fps_den=1001, duration_ms=5000, is_vfr=True)
    plan = CutPlan(job_id=1, media_sha256="y" * 64, timebase=vfr,
                   spans=[CutSpan(idx=0, src_in_ms=0, src_out_ms=5000, action=KEEP)])
    with pytest.raises(ValueError, match="VFR"):
        to_jsx(plan)


def test_sync_lock_gate_present_by_default_and_omittable():
    plan = _plan([
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=KEEP, reason="keep"),
        CutSpan(idx=1, src_in_ms=1000, src_out_ms=2000, action=CUT, reason="silence"),
        CutSpan(idx=2, src_in_ms=2000, src_out_ms=3_600_000, action=KEEP, reason="keep"),
    ])
    with_gate = to_jsx(plan, require_sync_lock=True)
    assert "confirm(" in with_gate
    assert "syncLockConfirmed" in with_gate

    without_gate = to_jsx(plan, require_sync_lock=False)
    assert "confirm(" not in without_gate
    assert "syncLockConfirmed" not in without_gate


def test_frame_math_uses_sequence_timebase_not_a_hardcoded_ticks_constant():
    plan = _plan([
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=KEEP, reason="keep"),
        CutSpan(idx=1, src_in_ms=1000, src_out_ms=2000, action=CUT, reason="silence"),
        CutSpan(idx=2, src_in_ms=2000, src_out_ms=3_600_000, action=KEEP, reason="keep"),
    ])
    jsx = to_jsx(plan)
    assert "Number(seq.timebase)" in jsx
    assert "254016000000" not in jsx
