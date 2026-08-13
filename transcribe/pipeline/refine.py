"""Post-decode token refinement — the pure half of the pipeline.

Internal to `transcribe/pipeline/`. Not part of any public interface; deliberately
absent from `pipeline/__init__.py`'s exports.

Everything between "two hypotheses exist" and "tokens are ready to write":
align → reconcile → normalize → hallucination filters → silence drop →
conditional word expansion → conditional forced alignment → cue conform.

A function of its arguments, so normalization, filtering and conform behaviour
can be tested on synthetic tokens without a WAV file, a database or a GPU. Forced
alignment is the one step that needs audio and a device, so the aligner arrives
as a dependency rather than being constructed in here — matching the existing
`ForcedAligner` abstraction, which already has two adapters (`CTCForcedAligner`,
`LinearFallbackAligner`) and is therefore already a real seam.
"""

from __future__ import annotations

import logging
import re

from transcribe.contracts import PipelineToken, detect_script
from transcribe.pipeline import align_force, align_hyp, normalize, reconcile

logger = logging.getLogger(__name__)

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
    # ── Phase 4: Hypothesis alignment ────────────────────────────────────────
    slots = align_hyp.align(hypotheses.tokens_a, hypotheses.tokens_b)
    logger.info("Alignment: %d slots", len(slots))

    # ── Phase 5: Reconciliation ───────────────────────────────────────────────
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

    # ── Phase 6: Normalization ────────────────────────────────────────────────
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

    # ── Phase 6b: Hallucination filters ──────────────────────────────────────
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

    # ── Phase 6c: Word-level expansion ───────────────────────────────────────
    # Engine A signals timestamps_final when its cue timestamps are already
    # final (skip word expansion + forced alignment).
    if not timestamps_final:
        pipeline_tokens = _expand_to_words(pipeline_tokens)
        logger.info("After word expansion: %d words", len(pipeline_tokens))

    # ── Phase 7: Forced alignment ─────────────────────────────────────────────
    # Skip if Engine A already provided final timestamps.
    if not timestamps_final:
        # Reuse the already-decoded array — no third decode (3.2).
        words = [t.text for t in pipeline_tokens]
        forced = align_force.forced_align(audio, sample_rate, words, aligner=aligner)
        for t, f in zip(pipeline_tokens, forced):
            t.start_ms = f.start_ms
            t.end_ms = f.end_ms
    else:
        logger.info("Skipping forced alignment — Whisper word timestamps used directly")

    # ── Phase 7b: Cue-timing conform ─────────────────────────────────────────
    # Runs on EVERY path, including the timestamps_final one above that skips
    # Phase 7 — the aligner used to be the only place the no-overlap/monotonic
    # invariant was enforced, so on the active engine path it was enforced
    # nowhere and overlapping cues reached the exported SRT.
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
