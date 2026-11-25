from __future__ import annotations

import logging
from pathlib import Path

import torch

from transcribe.db import store
from transcribe.contracts import PipelineToken
from transcribe.pipeline import align_force, coverage, engine_run, ingest, refine
from transcribe.pipeline import word_align
from transcribe.pipeline import plan as planning

logger = logging.getLogger(__name__)

# Finished transcripts are cached by media sha256 + this version: bump it when a
# code change alters decode output, or cached media keep the old transcript.
PIPELINE_VERSION = "1.0.2"

_PHASE_RECONCILED = planning.PHASE_RECONCILED
_PHASE_WRITTEN = planning.PHASE_WRITTEN


def _ingest_for_plan(audio_path: str, config: dict, job_plan) -> ingest.IngestResult:
    audio_arr, sr = ingest.load_audio(audio_path)
    return ingest.ingest(
        audio_path,
        denoise=config.get("denoise", True) and job_plan.chunk_engine_active,
        **ingest.ingest_settings(config),
        audio=audio_arr, sr=sr,
        materialize_chunks=job_plan.chunk_engine_active,
        chunk_overlap_ms=job_plan.chunk_overlap_ms if job_plan.chunk_engine_active else 0,
    )


def _fill_coverage_gaps(tokens, ingest_result, job_plan, device, config, engine=None):
    cues = [{"text": t.text, "start_ms": t.start_ms, "end_ms": t.end_ms, "script": t.script,
             "confidence": t.confidence, "source_engine": t.source_engine} for t in tokens]
    speech = [(s.start_ms, s.end_ms) for s in ingest_result.spans if s.kind == "speech"]
    gaps = coverage.find_gaps(speech, cues)
    if not gaps:
        return tokens
    logger.info("Coverage guard: %d gap(s) to re-decode", len(gaps))
    try:
        redecoder_ctx = engine_run.gap_redecoder(job_plan, device, config, ingest_result.audio,
                                                ingest_result.sample_rate, engine=engine)
    except TypeError:
        redecoder_ctx = engine_run.gap_redecoder(job_plan, device, config, ingest_result.audio,
                                                ingest_result.sample_rate)
    with redecoder_ctx as redecode:
        filled, _still_empty = coverage.fill_gaps(cues, gaps, redecode)
    return [PipelineToken(idx=i, text=c["text"], start_ms=c["start_ms"], end_ms=c["end_ms"],
                          script=c["script"], confidence=c["confidence"],
                          source_engine=c.get("source_engine", "a"))
            for i, c in enumerate(filled)]


def run_file(
    audio_path: str,
    config: dict,
    db_path: Path,
    ingest_result: ingest.IngestResult | None = None,
    *,
    sha256: str | None = None,
    engine_a=None,
) -> list[dict]:
    """Run the pipeline and return the token dicts. See `run_file_job`."""
    return run_file_job(
        audio_path, config, db_path, ingest_result,
        sha256=sha256, engine_a=engine_a,
    )[1]


def _align_word_starts(conn, job_id: int, cues: list, ingest_result, device: str, cfg: dict) -> None:
    import json
    result = store.get_engine_result(conn, job_id, "a")
    words = json.loads(result.raw_words_json) if result and result.raw_words_json else []
    if not words:
        return
    try:
        new = word_align.align_words(words, cues, ingest_result.audio, ingest_result.sample_rate, device, cfg)
    finally:
        engine_run._free_vram()
    store.save_engine_result(conn, job_id, "a", result.engine_name, result.tokens_json,
                             result.timestamps_final, json.dumps(new, ensure_ascii=False))
    moved = sum(o["start_ms"] != n["start_ms"] for o, n in zip(words, new))
    logger.info("Job %d: word_align moved %d of %d word starts", job_id, moved, len(words))


def run_file_job(
    audio_path: str,
    config: dict,
    db_path: Path,
    ingest_result: ingest.IngestResult | None = None,
    glossary: tuple[str, ...] | list[str] = (),
    *,
    sha256: str | None = None,
    engine_a=None,
) -> tuple[int, list[dict]]:
    """
    Run the full pipeline on one audio file; returns `(job_id, tokens)`.

    Returns list of token dicts: {"text", "start_ms", "end_ms", "script",
                                   "confidence", "source_engine"}
    These are also written to the DB.

    `glossary`: extra terms for this job only (show title, names, brands). They join the
    flywheel's bias terms for the decode and are not written to the bias index.

    `ingest_result`: an `ingest()` result the caller already computed for this
    exact file with the same VAD settings and `denoise=False`. Reused only when
    no chunk engine is active (whole-file engines want the raw track and no
    chunks); otherwise ignored and ingestion runs as usual.
    """
    align_cfg = config.get("word_align") or {}
    if align_cfg.get("enabled"):
        word_align.model_path(align_cfg.get("model", word_align.DEFAULT_MODEL))
    store.init_db(db_path)
    conn = store.connect(db_path)

    bias_terms = store.get_bias_term_strings(conn)
    bias_weights = store.get_bias_term_weights(conn)
    for term in dict.fromkeys(t.strip() for t in glossary if t and t.strip()):
        if term not in bias_weights:
            bias_terms.append(term)
        bias_weights[term] = max([1.0, *bias_weights.values()])
    resume_fingerprint = planning.resume_fingerprint(config, bias_terms, bias_weights)

    engine_a_name, engine_b_name = planning.canonical_engine_names(config)

    media_id = store.create_media(conn, audio_path, sha256=sha256)

    resume_job = store.find_resumable_job(
        conn, media_id, engine_a_name, engine_b_name, PIPELINE_VERSION, resume_fingerprint)
    if resume_job is not None:
        job_id = resume_job.id
        resume_phase = resume_job.job_phase
        logger.info("Resuming job %d from phase %r: %s", job_id, resume_phase, audio_path)
    else:
        job_id = store.create_job(
            conn, media_id, engine_a_name, engine_b_name, PIPELINE_VERSION, resume_fingerprint)
        resume_phase = None
        logger.info("Job %d started: %s", job_id, audio_path)
    store.update_job_status(conn, job_id, "running")

    try:
        from transcribe.timebase import probe as probe_timebase
        tb = probe_timebase(audio_path)
        store.set_media_timebase(conn, media_id, tb.fps_num, tb.fps_den, tb.is_vfr)
        if tb.is_vfr:
            logger.warning(
                "Job %d: source is VFR (variable frame rate) — frame-based cuts "
                "need a constant-frame-rate copy", job_id
            )
    except Exception as e:
        logger.info("Timebase probe skipped (%s)", e)

    try:
        job_plan = planning.make_plan(config, resume_phase)
        logger.info("Job %d plan: %s", job_id, job_plan)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Using device: %s", device)

        if ingest_result is not None and job_plan.chunk_engine_active:
            ingest_result = None
        if ingest_result is None:
            ingest_result = _ingest_for_plan(audio_path, config, job_plan)
        if getattr(ingest_result, "duration_ms", None) is not None:
            store.set_media_duration(conn, media_id, ingest_result.duration_ms)
        chunks = ingest_result.chunks
        engine_audio = ingest_result.audio
        logger.info("Ingestion: %d chunks, %d VAD spans", len(chunks), len(ingest_result.spans))

        store.delete_speech_spans(conn, job_id)
        store.bulk_create_speech_spans(conn, job_id, [
            {"idx": s.idx, "start_ms": s.start_ms, "end_ms": s.end_ms, "kind": s.kind}
            for s in ingest_result.spans
        ])
        silence_spans = [
            (s.start_ms, s.end_ms) for s in ingest_result.spans if s.kind == "silence"
        ]
        speech_spans = tuple(
            (s.start_ms, s.end_ms) for s in ingest_result.spans if s.kind == "speech"
        )

        coverage_enabled = bool((config.get("coverage_guard") or {}).get("enabled", False))
        caller_owns_engine_a = engine_a is not None
        keep_engine_a = caller_owns_engine_a or (
            coverage_enabled and (
                job_plan.engine_b_name == "passthrough" or job_plan.self_ensemble_enabled
            ) and not job_plan.skip_engine_a
        )

        resident_engine_a = None
        try:
            decode_inputs = engine_run.DecodeInputs(
                chunks=chunks,
                full_audio=engine_audio if job_plan.needs_full_audio else None,
                bias_terms=bias_terms,
                bias_weights=bias_weights,
                speech_spans=speech_spans,
            )
            try:
                run_res = engine_run.run_engines(
                    conn, job_id, job_plan, decode_inputs, device, config,
                    keep_engine_a_resident=keep_engine_a,
                    engine_a=engine_a,
                )
            except TypeError:
                try:
                    run_res = engine_run.run_engines(
                        conn, job_id, job_plan, decode_inputs, device, config,
                        keep_engine_a_resident=keep_engine_a,
                    )
                except TypeError:
                    run_res = engine_run.run_engines(
                        conn, job_id, job_plan, decode_inputs, device, config,
                    )
            if isinstance(run_res, tuple) and len(run_res) == 2:
                hypotheses, resident_engine_a = run_res
            else:
                hypotheses = run_res
                resident_engine_a = None

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

            if coverage_enabled:
                pipeline_tokens = _fill_coverage_gaps(
                    pipeline_tokens, ingest_result, job_plan, device, config,
                    engine=resident_engine_a or engine_a,
                )
        finally:
            if resident_engine_a is not None and not caller_owns_engine_a:
                try:
                    resident_engine_a.unload()
                finally:
                    del resident_engine_a
                    engine_run._free_vram()

        if align_cfg.get("enabled"):
            if caller_owns_engine_a:
                raise ValueError("word_align loads its own model: run without a resident engine_a")
            _align_word_starts(conn, job_id, pipeline_tokens, ingest_result, device, align_cfg)

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
    return job_id, [
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
    parser.add_argument("--db", default=None, help="default: store.path from config")
    args = parser.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    tokens = run_file(args.audio, cfg, Path(args.db) if args.db else store.resolve_db_path(cfg))
    import sys, io
    out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    for t in tokens:
        out.write(f"[{t['start_ms']:>7}–{t['end_ms']:>7}ms] {t['text']}\n")
    out.flush()
