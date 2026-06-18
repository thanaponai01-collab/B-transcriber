"""Phase 0 acceptance tests — the durable transcriber gaps that CutDeck stands on.

Covers GAP-1 (timebase), GAP-3 (VAD persistence + silence filter), GAP-4 (chunk
stitch), GAP-5 (bias prompt budget), GAP-7 (correction.reason), and A.2 (eval_run
attribution). All GPU-free.

Run: python -m pytest tests/test_cutdeck_phase0.py -v
"""

import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _tmp_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return Path(f.name)


# ── GAP-1: timebase round-trip ────────────────────────────────────────────────

# (fps_num, fps_den) for the rates where float fps accumulates drift.
_RATES = [
    (24000, 1001),  # NTSC 24
    (24, 1),        # true 24
    (25, 1),        # PAL
    (30000, 1001),  # NTSC 30
    (30, 1),        # true 30
    (60000, 1001),  # NTSC 60
]


def test_timebase_roundtrip_under_half_frame_over_four_hours():
    from transcribe.timebase import Timebase, frame_to_ms, ms_to_frame

    four_hours_ms = 4 * 60 * 60 * 1000
    for num, den in _RATES:
        tb = Timebase(fps_num=num, fps_den=den)
        half_frame_ms = (1000 * den / num) / 2.0
        # Sample across the whole 4-hour span, including the far end.
        for ms in range(0, four_hours_ms + 1, 1_000_003):  # prime-ish stride
            frame = ms_to_frame(ms, tb)
            back = frame_to_ms(frame, tb)
            # Round-trip ms → frame → ms must stay within half a frame.
            assert abs(back - ms) <= half_frame_ms, (
                f"{num}/{den}: {ms}ms → frame {frame} → {back}ms drifted too far"
            )


def test_timebase_ntsc_flag():
    from transcribe.timebase import Timebase
    assert Timebase(30000, 1001).ntsc is True
    assert Timebase(30, 1).ntsc is False
    assert Timebase(24000, 1001).ntsc is True


def test_timebase_rejects_bad_rate():
    import pytest
    from transcribe.timebase import Timebase
    with pytest.raises(ValueError):
        Timebase(0, 1)


def test_no_decimal_ntsc_fps_literal_in_codebase():
    """GAP-1 grep rule: no decimal NTSC fps literal anywhere in transcribe/."""
    pkg = Path(__file__).parent.parent / "transcribe"
    offenders = []
    pattern = re.compile(r"\b(29\.97|23\.976|59\.94|29\.976)\b")
    for py in pkg.rglob("*.py"):
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{py.name}:{i}: {line.strip()}")
    assert not offenders, "Decimal fps literal found:\n" + "\n".join(offenders)


# ── GAP-3: VAD span timeline + persistence ────────────────────────────────────

def test_build_spans_is_gap_free_and_alternating():
    from transcribe.pipeline.ingest import _build_spans

    sr = 16000
    # Speech from 1s–2s and 3s–4s within a 5s file → silence fills the rest.
    segments = [(1 * sr, 2 * sr), (3 * sr, 4 * sr)]
    spans = _build_spans(segments, total_samples=5 * sr, sr=sr)

    # Contiguous, exhaustive over [0, 5000ms], no gaps or overlaps.
    assert spans[0].start_ms == 0
    assert spans[-1].end_ms == 5000
    for a, b in zip(spans, spans[1:]):
        assert b.start_ms == a.end_ms
        assert a.kind != b.kind  # strictly alternating
    kinds = [s.kind for s in spans]
    assert kinds == ["silence", "speech", "silence", "speech", "silence"]


def test_speech_span_persistence_roundtrip():
    from transcribe.db import store

    db = _tmp_db()
    store.init_db(db)
    conn = store.connect(db)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as af:
        af.write(b"\x00" * 64)
        audio_path = af.name
    media_id = store.create_media(conn, audio_path)
    job_id = store.create_job(conn, media_id, "a", "b", "1.0")

    store.bulk_create_speech_spans(conn, job_id, [
        {"idx": 0, "start_ms": 0, "end_ms": 1000, "kind": "silence"},
        {"idx": 1, "start_ms": 1000, "end_ms": 2000, "kind": "speech"},
    ])
    rows = store.get_speech_spans(conn, job_id)
    assert len(rows) == 2
    assert rows[1].kind == "speech"
    assert rows[0].end_ms == 1000
    conn.close()
    db.unlink()
    Path(audio_path).unlink()


def test_drop_tokens_over_silence():
    from transcribe.contracts import PipelineToken
    from transcribe.pipeline.normalize import drop_tokens_over_silence

    def tok(idx, s, e):
        return PipelineToken(idx=idx, text="x", start_ms=s, end_ms=e,
                             script="latin", confidence=0.9, source_engine="a")

    silence = [(1000, 2000)]
    tokens = [
        tok(0, 0, 500),       # fully in speech — keep
        tok(1, 1100, 1900),   # fully in silence — drop
        tok(2, 1750, 2250),   # 50% straddle the boundary — keep
    ]
    kept = drop_tokens_over_silence(tokens, silence, overlap=0.8)
    texts = [(t.start_ms, t.end_ms) for t in kept]
    assert (1100, 1900) not in texts
    assert (0, 500) in texts
    assert (1750, 2250) in texts
    # idx re-contiguized
    assert [t.idx for t in kept] == [0, 1]


# ── GAP-4: chunk stitch ───────────────────────────────────────────────────────

def test_stitch_dedupes_seam_and_keeps_interior_copy():
    from transcribe.contracts import RecognizedToken
    from transcribe.pipeline.stitch import ChunkTokens, stitch

    chunk0 = ChunkTokens(
        start_ms=0, end_ms=1000,
        tokens=[
            RecognizedToken("hello", 0, 400, 0.9, "latin"),
            RecognizedToken("there", 400, 800, 0.9, "latin"),
            RecognizedToken("world", 800, 1000, 0.8, "latin"),  # near right seam
        ],
    )
    chunk1 = ChunkTokens(
        start_ms=800, end_ms=2000,
        tokens=[
            RecognizedToken("world", 820, 1020, 0.7, "latin"),  # deeper in its chunk
            RecognizedToken("again", 1020, 1600, 0.9, "latin"),
        ],
    )
    merged = stitch([chunk0, chunk1], iou_threshold=0.5)
    worlds = [t for t in merged if t.text == "world"]
    assert len(worlds) == 1, "duplicate seam word not deduped"
    assert worlds[0].start_ms == 820, "should keep the copy more interior to its chunk"
    assert [t.text for t in merged] == ["hello", "there", "world", "again"]


# ── GAP-5: bias prompt budget ─────────────────────────────────────────────────

def test_build_prompt_respects_budget_and_keeps_top_weight():
    from transcribe.flywheel.inject import BiasTerm, build_prompt

    # One token per term under this counter.
    count = lambda s: len(s.split())
    terms = [BiasTerm(term=f"term{i}", weight=float(i)) for i in range(500)]
    budget = 20
    prompt = build_prompt(terms, budget_tokens=budget, count_tokens=count)

    words = prompt.split()
    used = len(words) + (len(words) - 1)  # terms + joining spaces
    assert used <= budget, f"prompt exceeded budget: {used} > {budget}"
    # Highest-weight term always survives; a low-weight one cannot fit.
    assert "term499" in words
    assert "term0" not in words


def test_build_prompt_thai_is_token_dense_under_default_counter():
    from transcribe.flywheel.inject import BiasTerm, _approx_tokens
    # Thai chars each count as a token; Latin words as one each.
    assert _approx_tokens("สวัสดี") == 6
    assert _approx_tokens("hello world") == 2


# ── GAP-7: correction.reason ──────────────────────────────────────────────────

def test_correction_reason_optional():
    from transcribe.db import store

    db = _tmp_db()
    store.init_db(db)
    conn = store.connect(db)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as af:
        af.write(b"\x00" * 64)
        audio_path = af.name
    media_id = store.create_media(conn, audio_path)
    job_id = store.create_job(conn, media_id, "a", "b", "1.0")

    # Without reason
    store.create_correction(conn, job_id, 0, "ก", "ข", "a")
    # With reason
    store.create_correction(conn, job_id, 1, "ค", "ง", "a", reason="misheard")

    rows = store.get_corrections(conn, job_id)
    by_idx = {r.token_idx: r for r in rows}
    assert by_idx[0].reason is None
    assert by_idx[1].reason == "misheard"
    conn.close()
    db.unlink()
    Path(audio_path).unlink()


# ── A.2: eval_run attribution ─────────────────────────────────────────────────

def test_eval_run_attribution_columns():
    from transcribe.db import store

    db = _tmp_db()
    store.init_db(db)
    conn = store.connect(db)
    store.create_eval_run(
        conn, "cfg", 0.1, 0.2, True,
        cer_thai=0.05, wer_latin=0.08,
        kind="transcribe", pipeline_version="1.0.0",
        engine_pair="whisper_thai+whisper_multi", bias_hash="deadbeef",
    )
    last = store.get_last_passing_eval(conn)
    assert last.pipeline_version == "1.0.0"
    assert last.engine_pair == "whisper_thai+whisper_multi"
    assert last.bias_hash == "deadbeef"
    assert last.kind == "transcribe"
    conn.close()
    db.unlink()


def test_media_timebase_roundtrip():
    from transcribe.db import store

    db = _tmp_db()
    store.init_db(db)
    conn = store.connect(db)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as af:
        af.write(b"\x00" * 64)
        audio_path = af.name
    media_id = store.create_media(conn, audio_path)
    store.set_media_timebase(conn, media_id, 30000, 1001, is_vfr=True)
    media = store.get_media(conn, media_id)
    assert media.fps_num == 30000
    assert media.fps_den == 1001
    assert media.is_vfr == 1
    conn.close()
    db.unlink()
    Path(audio_path).unlink()
