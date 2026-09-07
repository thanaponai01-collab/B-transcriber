"""mark_export.py — CutPlan → mark plan (JSON) for the UXP Mark/Apply plugin
(issue #17/#19: CutDeck mark-and-apply cutting on a live Premiere sequence).

**PARKED (2026-08-26).** Nothing consumes this module. It assumes the plugin
can split the editor's live sequence at every cut boundary, and that split
primitive was abandoned on evidence after issues #18 and #24 — see
``assemble_export.py``'s docstring for the full reasoning and the span-count
arithmetic that settled it. ``cutdeck.export_mode.MODE_ASSEMBLE`` is the live
route.

Deliberately **not deleted yet.** This module is correct and tested, and the
assemble route has not yet cut real footage — retiring a proven module to make
room for an unproven one inverts the discipline issue #23 used when it retired
``jsx_export.py`` (which was removed only *after* it was shown unreachable).
Delete this, its tests, and ``MODE_MARK`` once assemble has passed its live
acceptance on a throwaway. If in-place marking is ever revived, it will need a
split primitive that does not exist today, not this file.

Pure, deterministic, no Premiere dependency. This module owns only *where* a
split/disable must happen — the UXP plugin owns *how* a split is performed
(clone + trim, see the plugin design in issue #22). Deliberately not JSX and
not a script, unlike the retired ``jsx_export.py``: nothing here executes
inside Premiere.

Frame math goes through ``transcribe.timebase`` only, same rule as
``xml_export.py`` — no float fps or float seconds ever reaches the output.

**No ordering requirement.** ``jsx_export.py`` had to emit CUT spans in
descending ``src_in_ms`` order because each ripple-delete shifted every
timestamp to its right, so a later cut had to be applied before an earlier
one could still be trusted. Mark moves nothing — every region is a split +
disable at an absolute, unchanging sequence timestamp — so that ordering
constraint has no analogue here. Regions are emitted in natural ascending
order for readability; do not reintroduce a reverse-chronological sort as a
"fix" without a reason that actually needs it.
"""

from __future__ import annotations

from cutdeck.contracts import CUT, CutPlan
from transcribe.timebase import ms_to_frame

MARK_PLAN_VERSION = "1.0"


def to_mark_plan(plan: CutPlan) -> dict:
    """Render a CutPlan's CUT spans as a JSON-serializable mark plan.

    ``{"idx": ..., "in_frame": ..., "out_frame": ..., "reason": ...}`` per CUT
    span, plus the sequence timebase the frame numbers are relative to. The
    plugin splits every track at ``in_frame``/``out_frame`` and disables the
    region between them; it never sees or reasons about milliseconds.

    ``idx``/``reason`` are carried through so the plugin (and a human reading
    its console log) can trace a mark back to the CutSpan that produced it —
    the same round-trip-key discipline ``xml_export.py`` uses for clip names
    and ``jsx_export.py`` used for its ``CUTDECK_SPAN`` markers.

    Raises ``ValueError`` on a VFR timebase (GAP-2), same refusal
    ``xml_export.to_xml`` uses — in-place mode does not guess frame numbers on
    VFR sources either. A plan with no CUT spans is a valid, tested no-op
    output (``regions: []``), not an error.
    """
    tb = plan.timebase
    if tb.is_vfr:
        raise ValueError(
            "refusing to generate a mark plan for VFR source: no single frame grid "
            "for frame-accurate cuts (GAP-2). Conform a CFR proxy first."
        )

    regions = [
        {
            "idx": s.idx,
            "in_frame": ms_to_frame(s.src_in_ms, tb),
            "out_frame": ms_to_frame(s.src_out_ms, tb),
            "reason": s.reason,
        }
        for s in plan.spans
        if s.action == CUT
    ]

    return {
        "mark_plan_version": MARK_PLAN_VERSION,
        "job_id": plan.job_id,
        "timebase": {"fps_num": tb.fps_num, "fps_den": tb.fps_den},
        "regions": regions,
    }
