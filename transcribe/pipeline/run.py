"""Pipeline orchestrator — runs the full batch pipeline for one audio file."""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path

import torch

from transcribe.contracts import EngineInput, PipelineToken, RecognizedToken, detect_script
from transcribe.db import store
from transcribe.engines.registry import get_engine
from transcribe.pipeline import align_force, align_hyp, ingest, normalize, reconcile, stitch

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "1.0.0"

# job_phase values (4.1, GAP-8): a resumed 'failed' job skips every phase up to
# and including its last recorded one, reusing cached engine_result rows instead
# of re-running GPU inference.
_PHASE_ENGINE_A_DONE = "engine_a_done"
_PHASE_ENGINE_B_DONE = "engine_b_done"
_PHASE_RECONCILED = "reconciled"
_PHASE_WRITTEN = "written"


def _tokens_to_json(tokens: list[RecognizedToken]) -> str:
    return json.dumps([dataclasses.asdict(t) for t in tokens])


def _tokens_from_json(blob: str) -> list[RecognizedToken]:
    return [RecognizedToken(**d) for d in json.loads(blob)]


def _log_vram(stage: str) -> None:
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        logger.info("[VRAM] %s: %.1f MB free / %.1f MB total", stage, free / 1e6, total / 1e6)


import re

# Whisper loops are long units repeated many times (e.g. "อื้อฮือฮือฮือ…"). The
# old blanket `(.+?)\1{2,}` corrupted real text: "2000"→"20", "555" (Thai
# laughter)→"5", phone numbers, "www". faster-whisper already kills loops at the
# source (condition_on_previous_text=False, vad_filter, compression/log-prob
# thresholds), so this pass only needs to catch the rare residual — and must not
# touch legitimate text.
#   • ≥3-char units: 3+ repeats is a real loop (Whisper loops are long units).
#   • ≤2-char units: need 5+ repeats before it's suspect ("www" survives).
#   • digits-only / digits+punct tokens are never touched.
_LOOP_RE_LONG = re.compile(r"(.{3,}?)\1{2,}")
_LOOP_RE_SHORT = re.compile(r"(.{1,2})\1{4,}")
_DIGITS_ONLY_RE = re.compile(r"^[\d\W_]+$")  # digits + punctuation, no letters (\w)


def _collapse_loops(text: str) -> str:
    if _DIGITS_ONLY_RE.match(text):
        return text  # 2000, 555, 0812345555 — never a loop
    # Short units first: otherwise the ≥3-char pattern greedily eats a 2-char
    # loop as a 4-char super-unit and only half-collapses it.
    collapsed = _LOOP_RE_LONG.sub(r"\1", _LOOP_RE_SHORT.sub(r"\1", text))
    if collapsed != text:
        logger.info("Loop-collapse: %r → %r", text, collapsed)
    return collapsed


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


def _transcribe_with(engine, chunks, full_audio, bias_terms, bias_weights, language_hint,
                     batch_size, chunk_overlap_ms=750):
    """Run one engine over the audio → (global-timestamped tokens, word_level, raw_words).

    Whole-file engines get the full track in a single call (their own VAD and
    segmentation is the point) and already return absolute timestamps. Chunk
    engines get the VAD chunks; we offset each chunk's tokens to global time and
    stitch overlaps.

    raw_words (4.2): the engine's own per-word timestamp list, when it provides
    one (`EngineResult.raw["words"]` — faster-whisper does; re-derived on demand
    downstream, e.g. CutDeck Phase 5 filler excision, instead of discarded here.
    Only captured for whole-file engines — chunk-engine raw words would need
    per-chunk offsetting/restitching that isn't wired up yet.
    """
    if getattr(engine, "prefers_whole_file", False):
        res = engine.transcribe(
            EngineInput(audio=full_audio, bias_terms=bias_terms,
                        bias_weights=bias_weights, language_hint=language_hint)
        )
        raw_words = res.raw.get("words") if isinstance(res.raw, dict) else None
        return res.tokens, res.timestamps_final, raw_words

    inputs = [
        EngineInput(audio=c.audio, bias_terms=bias_terms,
                    bias_weights=bias_weights, language_hint=language_hint)
        for c in chunks
    ]
    results = engine.transcribe_batch(inputs, batch_size=batch_size)
    timestamps_final = False
    chunk_tokens: list[stitch.ChunkTokens] = []
    for c, r in zip(chunks, results):
        timestamps_final = timestamps_final or r.timestamps_final
        for tok in r.tokens:  # offset to global position
            tok.start_ms += c.start_ms
            tok.end_ms += c.start_ms
        chunk_tokens.append(stitch.ChunkTokens(r.tokens, c.start_ms, c.end_ms))
    # GAP-4: stitch drops duplicate words from any chunk-overlap windows. The
    # seam search window matches the overlap ingest actually materialized.
    return stitch.stitch(chunk_tokens, seam_window_ms=chunk_overlap_ms), timestamps_final, None


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

    engine_a_name = config["engine_a"]
    engine_b_name = config["engine_b"]

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

    skip_engine_a = resume_phase in (_PHASE_ENGINE_A_DONE, _PHASE_ENGINE_B_DONE,
                                      _PHASE_RECONCILED, _PHASE_WRITTEN)
    skip_engine_b = resume_phase in (_PHASE_ENGINE_B_DONE, _PHASE_RECONCILED, _PHASE_WRITTEN)

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
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Using device: %s", device)
        engine_batch_size = int(config.get("engine_batch_size", 8))

        # Instantiate engines first (no weights loaded yet) to learn capabilities —
        # whether a chunk engine is active decides whether ingest denoises and cuts
        # chunks at all (3.2). Per-engine overrides live under config["engines"]
        # [<registry name>] so a model/compute_type/beam swap is a YAML edit, never
        # a code edit (2.3). Forwarded only to engines whose constructor accepts
        # them, so passthrough/mock stay untouched.
        engines_cfg = config.get("engines", {}) or {}

        def _safe_get_engine(name: str):
            kw = {"device": device, **engines_cfg.get(name, {})}
            try:
                return get_engine(name, **kw)
            except TypeError:
                # Engine doesn't accept these kwargs (e.g. passthrough, mock)
                return get_engine(name, device=device)

        engine_a = _safe_get_engine(engine_a_name)
        engine_b = _safe_get_engine(engine_b_name)

        def _is_chunk_engine(name: str, eng) -> bool:
            # passthrough consumes nothing; whole-file engines want the raw track.
            return name != "passthrough" and not getattr(eng, "prefers_whole_file", False)
        chunk_engine_active = (_is_chunk_engine(engine_a_name, engine_a)
                               or _is_chunk_engine(engine_b_name, engine_b))

        # ── Phase 2: Ingestion — decode ONCE, share the array with the engines ─
        audio_arr, sr = ingest.load_audio(audio_path)
        ingest_result = ingest.ingest(
            audio_path,
            # Denoise only helps chunk engines. Whole-file engines load the raw
            # track, so denoising here burns ~1.8k file writes/hr and desyncs the
            # silence timeline from the audio the engine actually hears (3.2).
            denoise=config.get("denoise", True) and chunk_engine_active,
            vad_threshold=float(config.get("vad_threshold", 0.5)),
            vad_min_speech_ms=int(config.get("vad_min_speech_ms", 250)),
            vad_min_silence_ms=int(config.get("vad_min_silence_ms", 300)),
            audio=audio_arr, sr=sr,
            materialize_chunks=chunk_engine_active,
            chunk_overlap_ms=int(config.get("chunk_overlap_ms", 750)) if chunk_engine_active else 0,
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
        full_audio = engine_audio if (engine_a.prefers_whole_file or engine_b.prefers_whole_file) else None

        if skip_engine_a:
            cached_a = store.get_engine_result(conn, job_id, "a")
            logger.info("Job %d: reusing cached engine-a result (resume)", job_id)
            result_a_tokens = _tokens_from_json(cached_a.tokens_json)
            engine_a_timestamps_final = cached_a.timestamps_final
        else:
            _log_vram("pre-engine-a")
            engine_a.load()
            _log_vram("engine-a-loaded")
            result_a_tokens, engine_a_timestamps_final, raw_words_a = _transcribe_with(
                engine_a, chunks, full_audio, bias_terms, bias_weights, "th", engine_batch_size,
                chunk_overlap_ms=int(config.get("chunk_overlap_ms", 750)),
            )
            engine_a.unload()
            _log_vram("post-engine-a")
            store.save_engine_result(
                conn, job_id, "a", engine_a_name,
                _tokens_to_json(result_a_tokens), engine_a_timestamps_final,
                json.dumps(raw_words_a) if raw_words_a is not None else None,
            )
            store.update_job_phase(conn, job_id, _PHASE_ENGINE_A_DONE)
        del engine_a
        torch.cuda.empty_cache() if torch.cuda.is_available() else None

        if skip_engine_b:
            cached_b = store.get_engine_result(conn, job_id, "b")
            logger.info("Job %d: reusing cached engine-b result (resume)", job_id)
            result_b_tokens = _tokens_from_json(cached_b.tokens_json)
        else:
            _log_vram("pre-engine-b")
            engine_b.load()
            _log_vram("engine-b-loaded")
            result_b_tokens, timestamps_final_b, raw_words_b = _transcribe_with(
                engine_b, chunks, full_audio, bias_terms, bias_weights, None, engine_batch_size,
                chunk_overlap_ms=int(config.get("chunk_overlap_ms", 750)),
            )
            engine_b.unload()
            _log_vram("post-engine-b")
            store.save_engine_result(
                conn, job_id, "b", engine_b_name,
                _tokens_to_json(result_b_tokens), timestamps_final_b,
                json.dumps(raw_words_b) if raw_words_b is not None else None,
            )
            store.update_job_phase(conn, job_id, _PHASE_ENGINE_B_DONE)
        del engine_b
        torch.cuda.empty_cache() if torch.cuda.is_available() else None

        # ── Phase 4: Hypothesis alignment ────────────────────────────────────
        slots = align_hyp.align(result_a_tokens, result_b_tokens)
        logger.info("Alignment: %d slots", len(slots))

        # ── Phase 5: Reconciliation ───────────────────────────────────────────
        reconciler_cfg = config.get("reconciler", {}) or {}
        llm_fn = None
        if reconciler_cfg.get("llm_enabled", False):
            from transcribe.pipeline.llm_reconcile import make_llm_fn
            llm_fn = make_llm_fn(reconciler_cfg.get("ollama", {}))
        reconciled = reconcile.reconcile(slots, bias_terms=bias_terms, llm_fn=llm_fn)
        logger.info("Reconciled: %d tokens", len(reconciled))
        store.update_job_phase(conn, job_id, _PHASE_RECONCILED)

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
        # Engine A signals timestamps_final when its cue timestamps are already
        # final (skip word expansion + forced alignment).
        if not engine_a_timestamps_final:
            pipeline_tokens = _expand_to_words(pipeline_tokens)
            logger.info("After word expansion: %d words", len(pipeline_tokens))

        # ── Phase 7: Forced alignment ─────────────────────────────────────────
        # Skip if Engine A already provided final timestamps.
        if not engine_a_timestamps_final:
            # Reuse the already-decoded array — no third decode (3.2).
            words = [t.text for t in pipeline_tokens]
            forced = align_force.forced_align(
                engine_audio, ingest_result.sample_rate, words,
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
