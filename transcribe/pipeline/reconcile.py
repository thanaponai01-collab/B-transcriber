"""Phase 5 — Reconciler.

SELECTS between candidate tokens. NEVER generates text that no engine proposed.
The no-generation constraint is enforced by an explicit raise in _pick() — not
an assert, which vanishes under `python -O`.
"""

from __future__ import annotations

import logging

from transcribe.contracts import RecognizedToken
from transcribe.pipeline.align_hyp import AlignSlot

logger = logging.getLogger(__name__)


class ReconcilerViolation(RuntimeError):
    """The reconciler emitted text no engine proposed — a select-only breach."""


def _candidates_text(slot: AlignSlot) -> set[str]:
    return {t.text for t in slot.candidates_a + slot.candidates_b}


def _pick(
    slot: AlignSlot,
    bias_terms: list[str],
    llm_fn=None,
) -> tuple[RecognizedToken, str]:
    """
    Choose one token from the slot. Returns (token, source_engine).
    source_engine: 'a' | 'b' | 'both'

    The raise at the end guarantees no-generation.
    """
    a_tokens = slot.candidates_a
    b_tokens = slot.candidates_b

    # Only A has a candidate
    if a_tokens and not b_tokens:
        chosen = a_tokens[0]
        source = "a"

    # Only B has a candidate
    elif b_tokens and not a_tokens:
        chosen = b_tokens[0]
        source = "b"

    else:
        ta, tb = a_tokens[0], b_tokens[0]
        # Agreement: both tokens have the same text
        if ta.text == tb.text:
            # Merge: prefer whichever has a confidence; average if both do
            if ta.confidence is not None and tb.confidence is not None:
                conf = (ta.confidence + tb.confidence) / 2
            else:
                conf = ta.confidence or tb.confidence
            chosen = RecognizedToken(
                text=ta.text,
                start_ms=min(ta.start_ms, tb.start_ms),
                end_ms=max(ta.end_ms, tb.end_ms),
                confidence=conf,
                script=ta.script,
            )
            source = "both"
        else:
            # Disagreement — try LLM
            if llm_fn is not None:
                try:
                    idx = llm_fn(ta, tb, bias_terms)
                    if idx == 0:
                        chosen, source = ta, "a"
                    else:
                        chosen, source = tb, "b"
                except Exception as e:
                    logger.warning("LLM reconciler failed (%s), using script fallback", e)
                    chosen, source = _script_fallback(ta, tb)
            else:
                chosen, source = _script_fallback(ta, tb)

    # ── No-generation guard (raise, not assert: survives python -O) ───────────
    allowed = _candidates_text(slot)
    if chosen.text not in allowed:
        raise ReconcilerViolation(
            f"Reconciler produced text {chosen.text!r} not in candidate set {allowed!r}. "
            "This violates the select-only rule."
        )

    return chosen, source


def _script_fallback(
    ta: RecognizedToken, tb: RecognizedToken
) -> tuple[RecognizedToken, str]:
    """Thai-script → Engine A; Latin-script → Engine B."""
    script = ta.script  # use A's script as the tiebreaker
    if script == "thai":
        return ta, "a"
    if script == "latin":
        return tb, "b"
    # Mixed or other: prefer whichever has higher confidence
    ca = ta.confidence or 0.0
    cb = tb.confidence or 0.0
    if ca >= cb:
        return ta, "a"
    return tb, "b"


def reconcile(
    slots: list[AlignSlot],
    bias_terms: list[str] | None = None,
    llm_fn=None,
) -> list[tuple[RecognizedToken, str]]:
    """
    Reconcile all slots.

    Args:
        slots: output of align_hyp.align()
        bias_terms: list of known terms to pass to the LLM
        llm_fn: callable(ta, tb, bias_terms) -> int (0=pick A, 1=pick B)
                Called only on disagreement. Must return an index — never text.
    Returns:
        list of (RecognizedToken, source_engine) in slot order
    """
    bias_terms = bias_terms or []
    results = []
    llm_calls = 0

    for slot in slots:
        if not slot.candidates_a and not slot.candidates_b:
            continue
        token, source = _pick(slot, bias_terms, llm_fn)
        results.append((token, source))
        if source in ("a", "b") and slot.candidates_a and slot.candidates_b:
            llm_calls += 1

    logger.debug(
        "Reconciled %d slots; %d disagreements routed to fallback/LLM", len(slots), llm_calls
    )
    return results
