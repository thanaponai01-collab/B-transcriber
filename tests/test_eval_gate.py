"""transcribe/eval/gate.py — the regression-gate verdict, addressed directly.

Before this module existed, everything here was reachable only through
run_harness: a scratch SQLite database, a bias-index mirror, a golden-set
load off disk, a per-clip pipeline timing loop and a 27-column INSERT, all to
exercise a comparison of a handful of floats. These tests construct
EvalMetrics, an EvalRunRow baseline (or None) and explicit CI bounds, and
assert on the returned GateVerdict. No database, no monkeypatching, no audio.

Run: python -m pytest tests/test_eval_gate.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.db.store import EvalRunRow
from transcribe.eval.gate import decide
from transcribe.eval.metrics import EvalMetrics

TOL_FRAC = 1.02      # regression_tolerance: 0.02
ABS_FLOOR = 0.005    # regression_abs_floor: 0.005

# Both gated metrics not under test in a given case are pinned equal to the
# baseline with a CI that trivially contains it, so they never contribute to
# the verdict.
_QUIET = (0.10, (0.10, 0.10))


def _metrics(cer_thai=0.10, wer_latin=0.10, boundary_error_rate=0.10,
             cue_boundary_error_rate=0.10, overlapping_cues=0):
    return EvalMetrics(
        cer_thai=cer_thai, wer_latin=wer_latin, boundary_error_rate=boundary_error_rate,
        wer=0.0, thai_chars=0, latin_words=0, total_words=0, ref_switches=0,
        cue_boundary_error_rate=cue_boundary_error_rate, overlapping_cues=overlapping_cues,
    )


def _baseline(cer_thai=0.10, wer_latin=0.10, boundary_error_rate=0.10,
              cue_boundary_error_rate=0.10):
    return EvalRunRow(
        id=1, config_hash="base", wer=0.0, boundary_error_rate=boundary_error_rate,
        cer_thai=cer_thai, wer_latin=wer_latin, kind="transcribe",
        pipeline_version="v1", engine_pair="a+b", bias_hash="h", ran_at="2026-01-01",
        passed=True, cue_boundary_error_rate=cue_boundary_error_rate,
    )


def _ci_all_quiet(**overrides):
    ci = {name: _QUIET[1] for name in
          ("cer_thai", "wer_latin", "boundary_error_rate", "cue_boundary_error_rate")}
    ci.update(overrides)
    return ci


# ── the three headline verdict cases ────────────────────────────────────────

def test_regression_whose_ci_excludes_the_baseline_hard_fails():
    metrics = _metrics(cer_thai=0.20)
    baseline = _baseline(cer_thai=0.10)
    ci = _ci_all_quiet(cer_thai=(0.15, 0.25))  # excludes 0.10
    v = decide(metrics, baseline, ci, TOL_FRAC, ABS_FLOOR)
    assert v.passed is False
    assert v.regressions and v.regressions[0].startswith("CER_thai")
    assert v.unresolved == []
    assert v.gate_unresolved is None


def test_regression_whose_ci_contains_the_baseline_is_unresolved_and_still_passes():
    metrics = _metrics(cer_thai=1.0 / 6)  # 0.1667, past the 0.02/0.005 band vs 0.10
    baseline = _baseline(cer_thai=0.10)
    ci = _ci_all_quiet(cer_thai=(0.10, 0.2333))  # contains 0.10
    v = decide(metrics, baseline, ci, TOL_FRAC, ABS_FLOOR)
    assert v.passed is True
    assert v.regressions == []
    assert v.unresolved and v.unresolved[0].startswith("CER_thai")
    assert v.gate_unresolved == "cer_thai"


def test_within_tolerance_move_is_a_clean_pass():
    metrics = _metrics(cer_thai=0.103)  # threshold is max(0.102, 0.105) = 0.105
    baseline = _baseline(cer_thai=0.10)
    ci = _ci_all_quiet(cer_thai=(0.08, 0.12))
    v = decide(metrics, baseline, ci, TOL_FRAC, ABS_FLOOR)
    assert v.passed is True
    assert v.regressions == []
    assert v.unresolved == []
    assert v.gate_unresolved is None


# ── no baseline ──────────────────────────────────────────────────────────────

def test_no_baseline_is_a_pass_with_no_verdict_messages():
    """First run under a new metrics_version: nothing to compare against."""
    metrics = _metrics(cer_thai=0.99)  # would hard-fail against any real baseline
    v = decide(metrics, None, _ci_all_quiet(), TOL_FRAC, ABS_FLOOR)
    assert v.passed is True
    assert v.regressions == []
    assert v.unresolved == []
    assert v.gate_unresolved is None


# ── overlapping_cues: hard structural invariant ─────────────────────────────

def test_overlapping_cues_hard_fails_even_with_no_baseline():
    metrics = _metrics(overlapping_cues=1)
    v = decide(metrics, None, _ci_all_quiet(), TOL_FRAC, ABS_FLOOR)
    assert v.passed is False
    assert v.regressions == []  # not a tolerance-band regression, no baseline to compare to
    assert v.unresolved == []
    assert v.gate_unresolved is None


def test_overlapping_cues_hard_fails_an_otherwise_passing_run():
    metrics = _metrics(overlapping_cues=2)  # every gated metric matches baseline exactly
    baseline = _baseline()
    v = decide(metrics, baseline, _ci_all_quiet(), TOL_FRAC, ABS_FLOOR)
    assert v.passed is False
    assert v.regressions == []
    assert v.unresolved == []
    assert v.gate_unresolved is None


# ── multiple metrics, mixed confirmed + unresolved ──────────────────────────

def test_multiple_regressions_mixing_confirmed_and_unresolved():
    metrics = _metrics(cer_thai=0.20, wer_latin=1.0 / 6)
    baseline = _baseline(cer_thai=0.10, wer_latin=0.10)
    ci = _ci_all_quiet(
        cer_thai=(0.15, 0.25),        # excludes 0.10 -> confirmed
        wer_latin=(0.10, 0.2333),     # contains 0.10 -> unresolved
    )
    v = decide(metrics, baseline, ci, TOL_FRAC, ABS_FLOOR)
    assert v.passed is False  # the confirmed regression alone fails the run
    assert len(v.regressions) == 1 and v.regressions[0].startswith("CER_thai")
    assert len(v.unresolved) == 1 and v.unresolved[0].startswith("WER_latin")
    assert v.gate_unresolved == "wer_latin"  # names only the unresolved metric
