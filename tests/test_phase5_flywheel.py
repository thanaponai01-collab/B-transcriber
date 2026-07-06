"""Phase 5 acceptance — flywheel correctness.

Run: python -m pytest tests/test_phase5_flywheel.py -v
"""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.db import store


def _tmp_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    db = Path(f.name)
    store.init_db(db)
    return db


# ── 5.2 regression gate is the harness's job and never self-compares ──────────

def test_harness_blocks_regression_vs_prior_baseline(monkeypatch):
    from transcribe.eval import harness

    db = _tmp_db()
    conn = store.connect(db)
    # A good passing baseline: low Thai CER.
    store.create_eval_run(conn, "cfg", 0.0, 0.0, True, cer_thai=0.05, wer_latin=0.0)
    conn.close()

    ref = [{"text": "สวัสดีครับ", "script": "thai", "start_ms": 0}]
    monkeypatch.setattr(harness, "_load_goldenset", lambda: [(Path("fake.wav"), ref)])
    # Hypothesis drops all Thai → cer_thai = 1.0, a massive regression.
    bad = lambda a, c: [{"text": "", "script": "thai", "start_ms": 0}]

    cfg = {"regression_tolerance": 0.02, "regression_abs_floor": 0.005}
    result = harness.run_harness(cfg, db, pipeline_fn=bad)

    assert result is not None
    assert not result.passed, "regression vs the 0.05 baseline must fail the gate"
    # If it had compared the new run against ITSELF, 1.0 vs 1.0 would have passed.
    assert abs(result.baseline.cer_thai - 0.05) < 1e-9
    # The failed run must not become the new passing baseline.
    conn = store.connect(db)
    assert abs(store.get_last_passing_eval(conn).cer_thai - 0.05) < 1e-9
    conn.close()


def test_two_passing_runs_do_not_compare_against_self(monkeypatch):
    from transcribe.eval import harness

    db = _tmp_db()
    ref = [{"text": "hello", "script": "latin", "start_ms": 0}]
    monkeypatch.setattr(harness, "_load_goldenset", lambda: [(Path("fake.wav"), ref)])
    perfect = lambda a, c: [{"text": "hello", "script": "latin", "start_ms": 0}]
    cfg = {"regression_tolerance": 0.02, "regression_abs_floor": 0.005}

    r1 = harness.run_harness(cfg, db, pipeline_fn=perfect)
    assert r1.passed and r1.baseline is None      # first run: no prior baseline
    r2 = harness.run_harness(cfg, db, pipeline_fn=perfect)
    assert r2.passed and r2.baseline is not None   # second run reads run1, not itself


def test_biasindex_rolls_back_when_gate_fails(monkeypatch):
    from transcribe.flywheel import biasindex
    from transcribe.eval.harness import HarnessResult
    from transcribe.eval.metrics import EvalMetrics

    db = _tmp_db()
    conn = store.connect(db)
    media_id = store.create_media(conn, __file__, 1000)
    job_id = store.create_job(conn, media_id, "faster_whisper", "passthrough", "1.0")
    # 3 corrections of the same span by the active engine → crosses min_occurrences.
    for i in range(3):
        store.create_correction(
            conn, job_id, i, "ChatGBT", "…ChatGPT…", "faster_whisper",
            corrected_span="ChatGPT",
        )
    conn.commit()

    # Force the gate to fail without touching a real pipeline/GPU.
    fail = HarnessResult(metrics=EvalMetrics(1, 0, 0, 0, 1, 0, 0, 0), passed=False, baseline=None)
    monkeypatch.setattr("transcribe.eval.harness.run_harness", lambda *a, **k: fail)

    with pytest.raises(RuntimeError):
        biasindex.update_bias_index(
            conn, active_engines=["faster_whisper"],
            eval_config={"regression_tolerance": 0.02}, db_path=db,
            run_regression_gate=True,
        )
    # The promoted term must be rolled back.
    assert "ChatGPT" not in store.get_bias_term_strings(conn)
    conn.close()


# ── 5.3 sub-cue correction diffing ────────────────────────────────────────────

def test_diff_extracts_minimal_span_not_whole_cue():
    from transcribe.flywheel.diff import diff_corrections

    orig = [{"idx": 0, "text": "วันนี้เราจะพูดถึง ChatGBT กันครับ", "source_engine": "a"}]
    corr = [{"idx": 0, "text": "วันนี้เราจะพูดถึง ChatGPT กันครับ"}]
    pairs = diff_corrections(orig, corr)
    assert len(pairs) == 1
    assert pairs[0].corrected_span == "ChatGPT"          # the word, not the sentence
    assert pairs[0].corrected_text.startswith("วันนี้")  # full cue kept for audit


def test_short_correction_keeps_full_text_as_span():
    from transcribe.flywheel.diff import diff_corrections
    pairs = diff_corrections(
        [{"idx": 0, "text": "ครับ", "source_engine": "a"}],
        [{"idx": 0, "text": "คะ"}],
    )
    assert pairs[0].corrected_span == "คะ"


def test_biasindex_refuses_sentence_length_terms():
    from transcribe.flywheel.biasindex import _too_long_to_promote
    assert _too_long_to_promote("this is a whole sentence with far too many words in it")
    assert _too_long_to_promote("ก" * 40)
    assert not _too_long_to_promote("ChatGPT")


def test_correction_counts_group_by_span():
    db = _tmp_db()
    conn = store.connect(db)
    media_id = store.create_media(conn, __file__, 1000)
    job_id = store.create_job(conn, media_id, "a", "b", "1.0")
    # Two different cues, same corrected span → must aggregate as one term.
    store.create_correction(conn, job_id, 0, "raw one", "cue one ChatGPT here",
                            "a", corrected_span="ChatGPT")
    store.create_correction(conn, job_id, 1, "raw two", "totally other cue ChatGPT",
                            "a", corrected_span="ChatGPT")
    conn.commit()
    counts = dict((t, n) for t, _e, n in store.get_correction_counts(conn))
    assert counts.get("ChatGPT") == 2
    conn.close()


# ── 5.1 weighted budgeted bias injection ──────────────────────────────────────

def test_build_prompt_ranks_by_weight():
    from transcribe.flywheel.inject import build_prompt, BiasTerm
    terms = [BiasTerm("low", 0.1), BiasTerm("high", 9.0), BiasTerm("mid", 1.0)]
    # Budget for ~2 tokens → the two highest-weight terms, highest first.
    out = build_prompt(terms, budget_tokens=2).split()
    assert out[0] == "high"
    assert "low" not in out


def test_store_returns_bias_weights():
    db = _tmp_db()
    conn = store.connect(db)
    store.upsert_bias_term(conn, "ChatGPT", "brand", "latin", "manual", weight=3.0)
    weights = store.get_bias_term_weights(conn)
    assert weights["ChatGPT"] == 3.0
    conn.close()
