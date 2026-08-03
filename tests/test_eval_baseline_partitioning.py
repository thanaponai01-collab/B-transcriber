"""Regression-baseline partitioning: an A/B experiment run's pass must never
become the baseline a subsequent production run is compared against.

The failure mode this pins: `harness --engine-b X` (or --llm-enabled) writes a
passing eval_run for a config that is NOT config.yaml. If get_last_passing_eval
returned it, the next production run would be gated against the experiment's
(possibly better) numbers and could fail — or worse, silently drift the baseline
lineage. Experiment runs are recorded with is_experiment=1, judged against the
production baseline, and excluded from ever becoming it.

Run: python -m pytest tests/test_eval_baseline_partitioning.py -v
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.db import store
from transcribe.eval import harness


def _tmp_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    db = Path(f.name)
    store.init_db(db)
    return db


# ── store level ────────────────────────────────────────────────────────────────

def test_experiment_run_is_never_the_baseline():
    db = _tmp_db()
    conn = store.connect(db)
    store.create_eval_run(conn, "prod", 0.5, 0.5, True, cer_thai=0.10, wer_latin=0.10,
                          engine_pair="faster_whisper+passthrough")
    # A later, better-scoring experiment on a different engine pair passes...
    store.create_eval_run(conn, "exp", 0.0, 0.0, True, cer_thai=0.0, wer_latin=0.0,
                          engine_pair="faster_whisper+funasr", is_experiment=True)
    last = store.get_last_passing_eval(conn)
    # ...but the baseline is still the production run.
    assert last is not None
    assert last.engine_pair == "faster_whisper+passthrough"
    assert abs(last.cer_thai - 0.10) < 1e-9
    assert last.is_experiment is False
    # The experiment row itself was still recorded (just excluded from baselines).
    runs = store.list_eval_runs(conn)
    assert any(r.is_experiment for r in runs)
    conn.close()


# ── harness level: baseline → passing experiment → production re-run ──────────

_REF = [{"text": "กขคง", "script": "thai", "start_ms": 0}]


def _hyp_fn(text):
    """pipeline_fn returning a fixed hypothesis, ignoring audio/config."""
    return lambda audio_path, cfg: [{"text": text, "script": "thai", "start_ms": 0}]


def test_production_baseline_survives_a_passing_experiment(monkeypatch):
    monkeypatch.setattr(harness, "_load_goldenset", lambda: [(Path("fake.wav"), _REF)])
    db = _tmp_db()

    prod_cfg = {"engine_a": "faster_whisper", "engine_b": "passthrough",
                "regression_tolerance": 0.02}
    exp_cfg = {**prod_cfg, "engine_b": "funasr"}

    # 1. Normal production baseline: 1 of 4 Thai chars wrong → cer_thai = 0.25.
    r1 = harness.run_harness(prod_cfg, db, pipeline_fn=_hyp_fn("กขคด"))
    assert r1 is not None and r1.passed and r1.baseline is None
    assert abs(r1.metrics.cer_thai - 0.25) < 1e-9

    # 2. A/B experiment on a different engine_pair scores PERFECTLY and passes.
    #    It is judged against the production baseline...
    r2 = harness.run_harness(exp_cfg, db, pipeline_fn=_hyp_fn("กขคง"), experiment=True)
    assert r2 is not None and r2.passed
    assert r2.baseline is not None and abs(r2.baseline.cer_thai - 0.25) < 1e-9
    assert abs(r2.metrics.cer_thai - 0.0) < 1e-9

    # 3. ...so re-running the normal config must still be compared against the
    #    ORIGINAL 0.25 baseline, not the experiment's 0.0 — 0.25 vs 0.0 would
    #    trip the gate and fail a production run that changed nothing.
    r3 = harness.run_harness(prod_cfg, db, pipeline_fn=_hyp_fn("กขคด"))
    assert r3 is not None
    assert r3.baseline is not None, "production baseline lost"
    assert abs(r3.baseline.cer_thai - 0.25) < 1e-9, (
        "experiment run leaked into the production baseline"
    )
    assert r3.passed, "unchanged production config failed its own baseline"

    # The recorded baseline lineage stays production-only.
    conn = store.connect(db)
    last = store.get_last_passing_eval(conn)
    assert last.engine_pair == "faster_whisper+passthrough"
    assert last.is_experiment is False
    conn.close()
