"""plan.py — CutPlan assembly, validation, serialization, and the Phase-1 CLI.

The CutPlan is the system's contract artifact (IMPLEMENT_CUTDECK.md §B.3). Spans
are **contiguous and exhaustive** over the media duration — a cut is represented,
not deleted — so the review UI and the flywheel diff both see the full picture.
:func:`build_plan` enforces that invariant with an assertion (no gaps, no
overlaps, starts at 0, ends at duration).

This module also wires the deterministic pass to the store: ``python -m
cutdeck.plan --job-id N`` reads a job's tokens + VAD spans + media timebase,
builds a deterministic CutPlan, and persists it as a ``cut_plan`` row.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

import yaml

from cutdeck.contracts import (
    PLAN_VERSION,
    CutConfig,
    CutPlan,
    CutSpan,
    Segment,
    Timebase,
)
from cutdeck.rules import build_cut_spans
from cutdeck.segment import segment_tokens


# ── assembly + validation ─────────────────────────────────────────────────────

def assert_contiguous_exhaustive(spans: list[CutSpan], duration_ms: int) -> None:
    """Spans must tile [0, duration_ms] with no gaps and no overlaps.

    This is the one invariant the rest of the system (XML export, review UI,
    diff) relies on, so it is checked, not assumed.
    """
    if not spans:
        raise ValueError("CutPlan has no spans")
    if spans[0].src_in_ms != 0:
        raise ValueError(f"plan must start at 0, starts at {spans[0].src_in_ms}")
    if spans[-1].src_out_ms != duration_ms:
        raise ValueError(
            f"plan must end at duration {duration_ms}, ends at {spans[-1].src_out_ms}"
        )
    for i, s in enumerate(spans):
        if s.src_out_ms <= s.src_in_ms:
            raise ValueError(f"span {i} is non-positive: [{s.src_in_ms}, {s.src_out_ms}]")
        if s.idx != i:
            raise ValueError(f"span at position {i} has idx {s.idx} (must be contiguous)")
    for a, b in zip(spans, spans[1:]):
        if b.src_in_ms != a.src_out_ms:
            raise ValueError(
                f"gap/overlap between span {a.idx} (ends {a.src_out_ms}) and "
                f"{b.idx} (starts {b.src_in_ms})"
            )


def _attach_segments(spans: list[CutSpan], segments: list[Segment]) -> None:
    """Record on each span the ids of segments whose midpoint falls inside it."""
    for seg in segments:
        mid = (seg.start_ms + seg.end_ms) // 2
        for s in spans:
            if s.src_in_ms <= mid < s.src_out_ms:
                s.segment_ids.append(seg.id)
                break


def build_plan(
    job_id: int,
    media_sha256: str,
    timebase: Timebase,
    duration_ms: int,
    spans: list[CutSpan],
    segments: Optional[list[Segment]] = None,
    plan_version: str = PLAN_VERSION,
) -> CutPlan:
    """Validate the deterministic spans and wrap them in a CutPlan artifact."""
    assert_contiguous_exhaustive(spans, duration_ms)
    if segments:
        _attach_segments(spans, segments)
    return CutPlan(
        job_id=job_id,
        media_sha256=media_sha256,
        timebase=timebase,
        spans=spans,
        plan_version=plan_version,
    )


# ── serialization ─────────────────────────────────────────────────────────────

def to_dict(plan: CutPlan) -> dict:
    return {
        "plan_version": plan.plan_version,
        "job_id": plan.job_id,
        "media_sha256": plan.media_sha256,
        "timebase": {"fps_num": plan.timebase.fps_num, "fps_den": plan.timebase.fps_den},
        "spans": [
            {
                "idx": s.idx,
                "src_in_ms": s.src_in_ms,
                "src_out_ms": s.src_out_ms,
                "action": s.action,
                "reason": s.reason,
                "source": s.source,
                "segment_ids": list(s.segment_ids),
            }
            for s in plan.spans
        ],
    }


def from_dict(data: dict) -> CutPlan:
    tb = data["timebase"]
    spans = [
        CutSpan(
            idx=s["idx"],
            src_in_ms=s["src_in_ms"],
            src_out_ms=s["src_out_ms"],
            action=s["action"],
            reason=s.get("reason"),
            source=s.get("source"),
            segment_ids=list(s.get("segment_ids", [])),
        )
        for s in data["spans"]
    ]
    return CutPlan(
        job_id=data["job_id"],
        media_sha256=data["media_sha256"],
        timebase=Timebase(fps_num=tb["fps_num"], fps_den=tb["fps_den"]),
        spans=spans,
        plan_version=data.get("plan_version", PLAN_VERSION),
    )


def dumps(plan: CutPlan) -> str:
    """Deterministic JSON (ensure_ascii=False to keep Thai readable in the DB)."""
    return json.dumps(to_dict(plan), ensure_ascii=False, sort_keys=True)


def loads(text: str) -> CutPlan:
    return from_dict(json.loads(text))


# ── store glue ────────────────────────────────────────────────────────────────

def save_plan(conn, plan: CutPlan, status: str = "proposed") -> int:
    from transcribe.db import store
    return store.create_cut_plan(conn, plan.job_id, plan.plan_version, dumps(plan), status)


def load_plan(conn, plan_id: int) -> Optional[CutPlan]:
    from transcribe.db import store
    row = store.get_cut_plan(conn, plan_id)
    if row is None:
        return None
    return loads(row.plan_json)


# ── job → plan ────────────────────────────────────────────────────────────────

def _timebase_from_media(media) -> Timebase:
    """Build a Timebase from a stored MediaRow, defaulting unprobed media to 25fps."""
    if media.fps_num and media.fps_den:
        return Timebase(
            fps_num=media.fps_num,
            fps_den=media.fps_den,
            duration_ms=media.duration_ms,
            is_vfr=bool(media.is_vfr),
        )
    return Timebase(fps_num=25, fps_den=1, duration_ms=media.duration_ms,
                    is_vfr=bool(media.is_vfr))


def propose_for_job(conn, job_id: int, cfg: CutConfig) -> CutPlan:
    """Read a job's tokens + VAD spans + timebase from the store and build a plan."""
    from transcribe.db import store

    job = store.get_job(conn, job_id)
    if job is None:
        raise ValueError(f"job {job_id} not found")
    media = store.get_media(conn, job.media_id)
    if media is None:
        raise ValueError(f"media {job.media_id} for job {job_id} not found")

    tokens = store.get_tokens(conn, job_id)
    spans = store.get_speech_spans(conn, job_id)

    # Duration truth: prefer probed media duration, else the furthest timeline edge.
    edges = [media.duration_ms or 0]
    if tokens:
        edges.append(max(t.end_ms for t in tokens))
    if spans:
        edges.append(max(s.end_ms for s in spans))
    duration_ms = max(edges)
    if duration_ms <= 0:
        raise ValueError(f"job {job_id} has no timeline (no duration, tokens, or spans)")

    segments = segment_tokens(tokens, spans, cfg)
    cut_spans = build_cut_spans(tokens, spans, duration_ms, cfg)
    return build_plan(
        job_id=job_id,
        media_sha256=media.sha256,
        timebase=_timebase_from_media(media),
        duration_ms=duration_ms,
        spans=cut_spans,
        segments=segments,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Build a deterministic CutDeck plan for a job.")
    ap.add_argument("--job-id", type=int, required=True)
    ap.add_argument("--config", default="transcribe/config.yaml")
    ap.add_argument("--db", default=None, help="SQLite path (defaults to store default)")
    ap.add_argument("--dry-run", action="store_true", help="print plan, do not persist")
    args = ap.parse_args(argv)

    from transcribe.db import store

    cfg = CutConfig.from_yaml(yaml.safe_load(Path(args.config).read_text(encoding="utf-8")))
    conn = store.connect(Path(args.db)) if args.db else store.connect()
    try:
        plan = propose_for_job(conn, args.job_id, cfg)
        n_cut = sum(1 for s in plan.spans if s.action == "cut")
        cut_ms = sum(s.duration_ms for s in plan.spans if s.action == "cut")
        if args.dry_run:
            print(dumps(plan))
        else:
            plan_id = save_plan(conn, plan)
            print(f"saved cut_plan id={plan_id}")
        print(f"job {args.job_id}: {len(plan.spans)} spans, {n_cut} cuts, "
              f"{cut_ms} ms removed of {plan.duration_ms} ms")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
