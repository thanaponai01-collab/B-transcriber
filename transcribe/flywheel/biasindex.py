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

_MIN_OCCURRENCES = 3     # a term must be corrected this many times to enter the index
_STALE_WEIGHT = 0.2      # weight applied to corrections from inactive engines


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
    Returns:
        list of bias term strings
    """
    counts = store.get_correction_counts(conn)

    # Weight correction counts by staleness; aggregation done in SQLite
    weighted: Counter[str] = Counter()
    for corrected_text, source_engine, n in counts:
        weight = 1.0 if source_engine in active_engines else _STALE_WEIGHT
        weighted[corrected_text] += weight * n

    # Promote terms that cross the threshold
    promoted = []
    for term, w in weighted.items():
        if w >= _MIN_OCCURRENCES:
            term_type, script = _classify_term(term)
            store.upsert_bias_term(conn, term, term_type, script, "flywheel", min(w, 5.0))
            promoted.append(term)
            logger.info("Bias term promoted: %r (weight %.1f)", term, w)

    if promoted and run_regression_gate and eval_config is not None and db_path is not None:
        _run_regression_gate(eval_config, db_path, promoted)

    return store.get_bias_term_strings(conn)


def _run_regression_gate(config: dict, db_path: Path, new_terms: list[str]) -> None:
    """Run eval harness; roll back new bias terms if WER/BER regresses."""
    from transcribe.eval.harness import run_harness

    logger.info("Regression gate: running eval harness after bias update")
    metrics = run_harness(config, db_path)

    conn = store.connect(db_path)
    last = store.get_last_passing_eval(conn)
    conn.close()

    tol_frac = 1.0 + float(config.get("regression_tolerance", 0.02))
    abs_floor = float(config.get("regression_abs_floor", 0.005))
    if last is not None and not _passed_gate(metrics, last, tol_frac, abs_floor):
        logger.warning(
            "Regression gate BLOCKED: rolling back %d bias terms", len(new_terms)
        )
        conn = store.connect(db_path)
        for term in new_terms:
            store.delete_bias_term(conn, term)
        conn.close()
        raise RuntimeError(
            f"Bias update rejected by regression gate: "
            f"WER {metrics.wer:.4f} > allowed threshold"
        )


def _passed_gate(current, last, tol_frac: float = 1.02, abs_floor: float = 0.005) -> bool:
    from transcribe.eval.metrics import regressed
    return not (
        regressed(current.wer, last.wer, tol_frac, abs_floor)
        or regressed(current.boundary_error_rate, last.boundary_error_rate, tol_frac, abs_floor)
    )
