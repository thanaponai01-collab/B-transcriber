"""Phase 1 acceptance — stop silent corruption.

Run: python -m pytest tests/test_phase1_robustness.py -v
"""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── 1.1 Loop-collapse must not corrupt real text ─────────────────────────────

@pytest.mark.parametrize("text", [
    "2000",          # any digit repeated 3+ — must survive
    "555",           # Thai laughter, extremely common
    "0812345555",    # phone number
    "www",           # 1-char unit ×3 — under the ≤2-char threshold of 5
    "100",
    "ababab",        # 2-char unit ×3 — under the ≤2-char threshold of 5
])
def test_collapse_loops_preserves_real_text(text):
    from transcribe.pipeline.run import _collapse_loops
    assert _collapse_loops(text) == text


@pytest.mark.parametrize("looped,collapsed", [
    ("ฮือฮือฮือฮือฮือ", "ฮือ"),        # 3-char unit ×5 → genuine Whisper loop
    ("นะนะนะนะนะนะ", "นะ"),            # 2-char unit ×6 → over the 5 threshold
    ("wwwww", "w"),                    # 1-char unit ×5 → over the 5 threshold
])
def test_collapse_loops_kills_real_loops(looped, collapsed):
    from transcribe.pipeline.run import _collapse_loops
    assert _collapse_loops(looped) == collapsed


def test_collapse_loops_logs_at_info(caplog):
    from transcribe.pipeline.run import _collapse_loops
    import logging
    with caplog.at_level(logging.INFO):
        _collapse_loops("ฮือฮือฮือฮือฮือ")
    assert any("Loop-collapse" in r.message for r in caplog.records)


# ── 1.2 Empty gold set must not write an eval_run ─────────────────────────────

def test_empty_goldenset_writes_no_eval_run(monkeypatch):
    from transcribe.db import store
    from transcribe.eval import harness

    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    db = Path(f.name)
    store.init_db(db)

    # Force an empty gold set regardless of what's on disk.
    monkeypatch.setattr(harness, "_load_goldenset", lambda: [])
    # pipeline_fn present so the scratch-DB branch is skipped.
    result = harness.run_harness({"engine_a": "mock", "engine_b": "passthrough"},
                                 db, pipeline_fn=lambda a, c: [])

    assert result is None
    conn = store.connect(db)
    assert store.get_last_passing_eval(conn) is None, "empty gold set poisoned the baseline"
    conn.close()
    db.unlink()


# ── 1.3 Reconciler violation is a real exception, not an assert ───────────────

def test_reconciler_violation_raises_under_optimize():
    # Reproduce a select-only breach by feeding _pick a slot whose chosen text is
    # forced out of the candidate set. We do it through the public raise path.
    from transcribe.contracts import RecognizedToken
    from transcribe.pipeline.align_hyp import AlignSlot
    from transcribe.pipeline import reconcile as R

    # Monkeypatch the fallback to fabricate text no engine proposed.
    slot = AlignSlot(
        candidates_a=[RecognizedToken("ครับ", 0, 500, 0.9, "thai")],
        candidates_b=[RecognizedToken("คะ", 0, 500, 0.8, "thai")],
    )
    orig = R._script_fallback
    R._script_fallback = lambda ta, tb: (RecognizedToken("GENERATED", 0, 500, 0.5, "latin"), "a")
    try:
        with pytest.raises(R.ReconcilerViolation):
            R._pick(slot, bias_terms=[])
    finally:
        R._script_fallback = orig
