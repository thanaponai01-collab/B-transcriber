"""Phase 4 acceptance — segment-first rough cut (HANDOFF_CUTDECK_WORDLEVEL.md).

``cut.rough_cut_mode: segment`` builds keeps outward from segments instead of
subtracting VAD silence intervals out of the whole timeline: a kept segment is
an utterance by construction, so a too-short one is just a short utterance,
never a case ``apply_min_clip_merge``'s dissolve/standalone bookkeeping has to
reason about. Default mode stays ``interval`` (byte-identical to pre-Phase-4
behaviour) until the segment path has been watched on real footage.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from cutdeck.contracts import (  # noqa: E402
    CUT,
    KEEP,
    LABEL_KEEP_WORTHY,
    ROUGH_CUT_INTERVAL,
    ROUGH_CUT_SEGMENT,
    CutConfig,
)
from cutdeck.rules import build_cut_spans, label_segments  # noqa: E402
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


# ── label_segments: the first real producer of the Layer-3 Label type ────────

def test_label_segments_keeps_every_segment_for_now():
    toks = [Tok(0, "a", 0, 500), Tok(1, "b", 2000, 2500)]
    segs = segment_tokens(toks, None, CutConfig(gap_ms=700))
    labels = label_segments(segs)
    assert len(labels) == len(segs)
    assert all(l.action == KEEP and l.kind == LABEL_KEEP_WORTHY for l in labels)
    assert sorted(l.segment_id for l in labels) == [s.id for s in segs]


def test_label_segments_empty_input():
    assert label_segments([]) == []


# ── config plumbing ────────────────────────────────────────────────────────────

def test_rough_cut_mode_defaults_to_interval():
    assert CutConfig().rough_cut_mode == ROUGH_CUT_INTERVAL
    assert CutConfig.from_yaml({}).rough_cut_mode == ROUGH_CUT_INTERVAL


def test_rough_cut_mode_read_from_yaml():
    cfg = CutConfig.from_yaml({"cut": {"rough_cut_mode": "segment"}})
    assert cfg.rough_cut_mode == ROUGH_CUT_SEGMENT


# ── the three real-world bug fixtures, rebuilt for segment mode ──────────────
#
# Same scenarios that drove apply_min_clip_merge's dissolved_ms/_STANDALONE
# machinery (tests/test_cutdeck_phase1.py), now with tokens attached to the
# real speech so segments exist. Segment mode must reach the same correct
# answer with none of that machinery involved at all.

def _seg_cfg(**kw):
    return CutConfig(min_silence_ms=350, pad_post_ms=40, pad_pre_ms=80,
                      min_clip_ms=1200, max_dissolve_ms=4000,
                      rough_cut_mode=ROUGH_CUT_SEGMENT, **kw)


def test_segment_mode_drops_tokenless_blip_between_two_long_silences():
    """Bug 1: a sub-min_clip_ms speech blip with NO token between two long
    silences. In interval mode this required max_dissolve_ms + a drop-instead-
    of-merge fallback. In segment mode there is simply no segment there (no
    token → no segment), so the blip was never a candidate keep at all."""
    cfg = _seg_cfg()
    tokens = [Tok(0, "a", 0, 2000), Tok(1, "b", 28790, 33000)]
    spans = [
        _speech(0, 2000), _silence(2000, 20500),
        _speech(20500, 20980),                     # 480ms blip, no token
        _silence(20980, 28790),
        _speech(28790, 33000),
    ]
    segs = segment_tokens(tokens, spans, cfg)
    out = build_cut_spans(tokens, spans, 33000, cfg, segments=segs)

    assert [s.action for s in out] == [KEEP, CUT, KEEP]
    cut = next(s for s in out if s.action == CUT)
    assert (cut.src_in_ms, cut.src_out_ms) == (2040, 28710)


def test_segment_mode_never_chains_dissolves_because_it_never_dissolves():
    """Bug 2: a chain of tokenless blips between silences individually under
    max_dissolve_ms summed to far more and stitched a ~14s stretch back
    together. Segment mode has no dissolve step to chain in the first place —
    tokenless blips simply aren't segments, so the whole chain of silences
    stays cut around the two real segments at either end."""
    cfg = _seg_cfg()
    tokens = [Tok(0, "a", 0, 2000), Tok(1, "b", 17500, 20000)]
    spans = [
        _speech(0, 2000),
        _silence(2000, 5500), _speech(5500, 6000),
        _silence(6000, 9500), _speech(9500, 10000),
        _silence(10000, 13500), _speech(13500, 14000),
        _silence(14000, 17500), _speech(17500, 20000),
    ]
    segs = segment_tokens(tokens, spans, cfg)
    out = build_cut_spans(tokens, spans, 20000, cfg, segments=segs)

    assert [s.action for s in out] == [KEEP, CUT, KEEP]
    cut = next(s for s in out if s.action == CUT)
    assert (cut.src_in_ms, cut.src_out_ms) == (2040, 17420)
    # No dissolved_ms bookkeeping is even meaningful here — nothing merged.
    assert all(s.dissolved_ms == 0 for s in out)


def test_segment_mode_keeps_short_real_word_islands_standalone_no_merge():
    """Bug 3: two brief separately-spoken real words either side of a genuine
    pause, each under min_clip_ms. Interval mode needed _has_token/_STANDALONE
    to stop the merge from stitching them together. Segment mode keeps both as
    their own (short) segments by construction — no merge exists to stop."""
    cfg = _seg_cfg()
    tokens = [Tok(0, "test1", 1520, 2420), Tok(1, "test2", 4030, 5210)]
    spans = [
        _silence(0, 1890), _speech(1890, 2558),
        _silence(2558, 4386), _speech(4386, 5182),
        _silence(5182, 23682),
    ]
    segs = segment_tokens(tokens, spans, cfg)
    out = build_cut_spans(tokens, spans, 23682, cfg, segments=segs)

    keeps = [s for s in out if s.action == KEEP]
    assert len(keeps) == 2
    # Neither was ever a merge/dissolve target — each is its own segment's
    # padded window standing alone (padding alone can push a genuinely short
    # segment's kept span past min_clip_ms; that's not the same as merging).
    assert all(s.dissolved_ms == 0 for s in out)
    # The real pause between the two words survives as its own cut.
    assert any(s.action == CUT and s.src_in_ms >= 2400 and s.src_out_ms <= 4400
               for s in out)


# ── structural invariants under segment mode ─────────────────────────────────

def test_segment_mode_contiguous_exhaustive_and_deterministic():
    cfg = _seg_cfg()
    tokens = [Tok(0, "a", 0, 2000), Tok(1, "b", 5000, 9000), Tok(2, "c", 11000, 15000)]
    spans = [_speech(0, 2000), _silence(2000, 5000), _speech(5000, 9000),
             _silence(9000, 11000), _speech(11000, 15000)]
    segs = segment_tokens(tokens, spans, cfg)

    def make():
        out = build_cut_spans(tokens, spans, 15000, cfg, segments=segs)
        planmod.assert_contiguous_exhaustive(out, 15000)
        return planmod.dumps(planmod.build_plan(1, "abc", planmod.Timebase(30, 1), 15000, out))

    assert make() == make()


def test_segment_mode_keep_span_always_backed_by_a_segment():
    cfg = _seg_cfg()
    tokens = [Tok(0, "a", 1520, 2420), Tok(1, "b", 4030, 5210), Tok(2, "c", 12000, 12800)]
    spans = [_silence(0, 1890), _speech(1890, 2558), _silence(2558, 4386),
             _speech(4386, 5182), _silence(5182, 11700), _speech(11700, 13000),
             _silence(13000, 23682)]
    segs = segment_tokens(tokens, spans, cfg)
    out = build_cut_spans(tokens, spans, 23682, cfg, segments=segs)

    def backed_by_a_segment(span):
        for seg in segs:
            window_lo = seg.start_ms - cfg.pad_pre_ms
            window_hi = seg.end_ms + cfg.pad_post_ms
            if span.src_in_ms < window_hi and span.src_out_ms > window_lo:
                return True
        return False

    for s in out:
        if s.action == KEEP:
            assert backed_by_a_segment(s), s


def test_segment_mode_no_segments_is_all_cut():
    cfg = _seg_cfg()
    out = build_cut_spans([], [_silence(0, 5000)], 5000, cfg, segments=[])
    assert [s.action for s in out] == [CUT]
    assert out[0].reason == "no_speech"


def test_segment_mode_short_gap_between_segments_stays_pace():
    # Segmentation (Layer 2) and the cut decision (Layer 4) are deliberately
    # decoupled: a tight gap_ms splits two segments for utterance-grouping
    # purposes, but the same gap is still well under min_silence_ms, so the
    # cut pass treats it as pace, not dead air.
    cfg = CutConfig(gap_ms=100, segment_vad_silence_ms=100_000, min_silence_ms=900,
                     pad_pre_ms=80, pad_post_ms=40, min_clip_ms=1200,
                     rough_cut_mode=ROUGH_CUT_SEGMENT)
    tokens = [Tok(0, "a", 0, 1000), Tok(1, "b", 1300, 2000)]  # 300ms gap
    spans = [_speech(0, 2000)]
    segs = segment_tokens(tokens, spans, cfg)
    assert len(segs) == 2  # two segments, but the gap between them is pace
    out = build_cut_spans(tokens, spans, 2000, cfg, segments=segs)
    assert [s.action for s in out] == [KEEP]


# ── word-level cuts still apply on top of segment gaps ───────────────────────

def test_segment_mode_still_honors_repeat_cuts():
    from cutdeck.words import Word

    cfg = _seg_cfg(repeats_enabled=True)
    tokens = [Tok(0, "go go stop", 0, 3000)]
    spans = [_speech(0, 3000)]
    segs = segment_tokens(tokens, spans, cfg)
    words = [
        Word("go", 0, 900, None), Word("go", 900, 1800, None),
        Word("stop", 1800, 3000, None),
    ]
    out = build_cut_spans(tokens, spans, 3000, cfg, words=words, segments=segs)
    cuts = [s for s in out if s.action == CUT]
    assert any(s.reason == "repeat" for s in cuts)


# ── default mode is unchanged (regression guard) ─────────────────────────────

def test_interval_mode_is_still_the_default_and_unaffected():
    cfg = CutConfig(min_silence_ms=900, pad_post_ms=120, pad_pre_ms=250, min_clip_ms=1200)
    assert cfg.rough_cut_mode == ROUGH_CUT_INTERVAL
    spans = [_speech(0, 3000), _silence(3000, 5000), _speech(5000, 10000)]
    out = build_cut_spans([], spans, 10000, cfg)
    actions = [(s.action, s.src_in_ms, s.src_out_ms) for s in out]
    assert actions == [(KEEP, 0, 3120), (CUT, 3120, 4750), (KEEP, 4750, 10000)]
