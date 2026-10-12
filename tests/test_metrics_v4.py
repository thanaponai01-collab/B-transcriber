"""Metrics v4: speech_coverage_miss and orphan_cues (docs/arch-design-transcription-engine.md #1).

Run: python -m pytest tests/test_metrics_v4.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.eval.metrics import EvalMetrics, METRICS_VERSION, compute_metrics


def _tok(text, start, end):
    return {"text": text, "script": "thai", "start_ms": start, "end_ms": end}


def test_version_bumped():
    assert METRICS_VERSION == 4


def test_dropped_cue_counts_its_full_duration():
    ref = [_tok("ก", 0, 1000), _tok("ข", 2000, 5000)]
    hyp = [_tok("ก", 0, 1000)]  # the 3 s cue produced nothing
    m = compute_metrics(ref, hyp)
    assert m.ref_speech_ms == 4000 and m.missed_speech_ms == 3000
    assert m.speech_coverage_miss == 0.75


def test_wrong_text_over_real_speech_is_not_a_coverage_miss():
    ref = [_tok("ก", 0, 1000)]
    hyp = [_tok("ผิด", 100, 900)]
    assert compute_metrics(ref, hyp).speech_coverage_miss == 0.0


def test_no_timestamps_means_zero_not_a_crash():
    m = compute_metrics([{"text": "ก", "script": "thai"}], [])
    assert m.ref_speech_ms == 0 and m.speech_coverage_miss == 0.0


def test_orphan_is_short_and_isolated():
    hyp = [_tok("ก", 0, 2000), _tok("น", 5000, 5120), _tok("ข", 9000, 11000)]
    assert compute_metrics([], hyp).orphan_cues == 1
    # a short cue butted against a neighbour is not an orphan
    hyp = [_tok("ก", 0, 2000), _tok("น", 2050, 2170)]
    assert compute_metrics([], hyp).orphan_cues == 0


def test_aggregate_weights_by_reference_speech():
    long_clip = EvalMetrics(0, 0, 0, 0, 0, 0, 0, 0, speech_coverage_miss=0.0, ref_speech_ms=9000, missed_speech_ms=0)
    short_clip = EvalMetrics(0, 0, 0, 0, 0, 0, 0, 0, speech_coverage_miss=1.0, ref_speech_ms=1000, missed_speech_ms=1000)
    agg = EvalMetrics.aggregate([long_clip, short_clip])
    assert agg.speech_coverage_miss == 0.1
    assert agg.missed_speech_ms == 1000


def test_resolve_db_path_is_repo_anchored_not_cwd(tmp_path, monkeypatch):
    from transcribe.db import store
    monkeypatch.chdir(tmp_path)
    assert store.resolve_db_path({"store": {"path": "transcriber.db"}}) == store._DEFAULT_DB
    assert store.resolve_db_path({}) == store._DEFAULT_DB
    assert store.resolve_db_path({"store": {"path": str(tmp_path / "x.db")}}) == tmp_path / "x.db"
