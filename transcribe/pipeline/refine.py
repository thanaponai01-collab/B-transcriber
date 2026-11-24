from __future__ import annotations

import logging
import re

from transcribe.contracts import PipelineToken, detect_script
from transcribe.pipeline import align_force, align_hyp, normalize, reconcile

logger = logging.getLogger(__name__)

_LOOP_RE_LONG = re.compile(r"(.{3,}?)\1{2,}")
_LOOP_RE_SHORT = re.compile(r"(.{1,2})\1{4,}")
_DIGITS_ONLY_RE = re.compile(r"^[\d\W_]+$")


def refine(hypotheses, *, config: dict, bias_terms, silence_spans, audio,
           sample_rate, aligner, on_reconciled=None) -> list[PipelineToken]:
    """Turn two hypothesis token streams into the final PipelineToken list.

    `aligner` is used only when the engine did NOT report final timestamps; on
    the active whole-file path it is never touched — which is why it may be a
    cheap-to-construct object rather than a loaded model.

    `on_reconciled` is the one concession to the caller's bookkeeping: `run_file`
    advances `job_phase` to 'reconciled' at exactly this point, and the ordering
    of phase advances relative to persistence is part of resume semantics. A
    caller with nothing to record passes nothing and this stays pure.
    """
    slots = align_hyp.align(hypotheses.tokens_a, hypotheses.tokens_b)
    logger.info("Alignment: %d slots", len(slots))

    reconciler_cfg = config.get("reconciler", {}) or {}
    llm_fn = None
    if reconciler_cfg.get("llm_enabled", False):
        from transcribe.pipeline.llm_reconcile import make_llm_fn
        llm_fn = make_llm_fn(reconciler_cfg.get("ollama", {}))
    reconciled = reconcile.reconcile(slots, bias_terms=bias_terms, llm_fn=llm_fn)
    logger.info("Reconciled: %d tokens", len(reconciled))
    if on_reconciled is not None:
        on_reconciled()

    timestamps_final = hypotheses.timestamps_final_a

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

    pipeline_tokens = _filter_hallucinations(pipeline_tokens)
    if config.get("drop_tokens_over_silence", True):
        before = len(pipeline_tokens)
        max_conf_cfg = config.get("silence_drop_max_confidence", 0.5)
        pipeline_tokens = normalize.drop_tokens_over_silence(
            pipeline_tokens, silence_spans,
            overlap=float(config.get("silence_overlap", 0.8)),
            max_confidence=(float(max_conf_cfg) if max_conf_cfg is not None else None),
        )
        if len(pipeline_tokens) != before:
            logger.info(
                "Silence filter removed %d tokens over VAD silence",
                before - len(pipeline_tokens),
            )

    if not timestamps_final:
        pipeline_tokens = _expand_to_words(pipeline_tokens)
        logger.info("After word expansion: %d words", len(pipeline_tokens))

    if not timestamps_final:
        words = [t.text for t in pipeline_tokens]
        forced = align_force.forced_align(audio, sample_rate, words, aligner=aligner)
        for t, f in zip(pipeline_tokens, forced):
            t.start_ms = f.start_ms
            t.end_ms = f.end_ms
    else:
        logger.info("Skipping forced alignment — Whisper word timestamps used directly")

    conform_report = align_force.conform_cues(
        pipeline_tokens,
        max_close_gap_ms=int(config.get("cue_max_close_gap_ms", align_force._GAP_CLOSE_MS)),
        duration_ms=int(len(audio) * 1000 / sample_rate),
    )
    if any(conform_report.values()):
        logger.info(
            "Cue conform: %d overlap(s) fixed, %d gap(s) closed, %d bound clamp(s)",
            conform_report["overlaps_fixed"], conform_report["gaps_closed"],
            conform_report["bounds_clamped"],
        )
    return pipeline_tokens


def _collapse_loops(text: str) -> str:
    if _DIGITS_ONLY_RE.match(text):
        return text
    collapsed = _LOOP_RE_LONG.sub(r"\1", _LOOP_RE_SHORT.sub(r"\1", text))
    if collapsed != text:
        logger.info("Loop-collapse: %r → %r", text, collapsed)
    return collapsed


def _filter_hallucinations(tokens: list[PipelineToken], max_run: int = 3) -> list[PipelineToken]:
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
    result = []
    idx = 0
    for tok in tokens:
        if tok.script in ("thai", "mixed"):
            try:
                from pythainlp.tokenize import word_tokenize
                words = [w for w in word_tokenize(tok.text, engine="newmm") if w.strip()]
            except Exception:
                words = list(tok.text)
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
