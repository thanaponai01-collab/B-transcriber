"""Acceptance tests for the 2026-07 improvement pass (see IMPROVEMENT_PLAN.md).

Each test pins one fixed defect so it cannot regress silently:
  1. eval harness mirrors the live bias index into its scratch DB
  2. corrections upsert per (job, token) — repeated saves never stack duplicates
  3. reverting a token deletes its stale correction (store-level primitive)
  4. empty corrected text is never promoted as a bias term
  5. mai yamok collapses space-separated repeats in one pass
  6. get_last_passing_eval filters by kind and tie-breaks on id

Run: python -m pytest tests/test_improvements_202607.py -v
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.db import store


def _tmp_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    db = Path(f.name)
    store.init_db(db)
    return db


# ── 1. harness bias-index mirroring ───────────────────────────────────────────

def test_harness_scratch_db_receives_live_bias_terms(monkeypatch):
    """The eval pipeline must see the same bias index a real run would see —
    otherwise the flywheel's regression gate measures a prompt-less pipeline."""
    from transcribe.eval import harness

    db = _tmp_db()
    conn = store.connect(db)
    store.upsert_bias_term(conn, "ChatGPT", "brand", "latin", "flywheel", 3.0)
    store.upsert_bias_term(conn, "เทสลา", "brand", "thai", "flywheel", 2.0)
    conn.close()

    ref = [{"text": "hello", "script": "latin", "start_ms": 0}]
    monkeypatch.setattr(harness, "_load_goldenset", lambda: [(Path("fake.wav"), ref)])

    seen_terms: list[list[str]] = []

    def fake_run_file(audio_path, cfg, scratch_db):
        c = store.connect(Path(scratch_db))
        seen_terms.append(store.get_bias_term_strings(c))
        c.close()
        return [{"text": "hello", "script": "latin", "start_ms": 0}]

    # Force the real-pipeline branch (pipeline_fn=None) but stub run_file so no
    # GPU/model is needed — the assertion is about the scratch DB's contents.
    import transcribe.pipeline.run as pipeline_run
    monkeypatch.setattr(pipeline_run, "run_file", fake_run_file)

    result = harness.run_harness({"regression_tolerance": 0.02}, db, pipeline_fn=None)
    assert result is not None and result.passed
    assert seen_terms, "stubbed run_file was never called"
    assert set(seen_terms[0]) == {"ChatGPT", "เทสลา"}, (
        "scratch DB must mirror the live bias index"
    )


# ── 2 + 3. correction upsert and revert ───────────────────────────────────────

def test_repeated_saves_do_not_stack_duplicate_corrections():
    db = _tmp_db()
    conn = store.connect(db)
    media_id = store.create_media(conn, __file__, 1000)
    job_id = store.create_job(conn, media_id, "faster_whisper", "passthrough", "1.0")

    for _ in range(3):  # same edit saved three times
        store.create_correction(
            conn, job_id=job_id, token_idx=0,
            raw_text="ChatGBT", corrected_text="ChatGPT",
            source_engine="a", corrected_span="ChatGPT",
        )

    rows = store.get_corrections(conn, job_id)
    assert len(rows) == 1, "re-saving must replace, not stack"

    counts = store.get_correction_counts(conn)
    assert counts == [("ChatGPT", "a", 1)], (
        "flywheel occurrence count must not be inflated by re-saves"
    )
    conn.close()


def test_refined_save_keeps_only_latest_text():
    db = _tmp_db()
    conn = store.connect(db)
    media_id = store.create_media(conn, __file__, 1000)
    job_id = store.create_job(conn, media_id, "faster_whisper", "passthrough", "1.0")

    store.create_correction(conn, job_id=job_id, token_idx=5,
                            raw_text="ราคา", corrected_text="ราคาส่ง", source_engine="a")
    store.create_correction(conn, job_id=job_id, token_idx=5,
                            raw_text="ราคา", corrected_text="ราคาปลีก", source_engine="a")

    rows = store.get_corrections(conn, job_id)
    assert len(rows) == 1
    assert rows[0].corrected_text == "ราคาปลีก"
    conn.close()


def test_delete_correction_removes_reverted_edit():
    db = _tmp_db()
    conn = store.connect(db)
    media_id = store.create_media(conn, __file__, 1000)
    job_id = store.create_job(conn, media_id, "faster_whisper", "passthrough", "1.0")

    store.create_correction(conn, job_id=job_id, token_idx=2,
                            raw_text="a", corrected_text="b", source_engine="a")
    store.delete_correction(conn, job_id, 2)
    assert store.get_corrections(conn, job_id) == []
    conn.close()


# ── 4. empty terms never promoted ─────────────────────────────────────────────

def test_empty_correction_text_is_not_promoted_to_bias_term():
    from transcribe.flywheel import biasindex

    db = _tmp_db()
    conn = store.connect(db)
    media_id = store.create_media(conn, __file__, 1000)
    # Deleting a hallucinated cue on three different jobs → corrected_text "".
    for i in range(3):
        job_id = store.create_job(conn, media_id, "faster_whisper", "passthrough", "1.0")
        store.create_correction(
            conn, job_id=job_id, token_idx=0,
            raw_text="ขอบคุณครับ ขอบคุณครับ", corrected_text="",
            source_engine="a", corrected_span="",
        )

    terms = biasindex.update_bias_index(
        conn, active_engines=["faster_whisper"], run_regression_gate=False,
    )
    assert "" not in terms
    assert all(t.strip() for t in terms)
    conn.close()


# ── 5. mai yamok space-separated repeats ──────────────────────────────────────

def test_mai_yamok_collapses_spaced_repeats():
    from transcribe.pipeline.normalize import normalize

    assert normalize("เร็ว ๆ ๆ") == "เร็วๆ"
    assert normalize("เร็วๆๆ") == "เร็วๆ"
    assert normalize("เร็ว ๆ") == "เร็วๆ"
    assert normalize("เร็วๆ") == "เร็วๆ"


# ── 6. eval baseline isolation by kind ────────────────────────────────────────

def test_last_passing_eval_ignores_other_kinds():
    db = _tmp_db()
    conn = store.connect(db)
    store.create_eval_run(conn, "cfg", 0.5, 0.5, True, cer_thai=0.10, wer_latin=0.10)
    # A later CutDeck-style run must not become the transcription baseline.
    store.create_eval_run(conn, "cfg", 0.0, 0.0, True, cer_thai=0.0, wer_latin=0.0,
                          kind="cut")
    last = store.get_last_passing_eval(conn)
    assert last is not None
    assert last.kind == "transcribe"
    assert abs(last.cer_thai - 0.10) < 1e-9
    conn.close()


def test_last_passing_eval_tiebreaks_same_second_by_id():
    db = _tmp_db()
    conn = store.connect(db)
    # Two passing runs in the same datetime('now') second: the later insert
    # (higher id) must win.
    store.create_eval_run(conn, "cfg", 0.5, 0.5, True, cer_thai=0.20, wer_latin=0.20)
    store.create_eval_run(conn, "cfg", 0.5, 0.5, True, cer_thai=0.10, wer_latin=0.10)
    last = store.get_last_passing_eval(conn)
    assert abs(last.cer_thai - 0.10) < 1e-9
    conn.close()
