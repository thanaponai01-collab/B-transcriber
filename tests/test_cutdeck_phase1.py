"""CutDeck Phase 1 acceptance tests — segment.py + rules.py + plan.py.

Covers IMPLEMENT_CUTDECK.md §B.3 acceptance:
  * segmentation by gap and by VAD silence;
  * silence cuts shrunk by padding, padding never overlapping a kept clip;
  * short silence left as pace;
  * determinism (byte-identical plan across runs);
  * min-clip merge (no kept clip shorter than min_clip_ms);
  * contiguous + exhaustive plan invariant (assertion enforced);
  * config-gated filler removal incl. contextual isolation;
  * CutPlan JSON round-trip and DB store round-trip;
  * end-to-end propose_for_job from the store (wiring).

All GPU-free. Run: python -m pytest tests/test_cutdeck_phase1.py -v
"""

import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from cutdeck.contracts import CUT, KEEP, CutConfig, CutSpan, Timebase  # noqa: E402
from cutdeck.rules import build_cut_spans  # noqa: E402
from cutdeck.segment import segment_tokens  # noqa: E402
from cutdeck import plan as planmod  # noqa: E402


@dataclass
class Tok:
    idx: int
    text: str
    start_ms: int
    end_ms: int


@dataclass
class Span:
    start_ms: int
    end_ms: int
    kind: str


def _silence(s, e):
    return Span(s, e, "silence")


def _speech(s, e):
    return Span(s, e, "speech")


# ── segment.py ────────────────────────────────────────────────────────────────

def test_segment_splits_on_gap():
    cfg = CutConfig(gap_ms=700)
    toks = [Tok(0, "a", 0, 500), Tok(1, "b", 600, 1000),   # 100ms gap → same seg
            Tok(2, "c", 2000, 2500)]                         # 1000ms gap → split
    segs = segment_tokens(toks, None, cfg)
    assert len(segs) == 2
    assert segs[0].token_ids == [0, 1]
    assert segs[1].token_ids == [2]
    assert segs[0].text == "a b"
    assert segs[1].start_ms == 2000 and segs[1].end_ms == 2500


def test_segment_splits_on_vad_silence_within_subgap_window():
    # Token gap is 700ms (NOT > gap_ms, so no gap-split), but a 600ms VAD silence
    # sits inside that window → the VAD signal forces the split on its own.
    cfg = CutConfig(gap_ms=700, segment_vad_silence_ms=500)
    toks = [Tok(0, "a", 0, 1000), Tok(1, "b", 1700, 2500)]
    spans = [_speech(0, 1000), _silence(1000, 1600), _speech(1600, 2500)]
    segs = segment_tokens(toks, spans, cfg)
    assert len(segs) == 2


def test_segment_empty_and_single():
    assert segment_tokens([], None, CutConfig()) == []
    segs = segment_tokens([Tok(0, "x", 0, 100)], None, CutConfig())
    assert len(segs) == 1 and segs[0].token_ids == [0]


# ── rules.py: silence cuts + padding ──────────────────────────────────────────

def test_silence_cut_shrunk_by_padding_no_overlap():
    cfg = CutConfig(min_silence_ms=900, pad_post_ms=120, pad_pre_ms=250, min_clip_ms=1200)
    spans = [_speech(0, 3000), _silence(3000, 5000), _speech(5000, 10000)]
    out = build_cut_spans([], spans, 10000, cfg)

    actions = [(s.action, s.src_in_ms, s.src_out_ms) for s in out]
    assert actions == [
        (KEEP, 0, 3120),       # +120ms post-roll kept on preceding speech
        (CUT, 3120, 4750),     # silence shrunk by both pads
        (KEEP, 4750, 10000),   # 250ms pre-roll kept before following speech
    ]
    # Padding never overlaps an adjacent kept clip: keeps butt the cut, not each other.
    cut = next(s for s in out if s.action == CUT)
    keeps = [s for s in out if s.action == KEEP]
    assert keeps[0].src_out_ms <= cut.src_in_ms
    assert keeps[1].src_in_ms >= cut.src_out_ms
    assert cut.reason == "silence" and cut.source == "rule"


def test_short_silence_is_pace_not_cut():
    cfg = CutConfig(min_silence_ms=900)
    spans = [_speech(0, 3000), _silence(3000, 3500), _speech(3500, 8000)]  # 500ms < 900
    out = build_cut_spans([], spans, 8000, cfg)
    assert all(s.action == KEEP for s in out)
    assert len(out) == 1 and out[0].src_in_ms == 0 and out[0].src_out_ms == 8000


def test_padding_consuming_whole_silence_yields_no_cut():
    # Silence just over threshold but smaller than the padding sum → no cut emitted.
    cfg = CutConfig(min_silence_ms=300, pad_post_ms=250, pad_pre_ms=250)
    spans = [_speech(0, 1000), _silence(1000, 1400), _speech(1400, 5000)]  # 400ms silence
    out = build_cut_spans([], spans, 5000, cfg)
    assert all(s.action == KEEP for s in out)


# ── rules.py: determinism ─────────────────────────────────────────────────────

def test_determinism_byte_identical_plan():
    cfg = CutConfig()
    spans = [_speech(0, 3000), _silence(3000, 5000), _speech(5000, 9000),
             _silence(9000, 11000), _speech(11000, 15000)]
    tb = Timebase(30000, 1001)

    def make():
        s = build_cut_spans([], spans, 15000, cfg)
        return planmod.dumps(planmod.build_plan(1, "abc", tb, 15000, s))

    assert make() == make()


# ── rules.py: min-clip merge ──────────────────────────────────────────────────

def test_min_clip_merge_absorbs_short_island_toward_longer_neighbor():
    cfg = CutConfig(min_silence_ms=900, pad_post_ms=120, pad_pre_ms=250, min_clip_ms=1200)
    spans = [
        _speech(0, 2000), _silence(2000, 4000),
        _speech(4000, 4200), _silence(4200, 7000),   # leaves a ~570ms keep island
        _speech(7000, 10000),
    ]
    out = build_cut_spans([], spans, 10000, cfg)
    # Every kept clip must be >= min_clip_ms.
    assert all(s.duration_ms >= cfg.min_clip_ms for s in out if s.action == KEEP)
    # The island merged toward the longer (right) neighbour: the second cut dissolved.
    assert [s.action for s in out] == [KEEP, CUT, KEEP]
    cut = next(s for s in out if s.action == CUT)
    assert (cut.src_in_ms, cut.src_out_ms) == (2120, 3750)


def test_min_clip_does_not_fire_when_disabled():
    cfg = CutConfig(min_silence_ms=900, pad_post_ms=120, pad_pre_ms=250, min_clip_ms=0)
    spans = [_speech(0, 2000), _silence(2000, 4000),
             _speech(4000, 4200), _silence(4200, 7000), _speech(7000, 10000)]
    out = build_cut_spans([], spans, 10000, cfg)
    assert [s.action for s in out].count(CUT) == 2


# ── rules.py: filler removal ──────────────────────────────────────────────────

def test_safe_filler_cut_when_enabled():
    cfg = CutConfig(fillers_enabled=True, filler_lexicon=("uh",), min_clip_ms=0)
    toks = [Tok(0, "hello", 0, 500), Tok(1, "uh", 600, 800), Tok(2, "world", 900, 1400)]
    out = build_cut_spans(toks, None, 2000, cfg)
    cuts = [(s.src_in_ms, s.src_out_ms, s.reason) for s in out if s.action == CUT]
    assert cuts == [(600, 800, "filler")]


def test_filler_off_by_default():
    cfg = CutConfig(filler_lexicon=("uh",))  # fillers_enabled defaults False
    toks = [Tok(0, "uh", 0, 500)]
    out = build_cut_spans(toks, None, 2000, cfg)
    assert all(s.action == KEEP for s in out)


def test_contextual_filler_only_cut_when_isolated():
    cfg = CutConfig(fillers_enabled=True, filler_lexicon=(),
                    filler_lexicon_contextual=("แบบ",), contextual_isolation_ms=200,
                    min_clip_ms=0)
    tok = Tok(0, "แบบ", 1000, 1200)

    # Not isolated (no surrounding silence) → kept.
    out = build_cut_spans([tok], None, 2000, cfg)
    assert all(s.action == KEEP for s in out)

    # Isolated by >=200ms silence on both sides → cut.
    spans = [_silence(800, 1000), _speech(1000, 1200), _silence(1200, 1400)]
    out = build_cut_spans([tok], spans, 2000, cfg)
    assert any(s.action == CUT and s.reason == "filler" for s in out)


# ── plan.py: invariant + serialization ────────────────────────────────────────

def test_build_plan_rejects_gappy_spans():
    bad = [CutSpan(0, 0, 1000, KEEP), CutSpan(1, 2000, 5000, KEEP)]  # gap 1000–2000
    with pytest.raises(ValueError):
        planmod.build_plan(1, "abc", Timebase(30, 1), 5000, bad)


def test_build_plan_rejects_wrong_duration():
    spans = [CutSpan(0, 0, 4000, KEEP)]
    with pytest.raises(ValueError):
        planmod.build_plan(1, "abc", Timebase(30, 1), 5000, spans)  # ends at 4000 != 5000


def test_plan_json_roundtrip():
    cfg = CutConfig()
    spans = build_cut_spans([], [_speech(0, 3000), _silence(3000, 5000), _speech(5000, 9000)],
                            9000, cfg)
    plan = planmod.build_plan(42, "deadbeef", Timebase(30000, 1001), 9000, spans)
    again = planmod.loads(planmod.dumps(plan))
    assert planmod.to_dict(again) == planmod.to_dict(plan)
    assert again.timebase.fps_num == 30000 and again.timebase.fps_den == 1001


def test_segment_ids_attached_to_containing_span():
    cfg = CutConfig(min_silence_ms=900, pad_post_ms=120, pad_pre_ms=250, min_clip_ms=0)
    toks = [Tok(0, "a", 0, 1000), Tok(1, "b", 6000, 7000)]
    spans_vad = [_speech(0, 1000), _silence(1000, 5000), _speech(5000, 7000)]
    duration = 7000
    segs = segment_tokens(toks, spans_vad, cfg)
    cut_spans = build_cut_spans(toks, spans_vad, duration, cfg)
    plan = planmod.build_plan(1, "abc", Timebase(30, 1), duration, cut_spans, segments=segs)
    # Each segment's midpoint lands in exactly one span; all ids accounted for once.
    attached = [sid for s in plan.spans for sid in s.segment_ids]
    assert sorted(attached) == [s.id for s in segs]


# ── plan.py: store round-trip + end-to-end wiring ─────────────────────────────

def _tmp_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return Path(f.name)


def _seed_job(conn):
    from transcribe.db import store
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as af:
        af.write(b"\x00" * 64)
        audio_path = af.name
    media_id = store.create_media(conn, audio_path)
    store.set_media_timebase(conn, media_id, 30000, 1001, is_vfr=False)
    job_id = store.create_job(conn, media_id, "a", "b", "1.0")
    return job_id, audio_path


def test_plan_store_roundtrip():
    from transcribe.db import store
    db = _tmp_db()
    store.init_db(db)
    conn = store.connect(db)
    job_id, audio_path = _seed_job(conn)

    spans = build_cut_spans([], [_speech(0, 3000), _silence(3000, 5000), _speech(5000, 9000)],
                            9000, CutConfig())
    plan = planmod.build_plan(job_id, "abc", Timebase(30000, 1001), 9000, spans)
    plan_id = planmod.save_plan(conn, plan)
    loaded = planmod.load_plan(conn, plan_id)
    assert planmod.to_dict(loaded) == planmod.to_dict(plan)

    row = store.get_cut_plan(conn, plan_id)
    assert row.status == "proposed"
    store.update_cut_plan_status(conn, plan_id, "reviewed")
    assert store.get_cut_plan(conn, plan_id).status == "reviewed"

    conn.close()
    db.unlink()
    Path(audio_path).unlink()


def test_propose_for_job_end_to_end():
    from transcribe.db import store
    db = _tmp_db()
    store.init_db(db)
    conn = store.connect(db)
    job_id, audio_path = _seed_job(conn)

    store.bulk_create_tokens(conn, [
        {"job_id": job_id, "idx": 0, "text": "สวัสดี", "start_ms": 0, "end_ms": 3000,
         "script": "thai", "confidence": 0.9, "source_engine": "a", "speaker_id": None},
        {"job_id": job_id, "idx": 1, "text": "ครับ", "start_ms": 5000, "end_ms": 9000,
         "script": "thai", "confidence": 0.9, "source_engine": "a", "speaker_id": None},
    ])
    store.bulk_create_speech_spans(conn, job_id, [
        {"idx": 0, "start_ms": 0, "end_ms": 3000, "kind": "speech"},
        {"idx": 1, "start_ms": 3000, "end_ms": 5000, "kind": "silence"},
        {"idx": 2, "start_ms": 5000, "end_ms": 9000, "kind": "speech"},
    ])

    plan = planmod.propose_for_job(conn, job_id, CutConfig())
    # One real silence cut, contiguous over the 9s timeline.
    assert plan.duration_ms == 9000
    assert any(s.action == CUT and s.reason == "silence" for s in plan.spans)
    planmod.assert_contiguous_exhaustive(plan.spans, 9000)
    assert plan.timebase.fps_num == 30000

    conn.close()
    db.unlink()
    Path(audio_path).unlink()
