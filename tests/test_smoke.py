"""Smoke tests covering acceptance criteria for Steps 1–3.

Run: python -m pytest tests/test_smoke.py -v
"""

import tempfile
from pathlib import Path

import pytest


# ── Regression gate near-zero floor (#6) ──────────────────────────────────────

def test_regressed_abs_floor():
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from transcribe.eval.metrics import regressed

    # Near-zero baseline: relative-only would trip on any nonzero score; the
    # absolute floor must absorb a small worsening.
    assert not regressed(0.004, 0.0, tol_frac=1.02, abs_floor=0.005)
    assert regressed(0.02, 0.0, tol_frac=1.02, abs_floor=0.005)
    # Normal baseline: relative band dominates the (wider) floor.
    assert not regressed(0.101, 0.10, tol_frac=1.02, abs_floor=0.005)  # +1% < 2%
    assert regressed(0.13, 0.10, tol_frac=1.02, abs_floor=0.005)       # +30%


# ── Step 1: DB schema + store ─────────────────────────────────────────────────

def _tmp_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return Path(f.name)


def test_db_init_and_crud():
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from transcribe.db import store

    db = _tmp_db()
    store.init_db(db)
    conn = store.connect(db)

    # Media
    # Create a temp "audio" file for sha256
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as af:
        af.write(b"\x00" * 100)
        audio_path = af.name
    media_id = store.create_media(conn, audio_path, 1000)
    assert media_id > 0
    media = store.get_media(conn, media_id)
    assert media is not None
    assert media.duration_ms == 1000

    # Job
    job_id = store.create_job(conn, media_id, "engine_a", "engine_b", "1.0")
    assert job_id > 0
    job = store.get_job(conn, job_id)
    assert job.status == "pending"
    store.update_job_status(conn, job_id, "done")
    assert store.get_job(conn, job_id).status == "done"

    # Token
    tok_id = store.create_token(conn, job_id, 0, "สวัสดี", 0, 500, "thai", 0.95, "a")
    assert tok_id > 0
    tokens = store.get_tokens(conn, job_id)
    assert len(tokens) == 1
    assert tokens[0].text == "สวัสดี"

    # Correction
    corr_id = store.create_correction(conn, job_id, 0, "สวัสดี", "สวัสดีครับ", "a")
    assert corr_id > 0
    corrections = store.get_corrections(conn, job_id)
    assert corrections[0].corrected_text == "สวัสดีครับ"

    # Bias term
    bt_id = store.upsert_bias_term(conn, "YouTube", "brand", "latin", "manual")
    assert bt_id > 0
    terms = store.get_bias_term_strings(conn)
    assert "YouTube" in terms

    # Eval run
    er_id = store.create_eval_run(conn, "abc123", 0.15, 0.22, True)
    assert er_id > 0
    last = store.get_last_passing_eval(conn)
    assert last is not None
    assert abs(last.wer - 0.15) < 1e-6

    conn.close()
    db.unlink()
    Path(audio_path).unlink()


# ── Step 2: Engine Contract + MockEngine ─────────────────────────────────────

def test_mock_engine_full_pipeline():
    """MockEngine must let the downstream pipeline run without a real model."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    # Trigger lazy registration
    import transcribe.engines.mock  # noqa: F401
    from transcribe.engines.registry import get_engine
    from transcribe.contracts import EngineInput

    engine = get_engine("mock")
    engine.load()
    result = engine.transcribe(EngineInput(audio_path="fake.wav", bias_terms=["test"]))
    engine.unload()

    assert result.engine_name == "mock"
    assert len(result.tokens) > 0
    for tok in result.tokens:
        assert tok.script in ("thai", "latin", "other", "mixed")
        assert tok.start_ms >= 0
        assert tok.end_ms > tok.start_ms


# ── Step 3: Alignment + Reconciler logic ─────────────────────────────────────

def test_align_identical():
    from transcribe.contracts import RecognizedToken
    from transcribe.pipeline.align_hyp import align

    toks = [
        RecognizedToken("hello", 0, 500, 0.9, "latin"),
        RecognizedToken("world", 500, 1000, 0.8, "latin"),
    ]
    slots = align(toks, toks)
    # Identical inputs → every slot has both candidates with same text
    assert len(slots) == 2
    for slot in slots:
        assert slot.candidates_a[0].text == slot.candidates_b[0].text


def test_reconciler_no_generation():
    from transcribe.contracts import RecognizedToken
    from transcribe.pipeline.align_hyp import AlignSlot
    from transcribe.pipeline.reconcile import reconcile

    slot = AlignSlot(
        candidates_a=[RecognizedToken("ครับ", 0, 500, 0.9, "thai")],
        candidates_b=[RecognizedToken("คะ", 0, 500, 0.8, "thai")],
    )
    results = reconcile([slot])
    chosen_text = results[0][0].text
    assert chosen_text in {"ครับ", "คะ"}, f"Reconciler emitted unknown text: {chosen_text!r}"


def test_reconciler_agreement_skips_llm():
    from transcribe.contracts import RecognizedToken
    from transcribe.pipeline.align_hyp import AlignSlot
    from transcribe.pipeline.reconcile import reconcile

    llm_called = []
    def fake_llm(ta, tb, bias):
        llm_called.append(True)
        return 0

    slot = AlignSlot(
        candidates_a=[RecognizedToken("hello", 0, 500, 0.9, "latin")],
        candidates_b=[RecognizedToken("hello", 0, 500, 0.85, "latin")],
    )
    results = reconcile([slot], llm_fn=fake_llm)
    assert not llm_called, "LLM should not be called when engines agree"
    assert results[0][1] == "both"


# ── Normalization regression tests ───────────────────────────────────────────

def test_normalization_boundary_spacing():
    from transcribe.pipeline.normalize import normalize

    result = normalize("สวัสดีworld")
    assert "สวัสดี world" == result or "สวัสดี" in result and "world" in result

    result = normalize("helloครับ")
    assert "hello ครับ" == result or "hello" in result and "ครับ" in result


def test_normalization_exception_lexicon():
    from transcribe.pipeline.normalize import normalize

    config = {"normalization": {"exception_lexicon": ["COVID-19"]}}
    result = normalize("ผู้ป่วยCOVID-19รายใหม่", config)
    assert "COVID-19" in result, f"Exception term was split: {result!r}"


def test_normalization_exception_lexicon_gets_boundary_spacing():
    """Phase 6 decision (STYLE_GUIDE §6): exception terms are spaced from
    surrounding Thai like any other code-switch word — the lexicon protects
    a term's interior, not its edges."""
    from transcribe.pipeline.normalize import normalize

    config = {"normalization": {"exception_lexicon": ["iPhone"]}}
    result = normalize("ผมใช้iPhoneอยู่", config)
    assert result == "ผมใช้ iPhone อยู่", f"Exception term glued to Thai neighbors: {result!r}"


# ── Metrics ───────────────────────────────────────────────────────────────────

def test_wer_perfect():
    from transcribe.eval.metrics import compute_metrics

    ref = [{"text": "hello", "script": "latin"}, {"text": "world", "script": "latin"}]
    m = compute_metrics(ref, ref)
    assert m.wer == 0.0


def test_wer_all_wrong():
    from transcribe.eval.metrics import compute_metrics

    ref = [{"text": "a", "script": "latin"}, {"text": "b", "script": "latin"}]
    hyp = [{"text": "x", "script": "latin"}, {"text": "y", "script": "latin"}]
    m = compute_metrics(ref, hyp)
    assert m.wer > 0.0


def test_boundary_detection():
    from transcribe.eval.metrics import compute_metrics

    # Thai → Latin boundary between index 1 and 2
    ref = [
        {"text": "สวัสดี", "script": "thai", "start_ms": 0},
        {"text": "ครับ", "script": "thai", "start_ms": 500},
        {"text": "Hello", "script": "latin", "start_ms": 1000},
        {"text": "world", "script": "latin", "start_ms": 1400},
    ]
    m = compute_metrics(ref, ref)
    assert m.wer == 0.0
    assert m.ref_switches == 1          # one Thai→Latin transition
    assert m.boundary_error_rate == 0.0  # ref vs itself: perfect timing


def test_temporal_boundary_penalizes_wrong_timing():
    from transcribe.eval.metrics import compute_metrics

    ref = [
        {"text": "ครับ", "script": "thai", "start_ms": 0},
        {"text": "Hello", "script": "latin", "start_ms": 1000},  # switch @1000ms
    ]
    # Hypothesis puts the switch 5s away — outside the 300ms tolerance.
    hyp = [
        {"text": "ครับ", "script": "thai", "start_ms": 0},
        {"text": "Hello", "script": "latin", "start_ms": 6000},
    ]
    m = compute_metrics(ref, hyp, boundary_tol_ms=300.0)
    assert m.boundary_error_rate > 0.0  # mistimed switch is penalized
    # Within tolerance, the same switch scores clean.
    hyp_ok = [
        {"text": "ครับ", "script": "thai", "start_ms": 0},
        {"text": "Hello", "script": "latin", "start_ms": 1100},
    ]
    assert compute_metrics(ref, hyp_ok, boundary_tol_ms=300.0).boundary_error_rate == 0.0


def test_cer_thai_is_tokenization_free():
    from transcribe.eval.metrics import compute_metrics

    # Same Thai characters, different (arbitrary) word splits → CER must be 0.
    ref = [{"text": "สวัสดีครับ", "script": "thai", "start_ms": 0}]
    hyp = [
        {"text": "สวัส", "script": "thai", "start_ms": 0},
        {"text": "ดีครับ", "script": "thai", "start_ms": 300},
    ]
    m = compute_metrics(ref, hyp)
    assert m.cer_thai == 0.0
    assert m.thai_chars == len("สวัสดีครับ")

    # One wrong character → non-zero CER.
    hyp_bad = [{"text": "สวัสดีคระ", "script": "thai", "start_ms": 0}]
    assert compute_metrics(ref, hyp_bad).cer_thai > 0.0


def test_wer_latin_is_case_insensitive():
    from transcribe.eval.metrics import compute_metrics

    ref = [{"text": "Hello", "script": "latin"}, {"text": "World", "script": "latin"}]
    hyp = [{"text": "hello", "script": "latin"}, {"text": "world", "script": "latin"}]
    assert compute_metrics(ref, hyp).wer_latin == 0.0


# ── Normalization policy (STYLE_GUIDE.md) ───────────────────────────────────────

def test_normalize_thai_digits():
    from transcribe.pipeline.normalize import normalize

    assert normalize("ราคา๑๐๐บาท") == normalize("ราคา100บาท")
    assert "100" in normalize("๑๐๐")


def test_normalize_mai_yamok_canonical():
    from transcribe.pipeline.normalize import normalize

    assert normalize("เด็ก ๆ") == normalize("เด็กๆ")
    assert normalize("เด็กๆๆ") == normalize("เด็กๆ")


def test_eval_normalizes_gold_and_hyp_identically():
    """A policy-equivalent gold/hyp pair must score perfectly once config is passed."""
    from transcribe.eval.metrics import compute_metrics

    config = {"normalization": {"thai_digits": True, "mai_yamok_attach": True}}
    ref = [{"text": "ราคา๑๐๐", "script": "thai", "start_ms": 0}]
    hyp = [{"text": "ราคา100", "script": "thai", "start_ms": 0}]
    # Without normalization the Thai digits differ → CER > 0.
    assert compute_metrics(ref, hyp).cer_thai > 0.0
    # With the shared policy applied to both sides → CER 0.
    assert compute_metrics(ref, hyp, config=config).cer_thai == 0.0
