"""Metrics v2 acceptance — intra-cue switch points, micro-F1 BER aggregation,
and metrics_version baseline partitioning.

Why this exists: tokens are phrase cues, so a real Thai↔Latin code-switch
almost always happens INSIDE a `mixed` cue. Metrics v1 derived switch points
from the token-level `script` field only, which made every intra-cue switch
invisible — the whole gold set scored `switches=0` and BER was structurally
pinned at 0.0, blinding the very gate that decides Engine B / LLM-reconciler
activation.

Run: python -m pytest tests/test_metrics_v2.py -v
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


# ── intra-cue switch detection ────────────────────────────────────────────────

def test_mixed_cue_yields_switch_points():
    # One mixed phrase cue containing an embedded English phrase → two switches
    # (thai→latin, latin→thai), previously invisible at cue granularity.
    ref = [{"text": "ผมอยากจะ share screen ให้ดู", "script": "mixed",
            "start_ms": 0, "end_ms": 2600}]
    m = compute_metrics(ref, ref)
    assert m.ref_switches == 2
    assert m.boundary_error_rate == 0.0   # ref vs itself: perfect


def test_digits_are_neutral_not_switches():
    # "ก 2 ก" — a digit between Thai words is not a Thai↔Latin switch
    # (STYLE_GUIDE §4: scripts are about pronunciation, digits carry none).
    ref = [{"text": "หน้า 2 ครับ", "script": "mixed", "start_ms": 0, "end_ms": 1000}]
    m = compute_metrics(ref, ref)
    assert m.ref_switches == 0


def test_intra_cue_switch_timestamp_is_interpolated():
    # 10 chars over [0, 1000] ms, latin run starts at char 5 → switch ≈ 500 ms.
    # A hyp that places the same switch at a *different token boundary* near
    # 500 ms must match within the 300 ms tolerance; one 5 s away must not.
    ref = [{"text": "กกกกกAAAAA", "script": "mixed", "start_ms": 0, "end_ms": 1000}]
    hyp_ok = [
        {"text": "กกกกก", "script": "thai", "start_ms": 0, "end_ms": 450},
        {"text": "AAAAA", "script": "latin", "start_ms": 480, "end_ms": 1000},
    ]
    hyp_bad = [
        {"text": "กกกกก", "script": "thai", "start_ms": 0, "end_ms": 450},
        {"text": "AAAAA", "script": "latin", "start_ms": 5500, "end_ms": 6000},
    ]
    assert compute_metrics(ref, hyp_ok, boundary_tol_ms=300.0).boundary_error_rate == 0.0
    assert compute_metrics(ref, hyp_bad, boundary_tol_ms=300.0).boundary_error_rate > 0.0


def test_cross_token_switch_unchanged_from_v1():
    # Pure-script token streams must behave exactly as before: the switch sits
    # at the first Latin character of the Latin token, i.e. its start_ms.
    ref = [
        {"text": "สวัสดี", "script": "thai", "start_ms": 0, "end_ms": 900},
        {"text": "Hello", "script": "latin", "start_ms": 1000, "end_ms": 1400},
    ]
    m = compute_metrics(ref, ref)
    assert m.ref_switches == 1
    assert m.boundary_error_rate == 0.0


# ── false-positive switches are penalized (micro-F1) ─────────────────────────

def test_hallucinated_switch_counts_against_hypothesis():
    # Reference is monolingual Thai (zero switches). A hypothesis that invents
    # a Latin word creates a hyp switch with nothing to match → BER must be 1,
    # and the counts must expose it for corpus-level micro aggregation.
    ref = [{"text": "สวัสดีครับผม", "script": "thai", "start_ms": 0, "end_ms": 1000}]
    hyp = [{"text": "สวัสดี okay ครับ", "script": "mixed", "start_ms": 0, "end_ms": 1000}]
    m = compute_metrics(ref, hyp)
    assert m.ref_switches == 0
    assert m.hyp_switches == 2
    assert m.matched_switches == 0
    assert m.boundary_error_rate == 1.0


def test_harness_micro_aggregation_penalizes_fp_on_clean_sample(monkeypatch):
    # Two samples: one with a real (matched) switch, one monolingual where the
    # hyp hallucinates switches. A ref-weighted mean (v1) would score 0.0;
    # micro-F1 must come out worse than 0.
    from transcribe.eval import harness

    db = _tmp_db()
    ref_switchy = [
        {"text": "สวัสดี", "script": "thai", "start_ms": 0, "end_ms": 900},
        {"text": "Hello", "script": "latin", "start_ms": 1000, "end_ms": 1400},
    ]
    ref_clean = [{"text": "สวัสดีครับผม", "script": "thai", "start_ms": 0, "end_ms": 1000}]
    monkeypatch.setattr(harness, "_load_goldenset", lambda: [
        (Path("a.wav"), ref_switchy), (Path("b.wav"), ref_clean),
    ])

    hyps = {
        "a.wav": ref_switchy,  # perfect on the switchy sample
        "b.wav": [{"text": "สวัสดี okay ครับ", "script": "mixed",
                   "start_ms": 0, "end_ms": 1000}],  # hallucinated switch
    }
    result = harness.run_harness(
        {"regression_tolerance": 0.02, "regression_abs_floor": 0.005},
        db, pipeline_fn=lambda p, c: hyps[Path(p).name],
    )
    assert result is not None
    assert result.metrics.ref_switches == 1
    assert result.metrics.hyp_switches == 3
    assert result.metrics.matched_switches == 1
    # micro-F1: precision 1/3, recall 1/1 → F1 = 0.5 → BER = 0.5
    assert abs(result.metrics.boundary_error_rate - 0.5) < 1e-9


# ── metrics_version baseline partitioning ────────────────────────────────────

def test_old_metrics_version_rows_are_not_current_baselines():
    db = _tmp_db()
    conn = store.connect(db)
    # A passing v1-era row (e.g. migrated from a pre-column DB).
    store.create_eval_run(conn, "old", 0.0, 0.0, True, cer_thai=0.0, wer_latin=0.0,
                          metrics_version=1)
    assert store.get_last_passing_eval(conn) is None or METRICS_VERSION == 1
    # A current-version row becomes the baseline.
    store.create_eval_run(conn, "new", 0.1, 0.1, True, cer_thai=0.10, wer_latin=0.10)
    last = store.get_last_passing_eval(conn)
    assert last is not None
    assert last.config_hash == "new"
    assert last.metrics_version == METRICS_VERSION
    # The v1 row is still reachable when asked for explicitly.
    v1 = store.get_last_passing_eval(conn, metrics_version=1)
    assert v1 is not None and v1.config_hash == "old"
    conn.close()


def test_harness_first_run_after_metric_change_passes(monkeypatch):
    # A perfect-zero v1 baseline would fail ANY nonzero v2 score if versions
    # weren't partitioned. The first v2 run must instead pass as the fresh
    # v2 baseline.
    from transcribe.eval import harness

    db = _tmp_db()
    conn = store.connect(db)
    store.create_eval_run(conn, "v1-perfect", 0.0, 0.0, True,
                          cer_thai=0.0, wer_latin=0.0, metrics_version=1)
    conn.close()

    ref = [{"text": "ผมใช้ Windows ครับ", "script": "mixed", "start_ms": 0, "end_ms": 1500}]
    # Imperfect hypothesis: nonzero CER + a mistimed switch.
    hyp = [{"text": "ผมใช่ Windows นะ", "script": "mixed", "start_ms": 0, "end_ms": 1500}]
    monkeypatch.setattr(harness, "_load_goldenset", lambda: [(Path("x.wav"), ref)])

    result = harness.run_harness(
        {"regression_tolerance": 0.02, "regression_abs_floor": 0.005},
        db, pipeline_fn=lambda p, c: hyp,
    )
    assert result is not None
    assert result.baseline is None, "v1 row must not be the v2 baseline"
    assert result.passed
