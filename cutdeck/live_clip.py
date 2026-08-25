"""live_clip.py — CutPlan from a live Premiere clip descriptor (issue #17/#20).

Supersedes ``sequence_mixdown.py`` as the in-place timestamp source. That
module assumed the editor exports an audio mixdown from the live sequence;
this one reads the clip's **original media file** directly, using positions
the UXP plugin already has for free: ``getProjectItem()`` -> ``getMediaFilePath()``,
``getStartTime()``, ``getInPoint()``, ``getOutPoint()``. Reading the original
file means no render wait and full-quality audio instead of a re-encode, and
it never triggers the trap ``sequence_mixdown.py`` documents — a mixdown
export is usually audio-only, so ``probe()`` silently falls back to a
fabricated 25fps timebase. The timebase arrives from the live sequence
instead (never probed here). ``media_sha256`` is stamped onto the returned
plan the same way every other CutPlan producer does it, using the existing
``store.sha256_of_file`` — no per-request ingest caching keyed on it exists
yet, so a re-run still re-runs VAD; that would need a store-level cache
lookup, which is out of scope here.

``sequence_mixdown.py`` stays in place; it is not the path this feature uses.

Pipeline, all existing and unmodified:

    ingest(media_path)  ->  VAD speech/silence spans          (source time)
    build_cut_spans(tokens=[], spans, duration_ms, cfg)  ->  CutPlan  (source time)
    clamp to [in_point_ms, out_point_ms]  ->  offset to sequence time

Offset: ``sequence_ms = clip_start_ms + (source_ms - clip_in_point_ms)``,
valid only at unit speed with playback not reversed — see ``ClipDescriptor``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Optional

from cutdeck.contracts import PLAN_VERSION, CutConfig, CutPlan, CutSpan, Timebase
from cutdeck.rules import build_cut_spans
from transcribe.pipeline.ingest import ingest

logger = logging.getLogger(__name__)


class LiveClipRefused(ValueError):
    """A clip descriptor that ``plan_from_live_clip`` refuses to plan against.

    Carries a machine-readable ``reason`` (for the bridge's structured error
    response, see ``cutdeck/bridge.py``) alongside the human-readable message
    an editor can be shown directly.
    """

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class ClipDescriptor:
    """What the UXP plugin sends to describe one clip on the live sequence.

    ``clip_start_ms``/``in_point_ms``/``out_point_ms`` are all read directly
    off the Premiere ``TrackItem`` (``getStartTime()``, ``getInPoint()``,
    ``getOutPoint()``) — no probing, no guessing. ``timebase`` is the
    *sequence's* own timebase, never the media file's.
    """

    media_path: str
    clip_start_ms: int
    in_point_ms: int
    out_point_ms: int
    timebase: Timebase
    speed: float = 1.0
    reversed: bool = False


def plan_from_live_clip(
    clip: ClipDescriptor,
    job_id: int,
    cfg: CutConfig,
    **ingest_kwargs,
) -> CutPlan:
    """Build a silence-removal ``CutPlan`` in **sequence time** from a live clip.

    Raises ``LiveClipRefused`` if ``clip.speed != 1.0`` or ``clip.reversed`` —
    the source-to-sequence offset above is only valid at unit, forward speed;
    under a speed change it would silently mistime every cut. This is the
    single most important guard in this module: never guess.

    ``cfg.fillers_enabled``/``cfg.repeats_enabled`` need a real word timeline,
    which a transcript-free run never builds — degrades to silence-only
    removal with a logged warning, same discipline as ``plan_from_mixdown``.

    Silence detected in the source media outside ``[in_point_ms, out_point_ms]``
    is not on the timeline and is clamped away rather than producing a mark.
    """
    if clip.speed != 1.0:
        raise LiveClipRefused(
            "speed_change",
            f"clip speed is {clip.speed}, not 1.0 — the source-to-sequence "
            "offset mapping is only valid at unit speed; cutting this clip "
            "would silently mistime every cut. Refusing.",
        )
    if clip.reversed:
        raise LiveClipRefused(
            "reversed",
            "clip is time-reversed — the source-to-sequence offset mapping "
            "does not hold under reversed playback. Refusing.",
        )

    if cfg.fillers_enabled or cfg.repeats_enabled:
        logger.warning(
            "live-clip ingest has no transcript for job %d — degrading "
            "cfg.fillers_enabled=%s / cfg.repeats_enabled=%s to silence-only "
            "removal. A live-clip run has no word timeline either.",
            job_id, cfg.fillers_enabled, cfg.repeats_enabled,
        )
        cfg = replace(cfg, fillers_enabled=False, repeats_enabled=False)

    result = ingest(clip.media_path, materialize_chunks=False, **ingest_kwargs)
    duration_ms = result.duration_ms

    source_spans = build_cut_spans(
        tokens=[], spans=result.spans, duration_ms=duration_ms, cfg=cfg,
    )
    sequence_spans = _clamp_and_offset(
        source_spans, clip.in_point_ms, clip.out_point_ms, clip.clip_start_ms,
    )

    from transcribe.db import store
    media_sha256 = store.sha256_of_file(clip.media_path)

    return CutPlan(
        job_id=job_id,
        media_sha256=media_sha256,
        timebase=clip.timebase,
        spans=sequence_spans,
        plan_version=PLAN_VERSION,
    )


def _clamp_and_offset(
    spans: list[CutSpan], in_point_ms: int, out_point_ms: int, clip_start_ms: int,
) -> list[CutSpan]:
    """Clamp source-time spans to the clip's visible range, then translate to
    sequence time. Clamping a contiguous, exhaustive tiling to a sub-interval
    keeps it contiguous over that sub-interval, so the result still tiles
    ``[clip_start_ms, clip_start_ms + (out_point_ms - in_point_ms)]`` exactly —
    only spans that fall entirely outside the visible range are dropped."""
    offset = clip_start_ms - in_point_ms
    out: list[CutSpan] = []
    for s in spans:
        src_in = max(s.src_in_ms, in_point_ms)
        src_out = min(s.src_out_ms, out_point_ms)
        if src_out <= src_in:
            continue
        out.append(replace(s, idx=len(out), src_in_ms=src_in + offset, src_out_ms=src_out + offset))
    return out
