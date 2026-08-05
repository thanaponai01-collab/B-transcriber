"""Phase A acceptance — bootstrap CIs, RTF, and the CI-gated "unresolved" verdict
(HANDOFF_ONE_ENGINE.md §3, "make the gate trustworthy at 1% margins").

Why this exists: every regression verdict before this phase compared two
single point estimates, with no way to tell a real 1% move from run-to-run
resampling noise on an 8-clip corpus — several standing rejections (TODO_LEDGER
2026-08-04/05) were decided by margins the handoffs themselves flagged as
smaller than that noise. This promotes a clip-level percentile bootstrap to a
first-class, stored signal and softens a point-estimate regression to
"unresolved" (not a hard fail) whenever the run's own 95% CI still contains
the baseline value.

Run: python -m pytest tests/test_phase_a_ci.py -v
"""

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.db import store
from transcribe.eval.metrics import CI_METRICS, EvalMetrics, bootstrap_ci


def _tmp_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    db = Path(f.name)
    store.init_db(db)
    return db


def _synth_wav(dirpath: Path, stem="clip", seconds=0.5):
    import soundfile as sf
    t = np.linspace(0, seconds, int(16000 * seconds), endpoint=False)
    p = dirpath / f"{stem}.wav"
    sf.write(p, (0.2 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), 16000)
    return p


# ── bootstrap_ci: unit-level ───────────────────────────────────────────────────

def _clip(cer_thai=0.0, thai_chars=0):
    return EvalMetrics(
        cer_thai=cer_thai, wer_latin=0.0, boundary_error_rate=0.0, wer=0.0,
        thai_chars=thai_chars, latin_words=0, total_words=0, ref_switches=0,
    )


def test_bootstrap_ci_degenerates_to_point_estimate_on_one_clip():
    # A single-clip corpus can only ever resample itself — the CI must
    # collapse to exactly that clip's value, for every gated metric.
    clips = [_clip(cer_thai=0.37, thai_chars=100)]
    lo, hi = bootstrap_ci(clips, "cer_thai")
    assert lo == hi == 0.37


def test_bootstrap_ci_is_seeded_reproducible():
    clips = [_clip(cer_thai=0.1, thai_chars=100), _clip(cer_thai=0.3, thai_chars=100)]
    a = bootstrap_ci(clips, "cer_thai", seed=0)
    b = bootstrap_ci(clips, "cer_thai", seed=0)
    assert a == b


def test_bootstrap_ci_bounds_are_ordered_and_span_all_metrics():
    clips = [
        EvalMetrics(cer_thai=0.1, wer_latin=0.2, boundary_error_rate=0.3, wer=0.1,
                    thai_chars=50, latin_words=10, total_words=20, ref_switches=4,
                    hyp_switches=3, matched_switches=2, cue_boundary_error_rate=0.4,
                    ref_cues=8, hyp_cues=7, matched_cues=5),
        EvalMetrics(cer_thai=0.2, wer_latin=0.4, boundary_error_rate=0.5, wer=0.2,
                    thai_chars=80, latin_words=15, total_words=30, ref_switches=6,
                    hyp_switches=5, matched_switches=3, cue_boundary_error_rate=0.6,
                    ref_cues=12, hyp_cues=10, matched_cues=6),
    ]
    for name in CI_METRICS:
        lo, hi = bootstrap_ci(clips, name)
        assert lo <= hi


def test_bootstrap_ci_empty_corpus_is_zero_zero():
    assert bootstrap_ci([], "cer_thai") == (0.0, 0.0)


# ── harness: CI/RTF columns land on eval_run ──────────────────────────────────

def test_harness_records_ci_and_rtf_on_eval_run(monkeypatch, tmp_path):
    from transcribe.eval import harness

    audio = _synth_wav(tmp_path)
    ref = [{"text": "สวัสดี", "script": "thai", "start_ms": 0, "end_ms": 500}]
    monkeypatch.setattr(harness, "_load_goldenset", lambda: [(audio, ref)])

    db = _tmp_db()
    result = harness.run_harness(
        {"regression_tolerance": 0.02, "regression_abs_floor": 0.005},
        db, pipeline_fn=lambda p, c: ref,
    )
    assert result is not None and result.passed
    assert result.rtf is not None and result.rtf >= 0.0
    assert result.ci is not None and set(result.ci) == set(CI_METRICS)

    conn = store.connect(db)
    last = store.get_last_passing_eval(conn)
    assert last.rtf is not None
    assert last.cer_thai_ci_lo == 0.0 and last.cer_thai_ci_hi == 0.0  # perfect match, 1 clip
    assert last.gate_unresolved is None
    conn.close()


def test_harness_rtf_is_none_when_audio_cannot_be_duration_probed(monkeypatch):
    # Mirrors the synthetic Path("fake.wav") fixtures every other harness test
    # uses — _audio_duration_s must swallow the failure, not crash the run.
    from transcribe.eval import harness

    ref = [{"text": "สวัสดี", "script": "thai", "start_ms": 0}]
    monkeypatch.setattr(harness, "_load_goldenset", lambda: [(Path("fake.wav"), ref)])
    db = _tmp_db()
    result = harness.run_harness(
        {"regression_tolerance": 0.02, "regression_abs_floor": 0.005},
        db, pipeline_fn=lambda p, c: ref,
    )
    assert result is not None
    assert result.rtf is None


# ── harness: unresolved vs. confirmed regression ───────────────────────────────

def test_regression_inside_bootstrap_ci_is_recorded_unresolved_not_failed(monkeypatch):
    """3-clip corpus, each clip's OWN cer_thai fixed at 0.10, 0.10, 0.30 (100
    Thai chars each). Corpus point estimate is 0.1667 — past the regression
    band vs. a 0.10 baseline — but this run's own bootstrap CI is
    [0.10, 0.2333] (verified directly against metrics.bootstrap_ci with this
    exact per-clip distribution): it still contains the baseline, so this
    must NOT hard-fail; it must be recorded unresolved instead."""
    from transcribe.eval import harness

    hyp_by_name = {
        "fake1.wav": "ก" * 90 + "ข" * 10,   # cer_thai = 0.10
        "fake2.wav": "ค" * 90 + "ง" * 10,   # cer_thai = 0.10
        "fake3.wav": "จ" * 70 + "ฉ" * 30,   # cer_thai = 0.30
    }
    ref_by_name = {
        "fake1.wav": "ก" * 100,
        "fake2.wav": "ค" * 100,
        "fake3.wav": "จ" * 100,
    }
    refs = [
        (Path(name), [{"text": text, "script": "thai", "start_ms": 0, "end_ms": 900}])
        for name, text in ref_by_name.items()
    ]
    monkeypatch.setattr(harness, "_load_goldenset", lambda: refs)

    def hyp_fn(path, cfg):
        return [{"text": hyp_by_name[path.name], "script": "thai", "start_ms": 0, "end_ms": 900}]

    db = _tmp_db()
    conn = store.connect(db)
    store.create_eval_run(conn, "baseline", 0.0, 0.0, True, cer_thai=0.10, wer_latin=0.0)
    conn.close()

    result = harness.run_harness(
        {"regression_tolerance": 0.02, "regression_abs_floor": 0.005},
        db, pipeline_fn=hyp_fn,
    )
    assert result is not None
    assert abs(result.metrics.cer_thai - 1.0 / 6) < 1e-6  # 0.1667, past the 0.02/0.005 band
    assert result.passed, "baseline is within this run's own CI - must not hard-fail"
    assert result.unresolved and any(m.startswith("CER_thai") for m in result.unresolved)

    conn = store.connect(db)
    last_run = store.get_last_passing_eval(conn)  # unresolved still passes
    assert last_run.gate_unresolved == "cer_thai"
    conn.close()
