"""Flywheel Phase 9b — build bias terms from recurring corrections.

Staleness rule: down-weight corrections from engines no longer in the active config.
Regression gate: auto-run eval harness; reject changes that worsen WER/BER.
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

from transcribe.db import store

logger = logging.getLogger(__name__)

# Defaults only — the live values come from config.flywheel (config.yaml) and are
# threaded through update_bias_index(). Kept here purely as fallbacks.
_MIN_OCCURRENCES = 3     # a term must be corrected this many times to enter the index
_STALE_WEIGHT = 0.2      # weight applied to corrections from inactive engines


def _too_long_to_promote(term: str, max_chars: int = 30, max_words: int = 6) -> bool:
    """A bias term must be a word or short phrase, never a sentence (5.3)."""
    return len(term) > max_chars or len(term.split()) > max_words


def _classify_term(term: str) -> tuple[str, str | None]:
    """
    Heuristic classification of a corrected term.
    Returns (term_type, script).
    """
    thai = sum(1 for c in term if "฀" <= c <= "๿")
    latin = sum(1 for c in term if c.isascii() and c.isalpha())

    if latin and not thai:
        script = "latin"
        # Capitalized Latin → likely proper noun / brand
        if term[0].isupper():
            return "brand", script
        return "technical", script
    if thai and not latin:
        return "loanword", "thai"
    return "technical", "mixed"


def update_bias_index(
    conn,
    active_engines: list[str],
    eval_config: dict | None = None,
    db_path: Path | None = None,
    run_regression_gate: bool = True,
    min_occurrences: float | None = None,
    stale_engine_weight: float | None = None,
) -> list[str]:
    """
    Scan corrections, promote recurring ones to bias_term rows.
    Returns the list of bias term strings after update.

    Args:
        conn: DB connection
        active_engines: engine names currently in config (e.g. ["whisper_thai", "funasr"])
        eval_config: config dict for running the regression gate
        db_path: path to DB (needed for regression gate)
        run_regression_gate: if True, run eval harness after update
        min_occurrences: promotion threshold; falls back to config.flywheel then _MIN_OCCURRENCES
        stale_engine_weight: weight for inactive-engine corrections; same fallback chain
    Returns:
        list of bias term strings
    """
    fw = (eval_config or {}).get("flywheel", {})
    if min_occurrences is None:
        min_occurrences = float(fw.get("min_occurrences", _MIN_OCCURRENCES))
    if stale_engine_weight is None:
        stale_engine_weight = float(fw.get("stale_engine_weight", _STALE_WEIGHT))

    counts = store.get_correction_counts(conn)

    # Weight correction counts by staleness; aggregation done in SQLite
    weighted: Counter[str] = Counter()
    for corrected_text, source_engine, n in counts:
        weight = 1.0 if source_engine in active_engines else stale_engine_weight
        weighted[corrected_text] += weight * n

    # Promote terms that cross the threshold. Guard against sentence-length "terms"
    # (5.3): even with sub-cue span extraction, never promote something that would
    # eat the prompt budget or bias toward phrase repetition.
    promoted = []
    for term, w in weighted.items():
        if w >= min_occurrences and not _too_long_to_promote(term):
            term_type, script = _classify_term(term)
            store.upsert_bias_term(conn, term, term_type, script, "flywheel", min(w, 5.0))
            promoted.append(term)
            logger.info("Bias term promoted: %r (weight %.1f)", term, w)

    if promoted and run_regression_gate and eval_config is not None and db_path is not None:
        _run_regression_gate(eval_config, db_path, promoted)

    return store.get_bias_term_strings(conn)


def _run_regression_gate(config: dict, db_path: Path, new_terms: list[str]) -> None:
    """Run eval harness; roll back new bias terms if the harness gate fails.

    The harness is the single gate authority (5.2): it captures the prior passing
    baseline before writing the new run and gates on cer_thai + wer_latin + BER.
    We consume its verdict directly — re-reading get_last_passing_eval here would
    fetch the run the harness just wrote and compare it against itself.
    """
    from transcribe.eval.harness import run_harness

    def _rollback(reason: str) -> None:
        logger.warning("Regression gate BLOCKED (%s): rolling back %d bias terms",
                       reason, len(new_terms))
        conn = store.connect(db_path)
        for term in new_terms:
            store.delete_bias_term(conn, term)
        conn.close()
        raise RuntimeError(f"Bias update rejected by regression gate: {reason}")

    logger.info("Regression gate: running eval harness after bias update")
    result = run_harness(config, db_path)
    if result is None:
        # Empty gold set — nothing to validate against. Roll back rather than
        # promote unvalidated terms.
        _rollback("no gold set to validate against")
    if not result.passed:
        _rollback(f"metrics regressed vs baseline (CER {result.metrics.cer_thai:.4f})")
