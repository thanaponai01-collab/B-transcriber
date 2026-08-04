"""Metrics v3 acceptance — cue-structure signals (HANDOFF_CEILING_BREAK §3.1).

Why this exists: tokens are phrase cues (5.4 granularity), so a token's
start_ms already IS a cue boundary — no new gold-schema field was needed, the
existing hand-recut-SRT gold set already carries it. This promotes the cue
timing quality (the thing the user's Premiere recut loop actually fixes,
TODO_LEDGER 2026-07-30) from an ad hoc one-off computation to a first-class,
regression-gated signal: cue_boundary_error_rate (F1@tol on cue starts, same
match rule as switch points), a hard invariant (overlapping_cues must be 0 —
not a rate), and descriptive-only trend stats (cue_count_delta,
shortest_cue_ms, nonzero_gap_count).

Run: python -m pytest tests/test_metrics_v3.py -v
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.db import store
from transcribe.eval.metrics import METRICS_VERSION, compute_metrics


def _tmp_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    db = Path(f.name)
    store.init_db(db)
    return db


def test_metrics_version_is_3():
    assert METRICS_VERSION == 3


# ── cue-boundary F1 ────────────────────────────────────────────────────────────

def test_identical_cue_starts_score_perfect():
    ref = [
        {"text": "สวัสดี", "script": "thai", "start_ms": 0, "end_ms": 900},
        {"text": "ครับ", "script": "thai", "start_ms": 900, "end_ms": 1500},
    ]
    m = compute_metrics(ref, ref)
    assert m.ref_cues == 2
    assert m.hyp_cues == 2
    assert m.matched_cues == 2
    assert m.cue_boundary_error_rate == 0.0


def test_cue_start_within_tolerance_matches():
    ref = [{"text": "สวัสดีครับ", "script": "thai", "start_ms": 1000, "end_ms": 2000}]
    hyp = [{"text": "สวัสดีครับ", "script": "thai", "start_ms": 1250, "end_ms": 2000}]
    m = compute_metrics(ref, hyp, boundary_tol_ms=300.0)
    assert m.matched_cues == 1
    assert m.cue_boundary_error_rate == 0.0


def test_cue_start_outside_tolerance_misses():
    ref = [{"text": "สวัสดีครับ", "script": "thai", "start_ms": 1000, "end_ms": 2000}]
    hyp = [{"text": "สวัสดีครับ", "script": "thai", "start_ms": 5000, "end_ms": 6000}]
    m = compute_metrics(ref, hyp, boundary_tol_ms=300.0)
    assert m.matched_cues == 0
    assert m.cue_boundary_error_rate == 1.0


def test_extra_hyp_cue_penalizes_precision():
    # Gold has one cue; hyp over-splits into two → a false-positive cue start
    # with nothing to match, same micro-F1 shape as a hallucinated switch.
    ref = [{"text": "สวัสดีครับผมมาแล้ว", "script": "thai", "start_ms": 0, "end_ms": 2000}]
    hyp = [
        {"text": "สวัสดีครับ", "script": "thai", "start_ms": 0, "end_ms": 1000},
        {"text": "ผมมาแล้ว", "script": "thai", "start_ms": 1000, "end_ms": 2000},
    ]
    m = compute_metrics(ref, hyp)
    assert m.ref_cues == 1
    assert m.hyp_cues == 2
    assert m.matched_cues == 1
    assert 0.0 < m.cue_boundary_error_rate < 1.0


# ── hard invariant: overlapping cues ──────────────────────────────────────────

def test_no_overlap_on_well_formed_hyp():
    hyp = [
        {"text": "ก", "script": "thai", "start_ms": 0, "end_ms": 1000},
        {"text": "ข", "script": "thai", "start_ms": 1000, "end_ms": 2000},
    ]
    m = compute_metrics(hyp, hyp)
    assert m.overlapping_cues == 0


def test_overlapping_hyp_cues_detected():
    # TODO_LEDGER 2026-07-30: cues 20/21 shipped as `42,740 --> 42,660`.
    ref = [{"text": "ก", "script": "thai", "start_ms": 0, "end_ms": 1000}]
    hyp = [
        {"text": "ก", "script": "thai", "start_ms": 0, "end_ms": 42740},
        {"text": "ข", "script": "thai", "start_ms": 42660, "end_ms": 43000},
    ]
    m = compute_metrics(ref, hyp)
    assert m.overlapping_cues == 1


# ── descriptive stats ──────────────────────────────────────────────────────────

def test_cue_count_delta_and_shortest_and_gaps():
    ref = [{"text": "ก", "script": "thai", "start_ms": 0, "end_ms": 1000}]
    hyp = [
        {"text": "ก", "script": "thai", "start_ms": 0, "end_ms": 560},     # 560ms cue
        {"text": "ข", "script": "thai", "start_ms": 700, "end_ms": 1500},  # 140ms gap before it
    ]
    m = compute_metrics(ref, hyp)
    assert m.cue_count_delta == 1          # 2 hyp cues - 1 ref cue
    assert m.shortest_cue_ms == 560.0
    assert m.nonzero_gap_count == 1


def test_missing_timestamps_are_skipped_not_fatal():
    # Unit fixtures without start_ms (as used by other metrics tests) must not
    # crash the v3 cue computation — they just contribute zero cues.
    ref = [{"text": "กขคง", "script": "thai"}]
    m = compute_metrics(ref, ref)
    assert m.ref_cues == 0
    assert m.hyp_cues == 0
    assert m.overlapping_cues == 0
    assert m.shortest_cue_ms is None
    assert m.cue_boundary_error_rate == 0.0


# ── harness: hard-fail on overlap, cue-BER in the regression gate ────────────

def test_harness_hard_fails_on_overlapping_cues_even_with_no_baseline(monkeypatch):
    from transcribe.eval import harness

    db = _tmp_db()
    ref = [{"text": "ก", "script": "thai", "start_ms": 0, "end_ms": 1000}]
    monkeypatch.setattr(harness, "_load_goldenset", lambda: [(Path("a.wav"), ref)])
    overlapping_hyp = [
        {"text": "ก", "script": "thai", "start_ms": 0, "end_ms": 1000},
        {"text": "ข", "script": "thai", "start_ms": 900, "end_ms": 2000},  # overlaps prev
    ]
    result = harness.run_harness(
        {"regression_tolerance": 0.02, "regression_abs_floor": 0.005},
        db, pipeline_fn=lambda p, c: overlapping_hyp,
    )
    assert result is not None
    assert result.baseline is None, "first run — no prior baseline to compare against"
    assert result.metrics.overlapping_cues == 1
    assert not result.passed, "overlapping cues must hard-fail even without a baseline"


def test_harness_records_cue_metrics_on_eval_run(monkeypatch):
    from transcribe.eval import harness

    db = _tmp_db()
    ref = [
        {"text": "สวัสดี", "script": "thai", "start_ms": 0, "end_ms": 900},
        {"text": "ครับ", "script": "thai", "start_ms": 900, "end_ms": 1500},
    ]
    monkeypatch.setattr(harness, "_load_goldenset", lambda: [(Path("a.wav"), ref)])
    result = harness.run_harness(
        {"regression_tolerance": 0.02, "regression_abs_floor": 0.005},
        db, pipeline_fn=lambda p, c: ref,
    )
    assert result is not None and result.passed
    conn = store.connect(db)
    last = store.get_last_passing_eval(conn)
    assert last is not None
    assert last.cue_boundary_error_rate == 0.0
    assert last.overlapping_cues == 0
    assert last.metrics_version == METRICS_VERSION
    conn.close()
