"""assemble_export.py — CutPlan → assemble plan (JSON) for the UXP plugin.

Pure, deterministic, no Premiere dependency. Successor to ``mark_export.py``
for the route settled after issue #24's spike: **CutDeck does not need a
razor.**

``mark_export.py`` assumed the plugin would split the editor's live sequence
at every cut boundary and disable the middles. Eighteen live rounds of #18/#24
went into proving ``createCloneTrackItemAction`` could perform that split.
The primitive work was never the problem — the *goal* was. ``CutSpan``'s own
contract guarantees spans "tile the whole media duration with no gaps and no
overlaps", so the pieces of a split already exist as data: you do not cut a
clip apart, you **place the pieces**. That is a three-point edit, which UXP
has shipped all along:

    ClipProjectItem.createSetInOutPointsAction(inPoint, outPoint)
    SequenceEditor.createOverwriteItemAction(projectItem, time, vIdx, aIdx)

The plugin creates a sequence, places **every** span — KEEP *and* CUT — back
to back, and calls ``createSetDisabledAction(true)`` on the CUT ones. The
result is byte-for-byte what "razor every boundary and grey out the silences"
would have produced, reached without splitting anything. Apply then collects
what is still disabled and issues one
``createRemoveItemsAction(sel, ripple=true, MediaType.ANY)``.

Why the razor route was abandoned on evidence, not taste: #24 round 16 found a
genuine native split, but it leaves a *full-duration* duplicate per boundary
needing a second committed transaction to remove. Real span counts from this
project's own DB are 487 (job 28, 38.6 min) and 431 (job 24, 32.0 min). At 487
boundaries the intermediate timeline would run to roughly 626 hours before
cleanup. The assemble route needs ~487 placements, every one of them final.

**This module owns only the geometry** — where each piece comes from and where
it lands. The plugin owns every API call. Nothing here executes inside
Premiere; this is not a script, same discipline as ``mark_export.py`` and
unlike the retired ``jsx_export.py``.

Frame math goes through ``transcribe.timebase`` only — no float fps and no
float seconds ever reach the output.

**One rounding per boundary.** Spans tile, so every internal boundary is
shared by exactly two spans. Each boundary is converted to a frame *once*,
into a shared array, and both adjacent spans read the same value. Rounding
each span's edges independently could round one span's ``out`` and its
neighbour's ``in`` to different frames, leaving a one-frame gap (a black flash
or an audio pop) or a one-frame overlap (which ``createOverwriteItemAction``
would resolve silently, eating a frame). Deriving both from one array makes
that structurally impossible rather than merely unlikely. Do not "simplify"
this into a per-span conversion.

**Source time is recovered, not carried.** ``plan_from_live_clip`` hands back
a plan already offset into *sequence* time (``clip_start_ms - in_point_ms``).
``createSetInOutPointsAction`` needs *source media* time, so this module
inverts that offset — which is why it takes ``clip_start_ms`` and
``in_point_ms`` rather than reading them off the plan, where they no longer
exist.

**Ordering carries no meaning.** Because the spans tile and nothing is removed
at assemble time, each destination is absolute: ``dest = src_in - in_point``.
There is no cumulative sum, so no order dependence and no accumulating drift,
and the assembled sequence must come out exactly as long as the source — which
makes verification a single ``getEndTime()`` comparison. Spans are emitted in
ascending order for readability only.
"""

from __future__ import annotations

from typing import Optional

from cutdeck.contracts import CUT, CutPlan
from transcribe.timebase import ms_to_frame

ASSEMBLE_PLAN_VERSION = "1.0"


def to_assemble_plan(
    plan: CutPlan,
    *,
    clip_start_ms: int = 0,
    in_point_ms: int = 0,
    media_path: Optional[str] = None,
    request_id: Optional[str] = None,
) -> dict:
    """Render a CutPlan as a JSON-serializable assemble plan.

    One entry per span — **every** span, not just the CUT ones, because the
    plugin places all of them and merely disables the cuts. Each entry carries
    ``src_in_frame``/``src_out_frame`` (source media time, for
    ``createSetInOutPointsAction``), ``seq_frame`` (destination, for
    ``createOverwriteItemAction``), and an explicit ``enabled`` flag so the
    plugin interprets nothing.

    ``clip_start_ms``/``in_point_ms`` must be the same values that produced the
    plan (see :class:`cutdeck.live_clip.ClipDescriptor`) — they invert the
    source→sequence offset ``plan_from_live_clip`` already applied. Both default
    to 0, which is correct for a plan built directly in source time.

    ``media_path``/``request_id`` are echoed straight back so the plugin can
    refuse a stale or mismatched plan rather than assembling one clip's cuts
    against another's footage. That check is the plugin's, but the plan has to
    carry the material for it — same round-trip-key discipline
    ``xml_export.py`` uses for clip names.

    Raises ``ValueError`` on a VFR timebase (GAP-2), the same refusal
    ``xml_export.to_xml`` and ``mark_export.to_mark_plan`` use; on spans that do
    not tile contiguously, since the whole destination-math argument rests on
    that invariant; and on a span that would read before the start of the source
    media. A plan with no spans is a valid, tested no-op (``spans: []``).
    """
    tb = plan.timebase
    if tb.is_vfr:
        raise ValueError(
            "refusing to generate an assemble plan for VFR source: no single "
            "frame grid for frame-accurate cuts (GAP-2). Conform a CFR proxy first."
        )

    spans = list(plan.spans)
    if not spans:
        return _envelope(plan, tb, media_path, request_id, entries=[], total_frames=0)

    # Contiguity is CutSpan's documented contract, and every claim this module
    # makes about destination math depends on it. Check rather than trust: a
    # silently non-tiling plan would produce overlapping placements that
    # createOverwriteItemAction resolves by eating footage, which is exactly
    # the "false cut" failure this project refuses to risk.
    for prev, cur in zip(spans, spans[1:]):
        if cur.src_in_ms != prev.src_out_ms:
            raise ValueError(
                f"spans do not tile: span {prev.idx} ends at {prev.src_out_ms}ms "
                f"but span {cur.idx} starts at {cur.src_in_ms}ms. CutSpan's "
                "contract guarantees a contiguous, exhaustive tiling; an "
                "assemble plan built from a gapped or overlapping one would "
                "place footage wrong. Refusing."
            )

    # One conversion per boundary, shared by both adjacent spans — see the
    # module docstring. N spans have N+1 boundaries.
    boundary_ms = [spans[0].src_in_ms] + [s.src_out_ms for s in spans]
    seq_frames = [ms_to_frame(ms, tb) for ms in boundary_ms]
    src_frames = [ms_to_frame(ms - clip_start_ms + in_point_ms, tb) for ms in boundary_ms]

    if src_frames[0] < 0:
        raise ValueError(
            f"span 0 maps to source frame {src_frames[0]} — before the start of "
            f"the media. clip_start_ms={clip_start_ms} / in_point_ms={in_point_ms} "
            "do not match the descriptor this plan was built from. Refusing."
        )

    origin = seq_frames[0]
    entries = [
        {
            "idx": s.idx,
            "action": s.action,
            "enabled": s.action != CUT,
            "src_in_frame": src_frames[i],
            "src_out_frame": src_frames[i + 1],
            "seq_frame": seq_frames[i] - origin,
            "reason": s.reason,
        }
        for i, s in enumerate(spans)
    ]

    return _envelope(
        plan, tb, media_path, request_id,
        entries=entries,
        total_frames=seq_frames[-1] - origin,
    )


def _envelope(
    plan: CutPlan,
    tb,
    media_path: Optional[str],
    request_id: Optional[str],
    *,
    entries: list,
    total_frames: int,
) -> dict:
    """The wrapper every assemble plan carries, no-op or not.

    ``total_frames`` is the assembled sequence's expected length — the plugin
    asserts ``sequence.getEndTime()`` against it after Build, which is the
    cheapest possible check that nothing was misplaced.
    """
    return {
        "assemble_plan_version": ASSEMBLE_PLAN_VERSION,
        "job_id": plan.job_id,
        "request_id": request_id,
        "media_path": media_path,
        "timebase": {"fps_num": tb.fps_num, "fps_den": tb.fps_den},
        "total_frames": total_frames,
        "spans": entries,
    }
