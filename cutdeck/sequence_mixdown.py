"""sequence_mixdown.py — sequence-mixdown ingest path (Phase 2,
docs/HANDOFF_CUTDECK_LIVE_SEQUENCE.md).

**Superseded as the in-place timestamp source by ``cutdeck/live_clip.py``**
(issue #17/#20), which reads the clip's original media file directly instead
of requiring a rendered mixdown export — no render wait, full-quality audio,
and it sidesteps the fabricated-25fps timebase trap this module documents
below. This module stays in place for now; it is not the path the UXP
Mark/Apply feature uses.

A thin wrapper, not new pipeline code:

    export mixdown (dialogue tracks) from a live sequence   [human/CEP step]
            |
            v
    transcribe.pipeline.ingest.ingest(mixdown_path, ...)      # existing, unmodified
            |  -> VAD speech/silence spans
            v
    cutdeck.rules.build_cut_spans(tokens=[], spans, duration_ms, cfg)  # existing, unmodified
            |  fillers_enabled / repeats_enabled stay at config default (False)
            v
    CutPlan (sequence time, since the mixdown IS the sequence's own audio)

No ASR engine is imported or run anywhere in this module — the mixdown IS the
sequence's own audio, already in sequence time, so this mode needs no transcript
and no offset math (see the handoff's timestamp-source table).
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import replace
from pathlib import Path
from typing import Optional

from cutdeck.contracts import CutConfig, CutPlan
from cutdeck.plan import build_plan
from cutdeck.rules import build_cut_spans
from transcribe.console import safe_print
from transcribe.pipeline.ingest import ingest
from transcribe.timebase import Timebase, probe

logger = logging.getLogger(__name__)


def plan_from_mixdown(
    mixdown_path: str,
    job_id: int,
    cfg: CutConfig,
    timebase: Optional[Timebase] = None,
    **ingest_kwargs,
) -> CutPlan:
    """Build a silence-removal ``CutPlan`` from a sequence's own audio mixdown.

    ``timebase`` defaults to probing ``mixdown_path`` directly — pass the live
    sequence's own ``Timebase`` when known (mixdown export usually has no video
    stream to probe fps from). ``ingest_kwargs`` forward to ``ingest()`` (e.g.
    ``rms_gate_enabled=False`` for a deterministic test run).

    ``cfg.fillers_enabled`` / ``cfg.repeats_enabled`` need a real word timeline,
    which a mixdown-only run (no ASR pass) never builds — if either is on, this
    degrades to silence-only removal with a logged warning rather than crashing
    or silently guessing a word timeline. Run the full ASR pipeline on the
    mixdown first (a separate job) if word-level cuts are actually needed.
    """
    if cfg.fillers_enabled or cfg.repeats_enabled:
        logger.warning(
            "sequence-mixdown ingest has no transcript for job %d — degrading "
            "cfg.fillers_enabled=%s / cfg.repeats_enabled=%s to silence-only "
            "removal. Run the full ASR pipeline on the mixdown first if "
            "word-level cuts are needed.",
            job_id, cfg.fillers_enabled, cfg.repeats_enabled,
        )
        cfg = replace(cfg, fillers_enabled=False, repeats_enabled=False)

    result = ingest(mixdown_path, materialize_chunks=False, **ingest_kwargs)
    duration_ms = result.duration_ms
    if timebase is not None:
        tb = timebase
    else:
        tb = probe(mixdown_path)
        logger.warning(
            "no timebase given for job %d — probed %s directly. A mixdown export "
            "is usually audio-only, so probe() silently falls back to a fabricated "
            "25fps timebase when it finds no video stream. Pass the live sequence's "
            "own Timebase explicitly (or --fps on the CLI) unless it really is "
            "25fps — a wrong timebase here mis-times every cut computed from "
            "this plan.",
            job_id, mixdown_path,
        )

    cut_spans = build_cut_spans(
        tokens=[], spans=result.spans, duration_ms=duration_ms, cfg=cfg,
    )

    from transcribe.db import store
    media_sha256 = store.sha256_of_file(mixdown_path)

    return build_plan(
        job_id=job_id,
        media_sha256=media_sha256,
        timebase=tb,
        duration_ms=duration_ms,
        spans=cut_spans,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

_DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "transcribe" / "config.yaml"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Build an in-place CutPlan from a live sequence's audio mixdown."
    )
    ap.add_argument("mixdown_path")
    ap.add_argument("--job-id", type=int, required=True)
    ap.add_argument("--fps", type=float, default=None,
                     help="the live sequence's own frame rate (e.g. 29.97, 25, 23.976). "
                          "A mixdown export is audio-only, so it has no video stream to "
                          "probe fps from — probing it directly silently falls back to a "
                          "fabricated 25fps timebase (transcribe.timebase.probe's "
                          "no-video-stream default). Required unless the sequence really "
                          "is 25fps, since a wrong timebase here mis-times every cut "
                          "computed from this plan.")
    ap.add_argument("--config", default=str(_DEFAULT_CONFIG))
    ap.add_argument("--db", default=None, help="SQLite path (defaults to store default)")
    ap.add_argument("--dry-run", action="store_true", help="print plan, do not persist")
    args = ap.parse_args(argv)

    import yaml

    from cutdeck import plan as planmod
    from transcribe.db import store

    cfg = CutConfig.from_yaml(yaml.safe_load(Path(args.config).read_text(encoding="utf-8")))
    timebase = Timebase.from_decimal_fps(args.fps) if args.fps is not None else None
    plan = plan_from_mixdown(args.mixdown_path, args.job_id, cfg, timebase=timebase)
    n_cut = sum(1 for s in plan.spans if s.action == "cut")
    cut_ms = sum(s.duration_ms for s in plan.spans if s.action == "cut")

    if args.dry_run:
        # ensure_ascii=False (see plan.dumps) — same latent Thai path as plan.py.
        safe_print(planmod.dumps(plan))
    else:
        conn = store.connect(Path(args.db)) if args.db else store.connect()
        try:
            plan_id = planmod.save_plan(conn, plan)
            print(f"saved cut_plan id={plan_id}")
        finally:
            conn.close()
    print(f"job {args.job_id}: {len(plan.spans)} spans, {n_cut} cuts, "
          f"{cut_ms} ms removed of {plan.duration_ms} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
