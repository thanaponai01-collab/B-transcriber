"""Pins the golden that tests/cutdeck_cut_plan_apply.test.cjs checks the native
planner (uxp/cutdeck/timeline/cutPlanApply.js) against: the XML route's own recut()
of the captured sample sequence, before and after, clip by clip in frames.
If recut() changes behaviour this fails — regenerate with
`python -m tests.test_cutdeck_native_plan_golden` and re-run the Node test."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from cutdeck.contracts import CUT, KEEP, CutPlan, CutSpan, Timebase
from cutdeck.xml_recut import recut, scoped_cuts

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "cutdeck_recut_sample_scrubbed.xml"
GOLDEN = FIXTURES / "cutdeck_native_plan_golden.json"
# Head-trims V2 (starts 27) and V3 (starts 261), mid splits, a tail trim.
CUTS_FRAMES = [[10, 40], [200, 300], [1000, 1100], [5000, 5003], [32900, 32948]]


def _clips(xml: str) -> list[list]:
    seq = ET.fromstring(xml).find("sequence")
    out = []
    for kind in ("video", "audio"):
        for track, t in enumerate(seq.findall(f"media/{kind}/track")):
            for c in t.findall("clipitem"):
                out.append([kind, track, int(c.findtext("start")), int(c.findtext("end")),
                            int(c.findtext("in"))])
    return sorted(out)


def build_golden() -> dict:
    xml = SAMPLE.read_text(encoding="utf-8")
    tb = Timebase(fps_num=30, fps_den=1)
    spans, cursor = [], 0
    for a, b in CUTS_FRAMES:
        a_ms, b_ms = round(a * 1000 / 30), round(b * 1000 / 30)
        if a_ms > cursor:
            spans.append(CutSpan(len(spans), cursor, a_ms, KEEP))
        spans.append(CutSpan(len(spans), a_ms, b_ms, CUT, reason="silence"))
        cursor = b_ms
    plan = CutPlan(job_id=0, media_sha256="", timebase=tb, spans=spans)
    assert scoped_cuts(plan, tb, 32948) == [tuple(c) for c in CUTS_FRAMES]
    out_xml, _ = recut(xml, plan)
    return {"cuts_frames": CUTS_FRAMES, "ticks_per_frame": str(254016000000 // 30),
            "before": _clips(xml), "after": _clips(out_xml)}


def test_golden_matches_xml_recut():
    assert json.loads(GOLDEN.read_text(encoding="utf-8")) == build_golden()


if __name__ == "__main__":
    GOLDEN.write_text(json.dumps(build_golden(), indent=1), encoding="utf-8")
