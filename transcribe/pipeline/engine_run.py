from __future__ import annotations

import dataclasses
from contextlib import contextmanager
import json
import logging

import torch

from transcribe.audio import decode_windows
from transcribe.contracts import EngineInput, RecognizedToken
from transcribe.db import store
from transcribe.engines.registry import get_engine
from transcribe.pipeline.plan import PHASE_ENGINE_A_DONE, PHASE_ENGINE_B_DONE, JobPlan

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class DecodeInputs:
    chunks: list
    full_audio: object | None
    bias_terms: list[str]
    bias_weights: dict
    speech_spans: tuple[tuple[int, int], ...] = ()


@dataclasses.dataclass(frozen=True)
class Hypotheses:
    tokens_a: list[RecognizedToken]
    timestamps_final_a: bool
    tokens_b: list[RecognizedToken]


def build_engine(name: str, device: str, config: dict):
    """Forward configured overrides; the registry validates before construction.

    Unsupported arguments fail explicitly instead of silently dropping settings.
    Errors inside the constructor propagate without a second attempt.
    """
    engines_cfg = (config.get("engines", {}) or {}).get(name, {})
    kw = {"device": device, **engines_cfg}
    if name == "faster_whisper":
        kw.setdefault("config", config)
    return get_engine(name, **kw)


@contextmanager
def _engine_residency(engine, stage: str):
    try:
        engine.load()
        yield engine
    finally:
        engine.unload()
        _log_vram("post-" + stage)


@contextmanager
def gap_redecoder(plan: JobPlan, device: str, config: dict, audio, sample_rate: int,
                  engine=None):
    """Engine A, resident for the duration, as `redecode(lo_ms, hi_ms) -> cue dicts`.

    Used by the coverage guard after the main decode, so it keeps the one-model-at-a-time
    rule. Each excerpt is decoded alone: no bias prompt, no earlier text as context.
    If `engine` is passed, the caller manages its residency lifecycle.
    """
    def redecoder(eng):
        def redecode(lo_ms: int, hi_ms: int) -> list[dict]:
            excerpt = audio[lo_ms * sample_rate // 1000:hi_ms * sample_rate // 1000].copy()
            if not len(excerpt):
                return []
            res = eng.transcribe(EngineInput(audio=excerpt, language_hint=plan.language))
            return [{"text": t.text, "start_ms": t.start_ms + lo_ms, "end_ms": t.end_ms + lo_ms,
                     "script": t.script, "confidence": t.confidence}
                    for t in res.tokens]
        return redecode

    if engine is not None:
        yield redecoder(engine)
    else:
        eng = build_engine(plan.engine_a_name, device, config)
        with _engine_residency(eng, "coverage-guard"):
            yield redecoder(eng)
        del eng
        _free_vram()


def run_engines(conn, job_id: int, plan: JobPlan, inputs: DecodeInputs,
                device: str, config: dict,
                keep_engine_a_resident: bool = False,
                engine_a=None) -> tuple[Hypotheses, object | None]:
    """Produce both hypotheses, reusing whatever a resumed job already cached."""
    caller_owns_a = engine_a is not None
    tokens_a, final_a, pseudo_b_tokens, pseudo_b_raw_words, resident_a = _run_engine_a(
        conn, job_id, plan, inputs, device, config,
        keep_resident=keep_engine_a_resident or caller_owns_a,
        engine=engine_a,
    )
    try:
        tokens_b = _run_engine_b(
            conn, job_id, plan, inputs, device, config,
            final_a, pseudo_b_tokens, pseudo_b_raw_words)
    except Exception:
        if resident_a is not None and not caller_owns_a:
            try:
                resident_a.unload()
            finally:
                del resident_a
                _free_vram()
        raise

    if resident_a is not None and not final_a and not caller_owns_a:
        try:
            resident_a.unload()
        finally:
            del resident_a
            _free_vram()
        resident_a = None

    return Hypotheses(tokens_a=tokens_a, timestamps_final_a=final_a, tokens_b=tokens_b), resident_a


def _run_engine_a(conn, job_id, plan, inputs, device, config,
                  keep_resident: bool = False, engine=None):
    caller_owns_engine = engine is not None
    if plan.skip_engine_a:
        cached_a = store.get_engine_result(conn, job_id, "a")
        logger.info("Job %d: reusing cached engine-a result (resume)", job_id)
        tokens_a = _tokens_from_json(cached_a.tokens_json)
        final_a = cached_a.timestamps_final
        pseudo_b_tokens = pseudo_b_raw_words = None
        if plan.self_ensemble_enabled and not plan.skip_engine_b:
            if caller_owns_engine:
                pseudo_b_tokens, pseudo_b_raw_words = _decode_self_ensemble_b(engine, plan, inputs)
            else:
                eng = build_engine(plan.engine_a_name, device, config)
                _log_vram("pre-engine-a-self-ensemble-resume")
                with _engine_residency(eng, "engine-a-self-ensemble-resume"):
                    pseudo_b_tokens, pseudo_b_raw_words = _decode_self_ensemble_b(eng, plan, inputs)
                del eng
        _free_vram()
        return tokens_a, final_a, pseudo_b_tokens, pseudo_b_raw_words, engine

    if not caller_owns_engine:
        engine = build_engine(plan.engine_a_name, device, config)
        _log_vram("pre-engine-a")
    if not keep_resident and not caller_owns_engine:
        with _engine_residency(engine, "engine-a"):
            _log_vram("engine-a-loaded")
            tokens_a, final_a, raw_words_a = _transcribe_with(
                engine, inputs.chunks, inputs.full_audio, inputs.bias_terms, inputs.bias_weights,
                plan.language, plan.engine_batch_size, chunk_overlap_ms=plan.chunk_overlap_ms,
                temperature=plan.temperature_a, beam_size=plan.beam_size_a,
                speech_spans=inputs.speech_spans,
            )
            pseudo_b_tokens = pseudo_b_raw_words = None
            if plan.self_ensemble_enabled:
                pseudo_b_tokens, pseudo_b_raw_words = _decode_self_ensemble_b(engine, plan, inputs)
                logger.info("Self-ensemble: decoded second hypothesis (temperature=%s, "
                            "beam_size=%s) from Engine A's residency, %d tokens",
                            plan.temperature_b, plan.beam_size_b, len(pseudo_b_tokens))
        store.save_engine_result(
            conn, job_id, "a", plan.engine_a_name,
            _tokens_to_json(tokens_a), final_a,
            json.dumps(raw_words_a) if raw_words_a is not None else None,
        )
        stats = getattr(engine, "last_segment_stats", None)
        if isinstance(stats, list) and stats:
            store.save_engine_segments(conn, job_id, "a", json.dumps(stats))
        store.update_job_phase(conn, job_id, PHASE_ENGINE_A_DONE)
        del engine
        _free_vram()
        return tokens_a, final_a, pseudo_b_tokens, pseudo_b_raw_words, None
    else:
        try:
            if not caller_owns_engine:
                engine.load()
                _log_vram("engine-a-loaded")
            tokens_a, final_a, raw_words_a = _transcribe_with(
                engine, inputs.chunks, inputs.full_audio, inputs.bias_terms, inputs.bias_weights,
                plan.language, plan.engine_batch_size, chunk_overlap_ms=plan.chunk_overlap_ms,
                temperature=plan.temperature_a, beam_size=plan.beam_size_a,
                speech_spans=inputs.speech_spans,
            )
            pseudo_b_tokens = pseudo_b_raw_words = None
            if plan.self_ensemble_enabled:
                pseudo_b_tokens, pseudo_b_raw_words = _decode_self_ensemble_b(engine, plan, inputs)
                logger.info("Self-ensemble: decoded second hypothesis (temperature=%s, "
                            "beam_size=%s) from Engine A's residency, %d tokens",
                            plan.temperature_b, plan.beam_size_b, len(pseudo_b_tokens))
            store.save_engine_result(
                conn, job_id, "a", plan.engine_a_name,
                _tokens_to_json(tokens_a), final_a,
                json.dumps(raw_words_a) if raw_words_a is not None else None,
            )
            stats = getattr(engine, "last_segment_stats", None)
            if isinstance(stats, list) and stats:
                store.save_engine_segments(conn, job_id, "a", json.dumps(stats))
            store.update_job_phase(conn, job_id, PHASE_ENGINE_A_DONE)
            return tokens_a, final_a, pseudo_b_tokens, pseudo_b_raw_words, engine
        except Exception:
            if not caller_owns_engine:
                try:
                    engine.unload()
                finally:
                    del engine
                    _free_vram()
            raise


def _run_engine_b(conn, job_id, plan, inputs, device, config,
                  final_a, pseudo_b_tokens, pseudo_b_raw_words):
    if plan.skip_engine_b:
        cached_b = store.get_engine_result(conn, job_id, "b")
        logger.info("Job %d: reusing cached engine-b result (resume)", job_id)
        tokens_b = _tokens_from_json(cached_b.tokens_json)
        _free_vram()
        return tokens_b

    if plan.self_ensemble_enabled:
        tokens_b = pseudo_b_tokens
        raw_words_b = pseudo_b_raw_words
        timestamps_final_b = final_a
    else:
        engine = build_engine(plan.engine_b_name, device, config)
        _log_vram("pre-engine-b")
        with _engine_residency(engine, "engine-b"):
            _log_vram("engine-b-loaded")
            tokens_b, timestamps_final_b, raw_words_b = _transcribe_with(
                engine, inputs.chunks, inputs.full_audio, inputs.bias_terms,
                inputs.bias_weights, None, plan.engine_batch_size,
                chunk_overlap_ms=plan.chunk_overlap_ms,
                speech_spans=inputs.speech_spans,
            )
        del engine

    store.save_engine_result(
        conn, job_id, "b", plan.engine_b_name,
        _tokens_to_json(tokens_b), timestamps_final_b,
        json.dumps(raw_words_b) if raw_words_b is not None else None,
    )
    store.update_job_phase(conn, job_id, PHASE_ENGINE_B_DONE)
    _free_vram()
    return tokens_b


def _decode_self_ensemble_b(engine, plan: JobPlan, inputs: DecodeInputs):
    res = engine.transcribe(
        EngineInput(audio=inputs.full_audio, bias_terms=inputs.bias_terms,
                    bias_weights=inputs.bias_weights, language_hint=plan.language,
                    speech_spans=inputs.speech_spans),
        temperature=plan.temperature_b,
        beam_size=plan.beam_size_b,
    )
    raw_words = res.raw.get("words") if isinstance(res.raw, dict) else None
    return res.tokens, raw_words


def _transcribe_with(engine, chunks, full_audio, bias_terms, bias_weights, language_hint,
                     batch_size, chunk_overlap_ms=750, temperature=None, beam_size=None,
                     speech_spans=()):
    if getattr(engine, "prefers_whole_file", False):
        inp = EngineInput(audio=full_audio, bias_terms=bias_terms,
                           bias_weights=bias_weights, language_hint=language_hint,
                           speech_spans=speech_spans)
        overrides = {}
        if temperature is not None:
            overrides["temperature"] = temperature
        if beam_size is not None:
            overrides["beam_size"] = beam_size
        res = engine.transcribe(inp, **overrides)
        raw_words = res.raw.get("words") if isinstance(res.raw, dict) else None
        return res.tokens, res.timestamps_final, raw_words

    inputs = [
        EngineInput(audio=c.audio, bias_terms=bias_terms,
                    bias_weights=bias_weights, language_hint=language_hint)
        for c in chunks
    ]
    results = engine.transcribe_batch(inputs, batch_size=batch_size)
    timestamps_final = any(r.timestamps_final for r in results)
    results_iter = iter(results)

    def decode_fn(_chunk_audio):
        return next(results_iter).tokens

    return decode_windows(chunks, decode_fn, seam_window_ms=chunk_overlap_ms), timestamps_final, None


def _tokens_to_json(tokens: list[RecognizedToken]) -> str:
    return json.dumps([dataclasses.asdict(t) for t in tokens])


def _tokens_from_json(blob: str) -> list[RecognizedToken]:
    return [RecognizedToken(**d) for d in json.loads(blob)]


def _log_vram(stage: str) -> None:
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        logger.info("[VRAM] %s: %.1f MB free / %.1f MB total", stage, free / 1e6, total / 1e6)


def _free_vram() -> None:
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
