"""Pipeline orchestrator — runs the full batch pipeline for one audio file.

`run_file` keeps its three-argument interface: it is the right shape, it is
genuinely deep, and the CLI, the eval harness and tools/make_gold.py all depend
on it. What changed is behind it — the 383-line undivided body now composes three
internal seams, each addressable by this package's own tests without a WAV file
or a database:

  plan.py        pure decisions: which engines, which phases to skip, whether
                 self-ensemble is valid, batch/overlap settings.
  engine_run.py  the load → decode → unload → persist bracket, written once for
                 both the real-Engine-B and self-ensemble-pseudo-B cases.
  refine.py      the post-decode token stages: align, reconcile, normalize,
                 filter, expand, force-align, conform.

Depth is a property of the interface, not the implementation.
"""

from __future__ import annotations

import logging
from pathlib import Path

import torch

from transcribe.db import store
from transcribe.pipeline import align_force, engine_run, ingest, refine
from transcribe.pipeline import plan as planning

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "1.0.0"

# The phase vocabulary is defined once, in plan.py — resume semantics depend on
# these exact strings. Named here too because this is where they are consumed.
_PHASE_RECONCILED = planning.PHASE_RECONCILED
_PHASE_WRITTEN = planning.PHASE_WRITTEN


def run_file(
    audio_path: str,
    config: dict,
    db_path: Path,
) -> list[dict]:
    """
    Run the full pipeline on one audio file.

    Returns list of token dicts: {"text", "start_ms", "end_ms", "script",
                                   "confidence", "source_engine"}
    These are also written to the DB.
    """
    conn = store.connect(db_path)

    # Bias terms from flywheel (+ weights for budget-aware prompt ranking, 5.1)
    bias_terms = store.get_bias_term_strings(conn)
    bias_weights = store.get_bias_term_weights(conn)

    # The resume key is (media, engine pair, pipeline version), so job identity
    # has to be decided before the job can be looked up. plan.make_plan below
    # re-derives the same names from the same function, so there is exactly one
    # rule — see canonical_engine_names for the defect that motivates it.
    engine_a_name, engine_b_name = planning.canonical_engine_names(config)

    # ── Media record ──────────────────────────────────────────────────────────
    media_id = store.create_media(conn, audio_path)

    # 4.1 (GAP-8): a 'failed' job for this exact media + engine pair + pipeline
    # version is resumable — reuse it instead of starting over from scratch, so
    # a crash after the (expensive, GPU-bound) engine passes doesn't cost them.
    resume_job = store.find_resumable_job(conn, media_id, engine_a_name, engine_b_name, PIPELINE_VERSION)
    if resume_job is not None:
        job_id = resume_job.id
        resume_phase = resume_job.job_phase
        logger.info("Resuming job %d from phase %r: %s", job_id, resume_phase, audio_path)
    else:
        job_id = store.create_job(conn, media_id, engine_a_name, engine_b_name, PIPELINE_VERSION)
        resume_phase = None
        logger.info("Job %d started: %s", job_id, audio_path)
    store.update_job_status(conn, job_id, "running")

    # ── Timebase probe (GAP-1) — best-effort; needs ffprobe + a video stream ──
    try:
        from transcribe.timebase import probe as probe_timebase
        tb = probe_timebase(audio_path)
        store.set_media_timebase(conn, media_id, tb.fps_num, tb.fps_den, tb.is_vfr)
        if tb.is_vfr:
            logger.warning(
                "Job %d: source is VFR (variable frame rate) — frame-based export "
                "requires a conformed CFR proxy (config conform_vfr: true)", job_id
            )
    except Exception as e:
        logger.info("Timebase probe skipped (%s)", e)

    try:
        # ── Plan ──────────────────────────────────────────────────────────────
        # Inside the try so a rejected plan (e.g. self_ensemble with a chunk
        # Engine A) marks the job failed exactly as it always did. Logged as a
        # value so a resumed job's decisions can be read rather than inferred.
        job_plan = planning.make_plan(config, resume_phase)
        logger.info("Job %d plan: %s", job_id, job_plan)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Using device: %s", device)

        # ── Phase 2: Ingestion — decode ONCE, share the array with the engines ─
        audio_arr, sr = ingest.load_audio(audio_path)
        ingest_result = ingest.ingest(
            audio_path,
            # Denoise only helps chunk engines. Whole-file engines load the raw
            # track, so denoising here burns ~1.8k file writes/hr and desyncs the
            # silence timeline from the audio the engine actually hears (3.2).
            denoise=config.get("denoise", True) and job_plan.chunk_engine_active,
            vad_threshold=float(config.get("vad_threshold", 0.5)),
            vad_min_speech_ms=int(config.get("vad_min_speech_ms", 250)),
            vad_min_silence_ms=int(config.get("vad_min_silence_ms", 300)),
            rms_gate_enabled=bool(config.get("rms_gate_enabled", True)),
            rms_gate_floor_db=(float(config["rms_gate_floor_db"])
                               if config.get("rms_gate_floor_db") is not None else None),
            rms_gate_floor_percentile=float(config.get("rms_gate_floor_percentile", 10.0)),
            rms_gate_min_gap_ms=int(config.get("rms_gate_min_gap_ms", 300)),
            audio=audio_arr, sr=sr,
            materialize_chunks=job_plan.chunk_engine_active,
            chunk_overlap_ms=job_plan.chunk_overlap_ms if job_plan.chunk_engine_active else 0,
        )
        chunks = ingest_result.chunks
        # The exact array the VAD/spans came from — feed it to the engine so the
        # silence filter can never drop words the engine heard (3.2).
        engine_audio = ingest_result.audio
        logger.info("Ingestion: %d chunks, %d VAD spans", len(chunks), len(ingest_result.spans))

        # Persist the VAD master timeline (GAP-3). Ingestion isn't itself
        # persisted across a resume (4.1) — it's cheap/CPU-only and deterministic,
        # so it always re-runs; clear any spans a prior attempt already wrote so
        # resuming doesn't duplicate them against the UNIQUE(job_id, idx) index.
        store.delete_speech_spans(conn, job_id)
        store.bulk_create_speech_spans(conn, job_id, [
            {"idx": s.idx, "start_ms": s.start_ms, "end_ms": s.end_ms, "kind": s.kind}
            for s in ingest_result.spans
        ])
        silence_spans = [
            (s.start_ms, s.end_ms) for s in ingest_result.spans if s.kind == "silence"
        ]

        # ── Phase 3: Dual-engine transcription (sequential) ───────────────────
        hypotheses = engine_run.run_engines(
            conn, job_id, job_plan,
            engine_run.DecodeInputs(
                chunks=chunks,
                full_audio=engine_audio if job_plan.needs_full_audio else None,
                bias_terms=bias_terms,
                bias_weights=bias_weights,
            ),
            device, config,
        )

        # ── Phases 4-7b: align, reconcile, normalize, filter, conform ─────────
        # CTCForcedAligner's constructor only records a device (the model loads
        # inside align()), so building it here costs nothing on the whole-file
        # path that never calls it.
        pipeline_tokens = refine.refine(
            hypotheses,
            config=config,
            bias_terms=bias_terms,
            silence_spans=silence_spans,
            audio=engine_audio,
            sample_rate=ingest_result.sample_rate,
            aligner=align_force.CTCForcedAligner(device=device),
            on_reconciled=lambda: store.update_job_phase(conn, job_id, _PHASE_RECONCILED),
        )

        # ── Write to DB ───────────────────────────────────────────────────────
        db_rows = [{
            "job_id": job_id,
            "idx": t.idx,
            "text": t.text,
            "start_ms": t.start_ms,
            "end_ms": t.end_ms,
            "script": t.script,
            "confidence": t.confidence,
            "source_engine": t.source_engine,
            "speaker_id": None,
        } for t in pipeline_tokens]
        # A resumed job may have partially written tokens from the attempt that
        # crashed after this point but before job_phase reached 'written' (4.1) —
        # clear first so the UNIQUE(job_id, idx) index can't reject the re-write.
        store.delete_tokens(conn, job_id)
        store.bulk_create_tokens(conn, db_rows)
        store.update_job_phase(conn, job_id, _PHASE_WRITTEN)
        store.update_job_status(conn, job_id, "done")
        logger.info("Job %d done: %d tokens written", job_id, len(pipeline_tokens))
        print(f"JOB_ID={job_id}", flush=True)

    except Exception:
        store.update_job_status(conn, job_id, "failed")
        conn.close()
        raise

    conn.close()
    return [
        {
            "idx": t.idx, "text": t.text, "start_ms": t.start_ms, "end_ms": t.end_ms,
            "script": t.script, "confidence": t.confidence, "source_engine": t.source_engine,
        }
        for t in pipeline_tokens
    ]


if __name__ == "__main__":
    import argparse, yaml, logging as _logging
    _logging.basicConfig(level=_logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("audio")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--db", default="transcriber.db")
    args = parser.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    tokens = run_file(args.audio, cfg, Path(args.db))
    import sys, io
    out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    for t in tokens:
        out.write(f"[{t['start_ms']:>7}–{t['end_ms']:>7}ms] {t['text']}\n")
    out.flush()
