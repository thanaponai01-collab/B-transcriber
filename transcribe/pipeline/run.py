"""Pipeline orchestrator — runs the full batch pipeline for one audio file."""

from __future__ import annotations

import logging
from pathlib import Path

import torch

from transcribe.contracts import EngineInput, PipelineToken, detect_script
from transcribe.db import store
from transcribe.engines.registry import get_engine
from transcribe.pipeline import align_force, align_hyp, ingest, normalize, reconcile, stitch

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "1.0.0"


def _log_vram(stage: str) -> None:
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        logger.info("[VRAM] %s: %.1f MB free / %.1f MB total", stage, free / 1e6, total / 1e6)


def _filter_hallucinations(tokens: list[PipelineToken], max_run: int = 3) -> list[PipelineToken]:
    """Remove tokens where the same word repeats more than max_run times in a row.

    Whisper hallucinates on silence/music by looping filler words.
    """
    if not tokens:
        return tokens
    result = []
    run = 0
    prev = None
    for tok in tokens:
        if tok.text == prev:
            run += 1
        else:
            run = 1
            prev = tok.text
        if run <= max_run:
            result.append(tok)
    removed = len(tokens) - len(result)
    if removed:
        logger.info("Hallucination filter removed %d repeated tokens", removed)
    return result


def _expand_to_words(tokens: list[PipelineToken]) -> list[PipelineToken]:
    """Split sentence-level tokens into word-level tokens for the CTC aligner.

    Uses pythainlp for Thai segments, whitespace split for Latin. Inherits
    the parent token's source_engine/confidence; timestamps are placeholders
    (the CTC aligner overwrites them).
    """
    result = []
    idx = 0
    for tok in tokens:
        if tok.script in ("thai", "mixed"):
            try:
                from pythainlp.tokenize import word_tokenize
                words = [w for w in word_tokenize(tok.text, engine="newmm") if w.strip()]
            except Exception:
                words = list(tok.text)  # character fallback
        else:
            words = tok.text.split()

        if not words:
            words = [tok.text]

        for word in words:
            result.append(PipelineToken(
                idx=idx,
                text=word,
                start_ms=tok.start_ms,
                end_ms=tok.end_ms,
                script=detect_script(word),
                confidence=tok.confidence,
                source_engine=tok.source_engine,
            ))
            idx += 1
    return result


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

    # Bias terms from flywheel
    bias_terms = store.get_bias_term_strings(conn)

    engine_a_name = config["engine_a"]
    engine_b_name = config["engine_b"]

    # ── Media record ──────────────────────────────────────────────────────────
    media_id = store.create_media(conn, audio_path)
    job_id = store.create_job(conn, media_id, engine_a_name, engine_b_name, PIPELINE_VERSION)
    store.update_job_status(conn, job_id, "running")
    logger.info("Job %d started: %s", job_id, audio_path)

    # ── Timebase probe (GAP-1) — best-effort; needs ffprobe + a video stream ──
    try:
        from transcribe.timebase import probe as probe_timebase
        tb = probe_timebase(audio_path)
        store.set_media_timebase(conn, media_id, tb.fps_num, tb.fps_den, tb.is_vfr)
        if tb.is_vfr:
            logger.warning(
                "Job %d: source is VFR (variable frame rate) — frame-based export "
                "requires a conformed CFR proxy (config ingest.conform_vfr)", job_id
            )
    except Exception as e:
        logger.info("Timebase probe skipped (%s)", e)

    try:
        # ── Phase 2: Ingestion ────────────────────────────────────────────────
        ingest_result = ingest.ingest(audio_path, denoise=config.get("denoise", True))
        chunks = ingest_result.chunks
        logger.info("Ingestion: %d chunks, %d VAD spans", len(chunks), len(ingest_result.spans))

        # Persist the VAD master timeline (GAP-3).
        store.bulk_create_speech_spans(conn, job_id, [
            {"idx": s.idx, "start_ms": s.start_ms, "end_ms": s.end_ms, "kind": s.kind}
            for s in ingest_result.spans
        ])
        silence_spans = [
            (s.start_ms, s.end_ms) for s in ingest_result.spans if s.kind == "silence"
        ]

        # ── Phase 3: Dual-engine transcription (sequential) ───────────────────
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Using device: %s", device)
        _log_vram("pre-engine-a")
        engine_a = get_engine(engine_a_name, device=device)
        engine_a.load()
        _log_vram("engine-a-loaded")

        engine_batch_size = int(config.get("engine_batch_size", 8))

        a_inputs = [
            EngineInput(audio=chunk.audio, bias_terms=bias_terms, language_hint="th")
            for chunk in chunks
        ]
        a_results = engine_a.transcribe_batch(a_inputs, batch_size=engine_batch_size)

        engine_a_word_level = False
        a_chunk_tokens: list[stitch.ChunkTokens] = []
        for chunk, result in zip(chunks, a_results):
            engine_a_word_level = engine_a_word_level or result.word_level_timestamps
            # Offset timestamps to global position
            for tok in result.tokens:
                tok.start_ms += chunk.start_ms
                tok.end_ms += chunk.start_ms
            a_chunk_tokens.append(stitch.ChunkTokens(result.tokens, chunk.start_ms, chunk.end_ms))

        # GAP-4: drop duplicate words from any chunk-overlap windows (no-op when
        # chunks do not overlap; ready once ingest emits ~0.5–1s overlap).
        result_a_tokens = stitch.stitch(a_chunk_tokens)

        engine_a.unload()
        del engine_a
        torch.cuda.empty_cache() if torch.cuda.is_available() else None
        _log_vram("post-engine-a")

        _log_vram("pre-engine-b")
        engine_b = get_engine(engine_b_name, device=device)
        engine_b.load()
        _log_vram("engine-b-loaded")

        b_inputs = [
            EngineInput(audio=chunk.audio, bias_terms=bias_terms, language_hint=None)
            for chunk in chunks
        ]
        b_results = engine_b.transcribe_batch(b_inputs, batch_size=engine_batch_size)

        b_chunk_tokens: list[stitch.ChunkTokens] = []
        for chunk, result in zip(chunks, b_results):
            for tok in result.tokens:
                tok.start_ms += chunk.start_ms
                tok.end_ms += chunk.start_ms
            b_chunk_tokens.append(stitch.ChunkTokens(result.tokens, chunk.start_ms, chunk.end_ms))

        result_b_tokens = stitch.stitch(b_chunk_tokens)

        engine_b.unload()
        del engine_b
        torch.cuda.empty_cache() if torch.cuda.is_available() else None
        _log_vram("post-engine-b")

        # ── Phase 4: Hypothesis alignment ────────────────────────────────────
        slots = align_hyp.align(result_a_tokens, result_b_tokens)
        logger.info("Alignment: %d slots", len(slots))

        # ── Phase 5: Reconciliation ───────────────────────────────────────────
        reconciled = reconcile.reconcile(slots, bias_terms=bias_terms)
        logger.info("Reconciled: %d tokens", len(reconciled))

        # ── Phase 6: Normalization ────────────────────────────────────────────
        pipeline_tokens: list[PipelineToken] = [
            PipelineToken(
                idx=idx,
                text=tok.text,
                start_ms=tok.start_ms,
                end_ms=tok.end_ms,
                script=tok.script,
                confidence=tok.confidence,
                source_engine=src,
            )
            for idx, (tok, src) in enumerate(reconciled)
        ]
        pipeline_tokens = normalize.normalize_tokens(pipeline_tokens, config)

        # ── Phase 6b: Hallucination filters ──────────────────────────────────
        pipeline_tokens = _filter_hallucinations(pipeline_tokens)
        if config.get("drop_tokens_over_silence", True):
            before = len(pipeline_tokens)
            pipeline_tokens = normalize.drop_tokens_over_silence(
                pipeline_tokens, silence_spans,
                overlap=float(config.get("silence_overlap", 0.8)),
            )
            if len(pipeline_tokens) != before:
                logger.info(
                    "Silence filter removed %d tokens over VAD silence",
                    before - len(pipeline_tokens),
                )

        # ── Phase 6c: Word-level expansion ───────────────────────────────────
        # Engine A signals word_level_timestamps when it returned per-word spans.
        if not engine_a_word_level:
            pipeline_tokens = _expand_to_words(pipeline_tokens)
            logger.info("After word expansion: %d words", len(pipeline_tokens))

        # ── Phase 7: Forced alignment ─────────────────────────────────────────
        # Skip if Engine A already provided per-word timestamps.
        if not engine_a_word_level:
            audio_arr, sr = ingest.load_audio(audio_path)
            words = [t.text for t in pipeline_tokens]
            forced = align_force.forced_align(
                audio_arr, sr, words,
                aligner=align_force.CTCForcedAligner(device=device),
            )
            for t, f in zip(pipeline_tokens, forced):
                t.start_ms = f.start_ms
                t.end_ms = f.end_ms
        else:
            logger.info("Skipping forced alignment — Whisper word timestamps used directly")

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
        store.bulk_create_tokens(conn, db_rows)
        store.update_job_status(conn, job_id, "done")
        logger.info("Job %d done: %d tokens written", job_id, len(pipeline_tokens))

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
