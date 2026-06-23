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


import re

# A unit of 1+ chars repeated 3+ times in a row = a Whisper loop, not real text
# (e.g. "อื้อฮือฮือฮือ…"). Collapse to a single copy. ponytail: 3+ identical
# repeats of a substring is essentially never legitimate Thai/Latin; mai-yamok (ๆ)
# carries genuine repetition.
_LOOP_RE = re.compile(r"(.+?)\1{2,}")


def _collapse_loops(text: str) -> str:
    return _LOOP_RE.sub(r"\1", text)


def _filter_hallucinations(tokens: list[PipelineToken], max_run: int = 3) -> list[PipelineToken]:
    """Strip Whisper repetition loops — both inside a single token and across tokens.

    Whisper hallucinates on silence/music by looping filler words. Two shapes:
    one token whose own text is a looped unit, and the same word as N consecutive
    tokens. Handle both.
    """
    if not tokens:
        return tokens
    for tok in tokens:
        tok.text = _collapse_loops(tok.text)

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


def _transcribe_with(engine, chunks, full_audio, bias_terms, language_hint, batch_size):
    """Run one engine over the audio → (global-timestamped tokens, word_level).

    Whole-file engines get the full track in a single call (their own VAD and
    segmentation is the point) and already return absolute timestamps. Chunk
    engines get the VAD chunks; we offset each chunk's tokens to global time and
    stitch overlaps.
    """
    if getattr(engine, "prefers_whole_file", False):
        res = engine.transcribe(
            EngineInput(audio=full_audio, bias_terms=bias_terms, language_hint=language_hint)
        )
        return res.tokens, res.word_level_timestamps

    inputs = [
        EngineInput(audio=c.audio, bias_terms=bias_terms, language_hint=language_hint)
        for c in chunks
    ]
    results = engine.transcribe_batch(inputs, batch_size=batch_size)
    word_level = False
    chunk_tokens: list[stitch.ChunkTokens] = []
    for c, r in zip(chunks, results):
        word_level = word_level or r.word_level_timestamps
        for tok in r.tokens:  # offset to global position
            tok.start_ms += c.start_ms
            tok.end_ms += c.start_ms
        chunk_tokens.append(stitch.ChunkTokens(r.tokens, c.start_ms, c.end_ms))
    # GAP-4: stitch drops duplicate words from any chunk-overlap windows.
    return stitch.stitch(chunk_tokens), word_level


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
        ingest_result = ingest.ingest(
            audio_path,
            denoise=config.get("denoise", True),
            vad_threshold=float(config.get("vad_threshold", 0.5)),
            vad_min_speech_ms=int(config.get("vad_min_speech_ms", 250)),
            vad_min_silence_ms=int(config.get("vad_min_silence_ms", 300)),
        )
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
        engine_batch_size = int(config.get("engine_batch_size", 8))

        # Instantiate (no weights loaded yet) to learn capabilities; load the full
        # track once if any engine wants whole-file input.
        # Optional per-engine overrides from config. Only forwarded to engines
        # whose constructor accepts them, so passthrough/mock stay untouched.
        def _engine_kwargs(model_key: str) -> dict:
            kw = {"device": device}
            model_id = config.get(model_key)
            if model_id:
                kw["model_id"] = model_id
            ct = config.get("compute_type")
            if ct:
                kw["compute_type"] = ct
            return kw

        def _safe_get_engine(name: str, model_key: str):
            try:
                return get_engine(name, **_engine_kwargs(model_key))
            except TypeError:
                # Engine doesn't accept model_id/compute_type (e.g. passthrough, mock)
                return get_engine(name, device=device)

        engine_a = _safe_get_engine(engine_a_name, "engine_a_model")
        engine_b = _safe_get_engine(engine_b_name, "engine_b_model")
        full_audio = None
        if engine_a.prefers_whole_file or engine_b.prefers_whole_file:
            full_audio, _ = ingest.load_audio(audio_path)

        _log_vram("pre-engine-a")
        engine_a.load()
        _log_vram("engine-a-loaded")
        result_a_tokens, engine_a_word_level = _transcribe_with(
            engine_a, chunks, full_audio, bias_terms, "th", engine_batch_size,
        )
        engine_a.unload()
        del engine_a
        torch.cuda.empty_cache() if torch.cuda.is_available() else None
        _log_vram("post-engine-a")

        _log_vram("pre-engine-b")
        engine_b.load()
        _log_vram("engine-b-loaded")
        result_b_tokens, _ = _transcribe_with(
            engine_b, chunks, full_audio, bias_terms, None, engine_batch_size,
        )
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
