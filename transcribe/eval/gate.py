"""The regression-gate verdict — pure decision, no I/O.

`run_harness` writes a scratch database, mirrors the bias index, reads the
golden set off disk, times a pipeline per clip, runs the cue-legality lint,
prints a report and persists a 27-column row. Buried inside all of that is a
pure decision: given the aggregate metrics for a run, the baseline it is
gated against, each gated metric's bootstrap CI, and two tolerances, the
verdict follows. `decide()` is that decision, reachable without any of the
I/O around it.
"""

from __future__ import annotations

from typing import NamedTuple, Optional

from transcribe.db.store import EvalRunRow
from transcribe.eval.metrics import CI_METRICS, EvalMetrics, regressed

# Printed/stored label for each gated metric (matches the pre-Phase-A print format).
_GATE_LABELS = {
    "cer_thai": "CER_thai",
    "wer_latin": "WER_latin",
    "boundary_error_rate": "BER",
    "cue_boundary_error_rate": "cue_BER",
}


class GateVerdict(NamedTuple):
    """The regression gate's decision for one run.

    `regressions` and `unresolved` are pre-formatted message strings, byte-
    identical to what `run_harness` has always printed — the caller still
    owns whether/when to print them. `unresolved_names` are the bare metric
    names (the DB's `gate_unresolved` column is derived from these);
    `gate_unresolved` is that list already comma-joined, or None when nothing
    is unresolved.
    """
    passed: bool
    regressions: list[str]
    unresolved: list[str]
    unresolved_names: list[str]
    gate_unresolved: Optional[str]


def decide(
    metrics: EvalMetrics,
    baseline: Optional[EvalRunRow],
    ci_bounds: dict[str, tuple[float, float]],
    tol_frac: float,
    abs_floor: float,
) -> GateVerdict:
    """Decide whether `metrics` passes the regression gate against `baseline`.

    `baseline=None` means there is nothing to compare against — the first run
    under a new `metrics_version` — so every tolerance check is skipped and
    that part of the verdict passes. `overlapping_cues > 0` is a hard
    structural invariant, checked unconditionally, even with no baseline.

    For each metric in `CI_METRICS` that regresses past (`tol_frac`,
    `abs_floor`), a point estimate whose own bootstrap CI still contains the
    baseline value is recorded `unresolved` (not distinguishable from
    resampling noise at this corpus size) rather than a confirmed regression.
    """
    passed = True
    regressions: list[str] = []
    unresolved: list[str] = []
    unresolved_names: list[str] = []

    if baseline is not None:
        for name in CI_METRICS:
            now, base = getattr(metrics, name), getattr(baseline, name)
            if not regressed(now, base, tol_frac, abs_floor):
                continue
            label = _GATE_LABELS[name]
            ci_lo, ci_hi = ci_bounds[name]
            if ci_lo <= base <= ci_hi:
                unresolved.append(
                    f"{label} {now:.4f} vs {base:.4f} (baseline within 95% CI "
                    f"[{ci_lo:.4f}, {ci_hi:.4f}] - unresolved, needs more data)"
                )
                unresolved_names.append(name)
            else:
                passed = False
                regressions.append(f"{label} {now:.4f} vs {base:.4f}")

    if metrics.overlapping_cues > 0:
        passed = False

    return GateVerdict(
        passed=passed,
        regressions=regressions,
        unresolved=unresolved,
        unresolved_names=unresolved_names,
        gate_unresolved=",".join(unresolved_names) or None,
    )
