"""EvalMetrics.aggregate + create_eval_run round-trip.

Aggregation's external behaviour is: given per-clip metrics, what corpus
metrics come out. Every assertion here is on the returned aggregate — no
database, no pipeline, no audio, no GPU. That is the point of the seam:
corpus weighting used to be ~20 hand-rolled accumulators in run_harness,
away from the metric definitions whose property the weighting actually is.

The round-trip test covers the class of bug the old 28-parameter
create_eval_run invited and nothing tested: a value written into the wrong
column, which produces plausible-looking numbers rather than a crash.

Run: python -m pytest tests/test_eval_aggregation.py -v
"""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.db import store
from transcribe.eval.metrics import METRICS_VERSION, EvalMetrics


def _clip(**kw) -> EvalMetrics:
    base = dict(cer_thai=0.0, wer_latin=0.0, boundary_error_rate=0.0, wer=0.0,
                thai_chars=0, latin_words=0, total_words=0, ref_switches=0)
    base.update(kw)
    return EvalMetrics(**base)


# ── reference-weighted means ────────────────────────────────────────────────

def test_reference_weighted_metric_aggregates_by_weight_not_clip_count():
    """Two clips with very different thai_chars must not contribute equally."""
    clips = [
        _clip(cer_thai=0.0, thai_chars=900),
        _clip(cer_thai=1.0, thai_chars=100),
    ]
    agg = EvalMetrics.aggregate(clips)
    assert agg.cer_thai == pytest.approx(0.10), "char-weighted, not the 0.5 clip mean"
    assert agg.thai_chars == 1000


def test_each_rate_uses_its_own_weight():
    clips = [
        _clip(cer_thai=0.0, wer_latin=1.0, wer=0.0, thai_chars=100, latin_words=10, total_words=50),
        _clip(cer_thai=1.0, wer_latin=0.0, wer=1.0, thai_chars=100, latin_words=90, total_words=50),
    ]
    agg = EvalMetrics.aggregate(clips)
    assert agg.cer_thai == pytest.approx(0.5)     # equal thai_chars
    assert agg.wer_latin == pytest.approx(0.1)    # 10 vs 90 latin_words
    assert agg.wer == pytest.approx(0.5)          # equal total_words


def test_zero_weight_does_not_divide_by_zero():
    agg = EvalMetrics.aggregate([_clip(cer_thai=0.7, thai_chars=0)])
    assert agg.cer_thai == 0.0
    assert agg.wer_latin == 0.0
    assert agg.wer == 0.0


# ── micro-F1, not a weighted mean ───────────────────────────────────────────

def test_boundary_error_rate_penalizes_hallucinated_switches_on_a_zero_switch_clip():
    """The exact case the old harness comment said a weighted mean would lose:
    a clip with zero reference switches but nonzero hypothesis switches. Under
    ref-weighting its weight is 0 and the false positives vanish."""
    clips = [
        _clip(ref_switches=10, hyp_switches=10, matched_switches=10),
        _clip(ref_switches=0, hyp_switches=10, matched_switches=0),   # all hallucinated
    ]
    agg = EvalMetrics.aggregate(clips)
    assert agg.boundary_error_rate > 0.0, "hallucinated switches must be penalized"
    # micro-F1: precision 10/20, recall 10/10 -> F1 = 2/3
    assert agg.boundary_error_rate == pytest.approx(1 - 2 / 3)


def test_cue_boundary_error_rate_gets_the_same_micro_f1_treatment():
    clips = [
        _clip(ref_cues=10, hyp_cues=10, matched_cues=10),
        _clip(ref_cues=0, hyp_cues=10, matched_cues=0),
    ]
    agg = EvalMetrics.aggregate(clips)
    assert agg.cue_boundary_error_rate == pytest.approx(1 - 2 / 3)


# ── plain sums, global minimum ──────────────────────────────────────────────

def test_counts_and_deltas_are_plain_sums():
    clips = [
        _clip(overlapping_cues=1, cue_count_delta=3, nonzero_gap_count=4, ref_cues=2, hyp_cues=5),
        _clip(overlapping_cues=2, cue_count_delta=-1, nonzero_gap_count=6, ref_cues=7, hyp_cues=1),
    ]
    agg = EvalMetrics.aggregate(clips)
    assert agg.overlapping_cues == 3
    assert agg.cue_count_delta == 2
    assert agg.nonzero_gap_count == 10
    assert agg.ref_cues == 9 and agg.hyp_cues == 6


def test_shortest_cue_ms_is_a_global_minimum_skipping_none():
    """A single flash-frame cue anywhere in the corpus must still be caught."""
    clips = [_clip(shortest_cue_ms=900.0), _clip(shortest_cue_ms=None),
             _clip(shortest_cue_ms=140.0), _clip(shortest_cue_ms=2000.0)]
    assert EvalMetrics.aggregate(clips).shortest_cue_ms == 140.0


def test_shortest_cue_ms_is_none_when_every_clip_is_none():
    assert EvalMetrics.aggregate([_clip(), _clip()]).shortest_cue_ms is None


def test_empty_clip_list_does_not_raise():
    """The empty-gold-set refusal happens before this point; aggregation itself
    must simply return zeros rather than blow up."""
    agg = EvalMetrics.aggregate([])
    assert agg.cer_thai == 0.0 and agg.wer_latin == 0.0 and agg.wer == 0.0
    assert agg.boundary_error_rate == 0.0 and agg.cue_boundary_error_rate == 0.0
    assert agg.thai_chars == 0 and agg.shortest_cue_ms is None


def test_single_clip_aggregates_to_itself():
    clip = _clip(cer_thai=0.25, wer_latin=0.5, wer=0.3, thai_chars=80,
                 latin_words=4, total_words=20, ref_switches=3, hyp_switches=4,
                 matched_switches=2, ref_cues=6, hyp_cues=7, matched_cues=5,
                 shortest_cue_ms=333.0, nonzero_gap_count=2, cue_count_delta=1)
    agg = EvalMetrics.aggregate([clip])
    for field in ("cer_thai", "wer_latin", "wer", "thai_chars", "latin_words",
                  "total_words", "ref_switches", "hyp_switches", "matched_switches",
                  "ref_cues", "hyp_cues", "matched_cues", "shortest_cue_ms",
                  "nonzero_gap_count", "cue_count_delta"):
        assert getattr(agg, field) == getattr(clip, field), field


# ── store round-trip ────────────────────────────────────────────────────────

def _tmp_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    path = Path(f.name)
    store.init_db(path)
    return path


def test_every_written_column_reads_back_from_the_column_it_was_meant_for():
    """Distinct values per field, so a transposition between two same-typed
    columns (e.g. a pair of CI bounds) cannot pass."""
    db = _tmp_db()
    run = store.EvalRun(
        config_hash="cfg-hash", wer=0.11, boundary_error_rate=0.12, passed=True,
        cer_thai=0.13, wer_latin=0.14, kind="transcribe",
        pipeline_version="9.9.9", engine_pair="a+b", bias_hash="bias-hash",
        is_experiment=True, metrics_version=7,
        cue_boundary_error_rate=0.15, overlapping_cues=16,
        cue_count_delta=-17, shortest_cue_ms=18.5, nonzero_gap_count=19,
        cer_thai_ci_lo=0.20, cer_thai_ci_hi=0.21,
        wer_latin_ci_lo=0.22, wer_latin_ci_hi=0.23,
        boundary_error_rate_ci_lo=0.24, boundary_error_rate_ci_hi=0.25,
        cue_boundary_error_rate_ci_lo=0.26, cue_boundary_error_rate_ci_hi=0.27,
        rtf=0.28, gate_unresolved="cer_thai,wer_latin", cue_legality_violations=29,
    )
    conn = store.connect(db)
    try:
        row_id = store.create_eval_run(conn, run)
        assert row_id > 0
        # list_eval_runs, not get_last_passing_eval: the latter deliberately
        # excludes experiment runs, and is_experiment=True is one of the values
        # under test here.
        rows = store.list_eval_runs(conn)
    finally:
        conn.close()
        db.unlink()

    assert len(rows) == 1
    back = rows[0]
    for field in (
        "config_hash", "wer", "boundary_error_rate", "cer_thai", "wer_latin",
        "kind", "pipeline_version", "engine_pair", "bias_hash", "is_experiment",
        "metrics_version", "cue_boundary_error_rate", "overlapping_cues",
        "cue_count_delta", "shortest_cue_ms", "nonzero_gap_count",
        "cer_thai_ci_lo", "cer_thai_ci_hi", "wer_latin_ci_lo", "wer_latin_ci_hi",
        "boundary_error_rate_ci_lo", "boundary_error_rate_ci_hi",
        "cue_boundary_error_rate_ci_lo", "cue_boundary_error_rate_ci_hi",
        "rtf", "gate_unresolved", "cue_legality_violations", "passed",
    ):
        assert getattr(back, field) == getattr(run, field), f"{field} did not round-trip"


def test_metrics_version_none_stamps_the_current_version():
    """Baseline partitioning depends on this; the db layer must still resolve it
    lazily rather than importing the eval tier at module load."""
    db = _tmp_db()
    conn = store.connect(db)
    try:
        store.create_eval_run(conn, store.EvalRun(
            config_hash="c", wer=0.0, boundary_error_rate=0.0, passed=True))
        back = store.get_last_passing_eval(conn)
    finally:
        conn.close()
        db.unlink()
    assert back is not None
    assert back.metrics_version == METRICS_VERSION


def test_every_eval_run_field_is_persisted():
    """A metric added to the record but forgotten in the column list would
    aggregate and print but never be stored — user story 20's half-added
    metric. This makes that a test failure instead of a silent hole."""
    from dataclasses import fields
    assert {f.name for f in fields(store.EvalRun)} == set(store._EVAL_RUN_COLUMNS)
