"""Paired gate evidence, corpus identity, baseline lineage and uncertainty."""
import dataclasses
import json
import sqlite3
from pathlib import Path

import pytest

from transcribe.db import store
from transcribe.eval import gate, harness
from transcribe.eval.metrics import CI_METRICS, EvalMetrics, bootstrap_ci, paired_bootstrap_ci


def clip(rate, weight=100, **counts):
    return EvalMetrics(rate, 0, 0, 0, weight, 0, 0, 0, **counts)


def test_pairing_cancels_clip_difficulty_and_detects_small_consistent_regression():
    baseline = [clip(0.1), clip(0.9)]
    candidate = [clip(0.12), clip(0.92)]
    lo, hi = paired_bootstrap_ci(candidate, baseline, 'cer_thai')
    assert lo == pytest.approx(0.02)
    assert hi == pytest.approx(0.02)
    # The old candidate-only band could not distinguish this consistent change.
    assert bootstrap_ci(candidate, 'cer_thai')[0] < 0.5 < bootstrap_ci(candidate, 'cer_thai')[1]
    v = gate.decide(EvalMetrics.aggregate(candidate), EvalMetrics.aggregate(baseline),
                    {name: (lo, hi) if name == 'cer_thai' else (0, 0) for name in CI_METRICS}, 1.02, .005)
    assert v.status == 'regression' and not v.passed


def test_identical_runs_have_exact_zero_delta_for_every_metric():
    clips = [clip(.1, 900, hyp_switches=3, matched_switches=0, ref_cues=2, hyp_cues=3, matched_cues=2),
             clip(.9, 100, hyp_switches=0, matched_switches=0, ref_cues=0, hyp_cues=1)]
    for name in CI_METRICS:
        assert paired_bootstrap_ci(clips, clips, name) == (0, 0)


def test_paired_bootstrap_reuses_weighted_and_micro_f1_aggregation():
    base = [clip(.1, 900, hyp_switches=0), clip(.9, 100, hyp_switches=0)]
    now = [clip(.2, 900, hyp_switches=1), clip(.8, 100, hyp_switches=2)]
    assert paired_bootstrap_ci(now, base, 'cer_thai') == pytest.approx((-.1, .1))
    # Hallucinated switches on monolingual clips must not disappear through weighting.
    assert paired_bootstrap_ci(now, base, 'boundary_error_rate') == (1, 1)
    assert paired_bootstrap_ci(now, base, 'cer_thai') == paired_bootstrap_ci(now, base, 'cer_thai')


@pytest.mark.parametrize('candidate,baseline', [([], []), ([clip(.1)], []), ([clip(.1)], [clip(.1), clip(.2)])])
def test_unmatched_or_empty_corpora_cannot_be_bootstrapped(candidate, baseline):
    with pytest.raises(ValueError):
        paired_bootstrap_ci(candidate, baseline, 'cer_thai')


def test_small_point_delta_can_be_unresolved_instead_of_passed():
    v = gate.decide(clip(.101), clip(.1),
                    {name: (.004, .007) if name == 'cer_thai' else (0, 0) for name in CI_METRICS}, 1.02, .005)
    assert v.status == 'unresolved' and not v.passed
    assert v.gate_unresolved == 'cer_thai'


def test_confirmed_improvement_is_reported():
    v = gate.decide(clip(.08), clip(.1),
                    {name: (-.03, -.01) if name == 'cer_thai' else (0, 0) for name in CI_METRICS}, 1.02, .005)
    assert v.passed and v.status == 'pass'
    assert len(v.improvements) == 1


REF = [{'text': 'กขคง', 'script': 'thai', 'start_ms': 0, 'end_ms': 900}]
CFG = {'engine_a': 'mock', 'engine_b': 'passthrough'}


def run_fixture(monkeypatch, tmp_path):
    monkeypatch.setattr(harness, '_load_goldenset', lambda: [(Path('fake.wav'), REF)])
    monkeypatch.setattr(harness, '_audio_duration_s', lambda _: 1)
    db = tmp_path / 'eval.db'
    def run(text='กขคง', **kwargs):
        return harness.run_harness(CFG, db, pipeline_fn=lambda *a: [{**REF[0], 'text': text}], **kwargs)
    return db, run


def test_per_clip_roundtrip_and_paired_baseline_lineage(monkeypatch, tmp_path):
    db, run = run_fixture(monkeypatch, tmp_path)
    first = run('กขคด')
    better = run(experiment=True)
    same = run('กขคด')
    assert first.passed and first.baseline is None
    assert better.passed and better.paired_ci['cer_thai'] == (-.25, -.25)
    assert same.passed and all(value == (0, 0) for value in same.paired_ci.values())
    conn = store.connect(db)
    try:
        rows = sorted(store.list_eval_runs(conn), key=lambda row: row.id)
        assert rows[1].baseline_eval_id == rows[0].id
        assert rows[2].baseline_eval_id == rows[0].id  # experiment never becomes baseline
        assert json.loads(rows[2].paired_delta_ci_json)['cer_thai'] == [0, 0]
        saved = store.get_eval_clip_metrics(conn, rows[0].id)
        assert len(saved) == 1
        assert EvalMetrics(**json.loads(next(iter(saved.values())))).cer_thai == .25
    finally:
        conn.close()


def test_unresolved_legacy_data_do_not_replace_baseline(monkeypatch, tmp_path):
    db, run = run_fixture(monkeypatch, tmp_path)
    store.init_db(db)
    conn = store.connect(db)
    old = store.create_eval_run(conn, store.EvalRun('old', 0, 0, True, cer_thai=0))
    conn.close()
    result = run()
    assert result.status == 'unresolved' and not result.passed
    conn = store.connect(db)
    try:
        assert store.get_last_passing_eval(conn).id == old
    finally:
        conn.close()
    assert run(establish_baseline=True).passed
    assert run().paired_ci['cer_thai'] == (0, 0)


def test_legacy_unresolved_pass_is_excluded_from_baselines(tmp_path):
    db = tmp_path / 'eval.db'
    store.init_db(db)
    conn = store.connect(db)
    try:
        old = store.create_eval_run(conn, store.EvalRun('good', 0, 0, True))
        store.create_eval_run(conn, store.EvalRun('uncertain', 0, 0, True, gate_unresolved='cer_thai'))
        assert store.get_last_passing_eval(conn).id == old
    finally:
        conn.close()


@pytest.mark.parametrize('change', ['media', 'reference', 'policy', 'members'])
def test_changed_corpus_or_scoring_policy_cannot_pair(monkeypatch, tmp_path, change):
    audio = tmp_path / 'real.wav'
    audio.write_bytes(b'original')
    samples = [(audio, list(REF))]
    monkeypatch.setattr(harness, '_load_goldenset', lambda: samples)
    monkeypatch.setattr(harness, '_audio_duration_s', lambda _: 1)
    db = tmp_path / 'eval.db'
    pipeline = lambda *a: REF
    assert harness.run_harness(CFG, db, pipeline_fn=pipeline).passed
    cfg = dict(CFG)
    if change == 'media':
        audio.write_bytes(b'changed')
    elif change == 'reference':
        samples[0] = (audio, [{**REF[0], 'text': 'changed'}])
    elif change == 'policy':
        cfg['boundary_tol_ms'] = 500
    else:
        samples.append((Path('other.wav'), REF))
    result = harness.run_harness(cfg, db, pipeline_fn=pipeline)
    assert result.status == 'unresolved' and result.paired_ci is None


def test_explicit_baseline_cannot_be_an_experiment(monkeypatch, tmp_path):
    _, run = run_fixture(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match='production'):
        run(experiment=True, establish_baseline=True)


def test_eval_and_clip_evidence_are_saved_atomically(tmp_path):
    db = tmp_path / 'eval.db'
    store.init_db(db)
    conn = store.connect(db)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            store.create_eval_run(conn, store.EvalRun('bad', 0, 0, True), {None: '{}'})
        assert store.list_eval_runs(conn) == []
    finally:
        conn.close()

def test_reordered_clips_are_paired_by_identity(monkeypatch, tmp_path):
    samples = [(Path('one.wav'), REF), (Path('two.wav'), REF)]
    monkeypatch.setattr(harness, '_load_goldenset', lambda: samples)
    monkeypatch.setattr(harness, '_audio_duration_s', lambda _: 1)
    db = tmp_path / 'eval.db'
    pipeline = lambda path, cfg: [{**REF[0], 'text': 'กขคด' if path.name == 'one.wav' else 'กขคง'}]
    assert harness.run_harness(CFG, db, pipeline_fn=pipeline).passed
    samples.reverse()
    result = harness.run_harness(CFG, db, pipeline_fn=pipeline)
    assert result.passed
    assert all(bounds == (0, 0) for bounds in result.paired_ci.values())


def test_baseline_establishment_still_rejects_overlapping_cues(monkeypatch, tmp_path):
    db, _ = run_fixture(monkeypatch, tmp_path)
    overlap = [dict(REF[0]), {**REF[0], 'start_ms': 100}]
    result = harness.run_harness(CFG, db, pipeline_fn=lambda *a: overlap, establish_baseline=True)
    assert result.status == 'regression' and not result.passed
    conn = store.connect(db)
    try:
        assert store.get_last_passing_eval(conn) is None
    finally:
        conn.close()


def test_unresolved_bias_update_is_rejected_with_correct_reason(monkeypatch, tmp_path):
    from transcribe.flywheel import biasindex
    db = tmp_path / 'eval.db'
    store.init_db(db)
    conn = store.connect(db)
    store.upsert_bias_term(conn, 'AI', 'technical', 'latin', 'flywheel')
    conn.close()
    unresolved = harness.HarnessResult(clip(.1), False, None, status='unresolved')
    monkeypatch.setattr(harness, 'run_harness', lambda *a: unresolved)
    with pytest.raises(RuntimeError, match='unresolved'):
        biasindex._run_regression_gate(CFG, db, ['AI'])
    conn = store.connect(db)
    try:
        assert store.get_bias_term_strings(conn) == []
    finally:
        conn.close()

def test_paired_uncertainty_does_not_promote_a_production_candidate(monkeypatch, tmp_path):
    references = {'one.wav': 'ก' * 100, 'two.wav': 'ค' * 100}
    samples = [(Path(name), [{**REF[0], 'text': text}]) for name, text in references.items()]
    monkeypatch.setattr(harness, '_load_goldenset', lambda: samples)
    monkeypatch.setattr(harness, '_audio_duration_s', lambda _: 1)
    db = tmp_path / 'eval.db'

    def baseline_pipeline(path, cfg):
        return [{**REF[0], 'text': references[path.name][:90] + 'ข' * 10}]

    def candidate_pipeline(path, cfg):
        errors = 10 if path.name == 'one.wav' else 30
        return [{**REF[0], 'text': references[path.name][:-errors] + 'ข' * errors}]

    assert harness.run_harness(CFG, db, pipeline_fn=baseline_pipeline).passed
    conn = store.connect(db)
    baseline_id = store.get_last_passing_eval(conn).id
    conn.close()
    result = harness.run_harness(CFG, db, pipeline_fn=candidate_pipeline)
    assert result.status == 'unresolved' and not result.passed
    assert result.paired_ci['cer_thai'] == pytest.approx((0, .2))
    conn = store.connect(db)
    try:
        assert store.get_last_passing_eval(conn).id == baseline_id
        latest = max(store.list_eval_runs(conn), key=lambda row: row.id)
        assert latest.gate_status == 'unresolved' and not latest.passed
        assert latest.baseline_eval_id == baseline_id
    finally:
        conn.close()
