"""The engine-run bracket — instantiate, load, decode, unload, persist, advance.

Internal to `transcribe/pipeline/`. Not part of any public interface; deliberately
absent from `pipeline/__init__.py`'s exports.

This is where the duplication died. The self-ensemble second-decode block existed
twice in `run_file`, near-verbatim: once on the fresh path and once on the resume
path, the second copy existing only because a crash landing in one narrow window
(cached hypothesis A, uncomputed hypothesis B) would otherwise emit
`result_b_tokens=None`. That is what an unseamed body does under pressure — a
second copy was cheaper to add than a seam. Both paths now route through
`_decode_self_ensemble_b`, so a fix to it cannot be applied to one copy and
missed on the other.

It is also where CLAUDE.md's VRAM discipline (load → run → unload → del →
empty_cache, never two models resident) is written once instead of by repetition.
"""

from __future__ import annotations

import dataclasses
import json
import logging

import torch

from transcribe.contracts import EngineInput, RecognizedToken
from transcribe.db import store
from transcribe.engines.registry import get_engine
from transcribe.pipeline import stitch
from transcribe.pipeline.plan import PHASE_ENGINE_A_DONE, PHASE_ENGINE_B_DONE, JobPlan

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class DecodeInputs:
    """Everything an engine needs to decode this job, independent of which engine."""

    chunks: list
    full_audio: object | None
    bias_terms: list[str]
    bias_weights: dict


@dataclasses.dataclass(frozen=True)
class Hypotheses:
    """The two token streams the reconciler will be given."""

    tokens_a: list[RecognizedToken]
    timestamps_final_a: bool
    tokens_b: list[RecognizedToken]


def build_engine(name: str, device: str, config: dict):
    """Construct an engine, probing what its constructor accepts.

    A **capability probe**, not a swallowed exception: per-engine overrides live
    under `config["engines"][<registry name>]` so a model/compute_type/beam swap
    is a YAML edit, never a code edit (2.3). Not every adapter accepts that kwarg
    set — passthrough and mock take `device` and nothing else — so we try the
    full set and fall back to device-only on the `TypeError` that says "this
    engine does not have those knobs". Any other failure propagates.
    """
    engines_cfg = (config.get("engines", {}) or {}).get(name, {})
    kw = {"device": device, **engines_cfg}
    if name == "faster_whisper":
        # HANDOFF_THAI_BREAK_ATOMS.md: the break-atom lexicon needs the full
        # pipeline config (thai_atoms + normalization.exception_lexicon), not just
        # this engine's own config["engines"]["faster_whisper"] sub-block —
        # threaded only to this engine so other engines' kwarg sets (and their own
        # TypeError fallback below) are untouched.
        kw.setdefault("config", config)
    try:
        return get_engine(name, **kw)
    except TypeError:
        return get_engine(name, device=device)


def run_engines(conn, job_id: int, plan: JobPlan, inputs: DecodeInputs,
                device: str, config: dict) -> Hypotheses:
    """Produce both hypotheses, reusing whatever a resumed job already cached."""
    tokens_a, final_a, pseudo_b_tokens, pseudo_b_raw_words = _run_engine_a(
        conn, job_id, plan, inputs, device, config)
    tokens_b = _run_engine_b(
        conn, job_id, plan, inputs, device, config,
        final_a, pseudo_b_tokens, pseudo_b_raw_words)
    return Hypotheses(tokens_a=tokens_a, timestamps_final_a=final_a, tokens_b=tokens_b)


def _run_engine_a(conn, job_id, plan, inputs, device, config):
    """Hypothesis A, plus the self-ensemble pseudo-B decoded inside A's own
    residency (never a second model load).

    Returns (tokens_a, timestamps_final_a, pseudo_b_tokens, pseudo_b_raw_words).
    """
    if plan.skip_engine_a:
        cached_a = store.get_engine_result(conn, job_id, "a")
        logger.info("Job %d: reusing cached engine-a result (resume)", job_id)
        tokens_a = _tokens_from_json(cached_a.tokens_json)
        final_a = cached_a.timestamps_final
        pseudo_b_tokens = pseudo_b_raw_words = None
        # Resumed exactly at engine_a_done: hypothesis A was cached but the
        # self-ensemble's own pseudo-B pass (never separately persisted until the
        # "b" phase below) was not — reload once to produce it. Rare (only a crash
        # landing in this exact window hits it), but a resumed self-ensemble job
        # must not silently emit result_b_tokens=None.
        if plan.self_ensemble_enabled and not plan.skip_engine_b:
            engine = build_engine(plan.engine_a_name, device, config)
            _log_vram("pre-engine-a-self-ensemble-resume")
            engine.load()
            pseudo_b_tokens, pseudo_b_raw_words = _decode_self_ensemble_b(engine, plan, inputs)
            engine.unload()
            _log_vram("post-engine-a-self-ensemble-resume")
            del engine
        _free_vram()
        return tokens_a, final_a, pseudo_b_tokens, pseudo_b_raw_words

    engine = build_engine(plan.engine_a_name, device, config)
    _log_vram("pre-engine-a")
    engine.load()
    _log_vram("engine-a-loaded")
    tokens_a, final_a, raw_words_a = _transcribe_with(
        engine, inputs.chunks, inputs.full_audio, inputs.bias_terms, inputs.bias_weights,
        "th", plan.engine_batch_size, chunk_overlap_ms=plan.chunk_overlap_ms,
        temperature=plan.temperature_a, beam_size=plan.beam_size_a,
    )
    pseudo_b_tokens = pseudo_b_raw_words = None
    if plan.self_ensemble_enabled:
        pseudo_b_tokens, pseudo_b_raw_words = _decode_self_ensemble_b(engine, plan, inputs)
        logger.info("Self-ensemble: decoded second hypothesis (temperature=%s, "
                    "beam_size=%s) from Engine A's residency, %d tokens",
                    plan.temperature_b, plan.beam_size_b, len(pseudo_b_tokens))
    engine.unload()
    _log_vram("post-engine-a")
    store.save_engine_result(
        conn, job_id, "a", plan.engine_a_name,
        _tokens_to_json(tokens_a), final_a,
        json.dumps(raw_words_a) if raw_words_a is not None else None,
    )
    store.update_job_phase(conn, job_id, PHASE_ENGINE_A_DONE)
    del engine
    _free_vram()
    return tokens_a, final_a, pseudo_b_tokens, pseudo_b_raw_words


def _run_engine_b(conn, job_id, plan, inputs, device, config,
                  final_a, pseudo_b_tokens, pseudo_b_raw_words):
    """Hypothesis B — cached, the self-ensemble pseudo-B, or a real second model."""
    if plan.skip_engine_b:
        cached_b = store.get_engine_result(conn, job_id, "b")
        logger.info("Job %d: reusing cached engine-b result (resume)", job_id)
        tokens_b = _tokens_from_json(cached_b.tokens_json)
        _free_vram()
        return tokens_b

    if plan.self_ensemble_enabled:
        # Already decoded inside Engine A's residency — no engine is constructed
        # or loaded here at all. The result is labelled with the canonical
        # "self_ensemble" name, which is record-keeping, never a registry lookup.
        tokens_b = pseudo_b_tokens
        raw_words_b = pseudo_b_raw_words
        timestamps_final_b = final_a
    else:
        engine = build_engine(plan.engine_b_name, device, config)
        _log_vram("pre-engine-b")
        engine.load()
        _log_vram("engine-b-loaded")
        tokens_b, timestamps_final_b, raw_words_b = _transcribe_with(
            engine, inputs.chunks, inputs.full_audio, inputs.bias_terms,
            inputs.bias_weights, None, plan.engine_batch_size,
            chunk_overlap_ms=plan.chunk_overlap_ms,
        )
        engine.unload()
        _log_vram("post-engine-b")
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
    """The self-ensemble second hypothesis, from an ALREADY-LOADED Engine A.

    The one copy of this. Both the fresh path and the resume-at-engine_a_done
    path call it, which is the point of this module.
    """
    res = engine.transcribe(
        EngineInput(audio=inputs.full_audio, bias_terms=inputs.bias_terms,
                    bias_weights=inputs.bias_weights, language_hint="th"),
        temperature=plan.temperature_b,
        beam_size=plan.beam_size_b,
    )
    raw_words = res.raw.get("words") if isinstance(res.raw, dict) else None
    return res.tokens, raw_words


def _transcribe_with(engine, chunks, full_audio, bias_terms, bias_weights, language_hint,
                     batch_size, chunk_overlap_ms=750, temperature=None, beam_size=None):
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

    temperature/beam_size (HANDOFF_ONE_ENGINE §6, Phase D): only passed to
    engine.transcribe() when explicitly given, so engines whose transcribe(inp)
    doesn't accept the kwargs (mock, passthrough, every non-faster_whisper
    adapter) are unaffected.
    """
    if getattr(engine, "prefers_whole_file", False):
        inp = EngineInput(audio=full_audio, bias_terms=bias_terms,
                           bias_weights=bias_weights, language_hint=language_hint)
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


def _tokens_to_json(tokens: list[RecognizedToken]) -> str:
    return json.dumps([dataclasses.asdict(t) for t in tokens])


def _tokens_from_json(blob: str) -> list[RecognizedToken]:
    return [RecognizedToken(**d) for d in json.loads(blob)]


def _log_vram(stage: str) -> None:
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        logger.info("[VRAM] %s: %.1f MB free / %.1f MB total", stage, free / 1e6, total / 1e6)


def _free_vram() -> None:
    """Close each engine's bracket. CLAUDE.md's ceiling is 8GB and engines run
    sequentially precisely so two are never resident at once."""
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
