"""Pure paired regression gate: pass, regression or unresolved."""
from __future__ import annotations

from typing import NamedTuple

from transcribe.db.store import EvalRunRow
from transcribe.eval.metrics import CI_METRICS, EvalMetrics

_GATE_LABELS = {
    "cer_thai": "CER_thai", "wer_latin": "WER_latin",
    "boundary_error_rate": "BER", "cue_boundary_error_rate": "cue_BER",
}


class GateVerdict(NamedTuple):
    passed: bool
    regressions: list[str]
    unresolved: list[str]
    unresolved_names: list[str]
    gate_unresolved: str | None
    status: str
    improvements: list[str]


def decide(
    metrics: EvalMetrics, baseline: EvalRunRow | None,
    paired_ci: dict[str, tuple[float, float]] | None,
    tol_frac: float, abs_floor: float, *, comparison_error: str | None = None,
) -> GateVerdict:
    """Compare paired delta intervals with the allowed regression margin.

    An interval entirely above the margin confirms regression; entirely below
    or touching it passes. An interval straddling it is unresolved even if its
    point estimate looks acceptable. Missing matching evidence is unresolved.
    A first/explicitly established baseline still enforces cue non-overlap.
    """
    regressions, unresolved, unresolved_names, improvements = [], [], [], []
    if baseline is not None:
        for name in CI_METRICS:
            label = _GATE_LABELS[name]
            if paired_ci is None:
                unresolved.append(f"{label}: {comparison_error or 'paired baseline evidence unavailable'}")
                unresolved_names.append(name)
                continue
            base = getattr(baseline, name)
            margin = max(base * (tol_frac - 1), abs_floor)
            lo, hi = paired_ci[name]
            detail = f"{label} delta 95% CI [{lo:.4f}, {hi:.4f}], allowed +{margin:.4f}"
            if lo > margin:
                regressions.append(detail)
            elif hi > margin:
                unresolved.append(detail + " - needs more data")
                unresolved_names.append(name)
            elif hi < 0:
                improvements.append(detail)
    status = ("regression" if regressions or metrics.overlapping_cues > 0
              else "unresolved" if unresolved else "pass")
    return GateVerdict(status == "pass", regressions, unresolved, unresolved_names,
                       ",".join(unresolved_names) or None, status, improvements)
