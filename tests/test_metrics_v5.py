"""Metrics v5: cer_thai substitution/deletion/insertion breakdown and the robustness spread.

Run: python -m pytest tests/test_metrics_v5.py -v
"""
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.db import store
from transcribe.eval import robustness as robust
from transcribe.eval.metrics import METRICS_VERSION, EvalMetrics, _edit_counts_py, compute_metrics


def _tok(text, start=0, end=1000):
    return {"text": text, "script": "thai", "start_ms": start, "end_ms": end}


def test_version_bumped():
    assert METRICS_VERSION == 5


@pytest.mark.parametrize("ref,hyp,expected", [
    ("กขคง", "กขคง", (0, 0, 0)),
    ("กขคง", "กxคง", (1, 0, 0)),
    ("กขคง", "กคง", (0, 1, 0)),
    ("กขคง", "กขยคง", (0, 0, 1)),
    ("กขคง", "", (0, 4, 0)),
])
def test_breakdown_counts_each_kind(ref, hyp, expected):
    m = compute_metrics([_tok(ref)], [_tok(hyp.replace("x", "จ"))])
    assert (m.thai_sub, m.thai_del, m.thai_ins) == expected


def test_breakdown_sums_to_the_error_rate():
    m = compute_metrics([_tok("สวัสดีครับวันนี้อากาศดี")], [_tok("สวัดีคับวันนนี้อากาดดี")])
    assert (m.thai_sub + m.thai_del + m.thai_ins) / m.thai_chars == pytest.approx(m.cer_thai)


def test_pure_python_breakdown_matches_the_distance():
    ref, hyp = "สวัสดีครับวันนี้", "สวัดีคับวันนนี้"
    assert sum(_edit_counts_py(ref, hyp)) == sum(compute_metrics([_tok(ref)], [_tok(hyp)]).__dict__[k]
                                                 for k in ("thai_sub", "thai_del", "thai_ins"))


def test_breakdown_aggregates_as_sums():
    a = EvalMetrics(0, 0, 0, 0, 10, 0, 0, 0, thai_sub=1, thai_del=2, thai_ins=0)
    b = EvalMetrics(0, 0, 0, 0, 10, 0, 0, 0, thai_sub=0, thai_del=1, thai_ins=3)
    agg = EvalMetrics.aggregate([a, b])
    assert (agg.thai_sub, agg.thai_del, agg.thai_ins) == (1, 3, 3)


# ── perturbation ────────────────────────────────────────────────────────────

def _speech(n=16000):
    t = np.arange(n) / 16000
    return (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def test_gain_scales_and_hot_gain_clips():
    audio = _speech()
    quiet = robust.perturb(audio, 16000, robust.Condition("q", gain_db=-6.0))
    assert np.max(np.abs(quiet)) == pytest.approx(0.1 * 10 ** (-6 / 20), rel=1e-3)
    hot = robust.perturb(audio * 9, 16000, robust.Condition("h", gain_db=6.0))
    assert np.max(np.abs(hot)) == pytest.approx(1.0)


def test_noise_lands_at_the_requested_snr():
    audio = _speech(32000)
    noisy = robust.perturb(audio, 16000, robust.Condition("n", noise_snr_db=10.0))
    noise = noisy - audio
    snr = 20 * np.log10(np.sqrt(np.mean(audio ** 2)) / np.sqrt(np.mean(noise ** 2)))
    assert snr == pytest.approx(10.0, abs=0.1)


def test_music_condition_needs_a_bed():
    with pytest.raises(ValueError):
        robust.perturb(_speech(), 16000, robust.Condition("m", music_snr_db=10.0))


def test_spread_is_worst_minus_best_condition():
    def clip(cer):
        return EvalMetrics(cer, 0, 0, 0, 100, 0, 0, 0)
    by_cond = {"clean": [clip(0.1), clip(0.1)], "noise": [clip(0.3), clip(0.1)]}
    assert robust.cer_thai_spread(by_cond) == pytest.approx(0.1)
    lo, hi = robust.paired_bootstrap_ci(by_cond, by_cond, "cer_thai_spread")
    assert lo == hi == 0.0


# ── harness ─────────────────────────────────────────────────────────────────

def _robust_setup(monkeypatch, tmp_path):
    import soundfile as sf
    from transcribe.eval import harness
    wav = tmp_path / "clip.wav"
    sf.write(str(wav), _speech(32000), 16000)
    music = tmp_path / "bed.wav"
    sf.write(str(music), _speech(8000) * 3, 16000)
    ref = [_tok("สวัสดีครับ", 0, 1000)]
    monkeypatch.setattr(harness, "_load_goldenset", lambda: [(wav, ref)])
    monkeypatch.setattr(harness, "_audio_duration_s", lambda p: 2.0)

    def pipeline(path, cfg):
        import soundfile as sf
        audio, _ = sf.read(str(path))
        quiet = np.max(np.abs(audio)) < 0.02
        return [_tok("สวัสดี" if quiet else "สวัสดีครับ", 0, 1000)]

    cfg = {"regression_tolerance": 0.02, "regression_abs_floor": 0.005,
           "eval_robustness": {"music_bed": str(music)}}
    return harness, cfg, pipeline


def test_robustness_run_records_spread_under_its_own_kind(monkeypatch, tmp_path):
    harness, cfg, pipeline = _robust_setup(monkeypatch, tmp_path)
    db = Path(tempfile.mkdtemp()) / "t.db"
    first = harness.run_harness(cfg, db, pipeline_fn=pipeline, robustness=True)
    assert first is not None and first.passed
    conn = store.connect(db)
    row = store.get_last_passing_eval(conn, kind="robustness")
    assert row is not None and row.kind == "robustness"
    assert row.cer_thai_spread == pytest.approx(0.4)  # gain-18 drops "ครับ" (4 of 10 chars)
    assert store.get_last_passing_eval(conn) is None, "a robustness run is never a transcribe baseline"
    assert len(store.get_eval_clip_metrics(conn, row.id)) == len(robust.CONDITIONS)
    conn.close()

    second = harness.run_harness(cfg, db, pipeline_fn=pipeline, robustness=True)
    assert second.baseline is not None and second.baseline.id == row.id
    assert second.paired_ci["cer_thai_spread"] == (0.0, 0.0)
    assert second.status == "pass"
