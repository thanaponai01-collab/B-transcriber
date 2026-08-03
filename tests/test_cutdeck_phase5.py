"""Phase 5 acceptance — two cheap wins on dead air (HANDOFF_CUTDECK_WORDLEVEL.md).

5.1 Token-less speech spans: VAD marks breaths/lip-smacks/coughs/camera noise
as speech, so they survive the silence pass as kept pace forever. A "speech"
span with no token midpoint inside it and longer than ``min_nonspeech_ms`` is
dead air, not content — cut it outright.

5.2 Adaptive silence threshold: a fixed ``min_silence_ms`` floor ignores that
pacing varies within and between takes. When ``adaptive_silence`` is on, the
threshold is a percentile of the job's own inter-speech gap distribution,
floored at ``min_silence_ms`` so it can only ever be more conservative.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from cutdeck.contracts import CUT, KEEP, ROUGH_CUT_SEGMENT, CutConfig  # noqa: E402
from cutdeck.rules import (  # noqa: E402
    _adaptive_min_silence_ms,
    build_cut_spans,
    nonspeech_cuts,
    silence_cuts,
)
from cutdeck.segment import segment_tokens  # noqa: E402
from cutdeck.words import Word  # noqa: E402


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


# ── 5.1 token-less speech spans ───────────────────────────────────────────────

def test_nonspeech_cuts_off_by_default():
    cfg = CutConfig(min_nonspeech_ms=400)
    assert cfg.nonspeech_enabled is False
    spans = [_speech(1000, 1700)]  # 700ms, no token — would cut if enabled
    assert nonspeech_cuts(spans, tokens=[], words=[], cfg=cfg) == []


def test_nonspeech_cuts_cuts_tokenless_speech_span_above_threshold():
    cfg = CutConfig(min_nonspeech_ms=400, nonspeech_enabled=True)
    spans = [_speech(1000, 1700)]  # 700ms, no token
    cuts = nonspeech_cuts(spans, tokens=[], words=[], cfg=cfg)
    assert cuts == [(1000, 1700, "nonspeech", "rule", "vad")]


def test_nonspeech_cuts_keeps_span_containing_a_token():
    cfg = CutConfig(min_nonspeech_ms=400, nonspeech_enabled=True)
    spans = [_speech(1000, 1700)]
    tokens = [Tok(0, "hi", 1200, 1300)]
    assert nonspeech_cuts(spans, tokens=tokens, words=[], cfg=cfg) == []


def test_nonspeech_cuts_keeps_span_containing_a_word_even_without_a_token():
    cfg = CutConfig(min_nonspeech_ms=400, nonspeech_enabled=True)
    spans = [_speech(1000, 1700)]
    words = [Word("hi", 1200, 1300, None)]
    assert nonspeech_cuts(spans, tokens=[], words=words, cfg=cfg) == []


def test_nonspeech_cuts_leaves_span_below_threshold():
    cfg = CutConfig(min_nonspeech_ms=400, nonspeech_enabled=True)
    spans = [_speech(1000, 1200)]  # 200ms, below threshold
    assert nonspeech_cuts(spans, tokens=[], words=[], cfg=cfg) == []


def test_nonspeech_cuts_ignores_silence_kind_spans():
    cfg = CutConfig(min_nonspeech_ms=400, nonspeech_enabled=True)
    spans = [_silence(1000, 1700)]
    assert nonspeech_cuts(spans, tokens=[], words=[], cfg=cfg) == []


def test_nonspeech_cuts_wired_into_build_cut_spans_interval_mode():
    cfg = CutConfig(min_silence_ms=900, pad_pre_ms=250, pad_post_ms=120,
                     min_clip_ms=1200, min_nonspeech_ms=400, nonspeech_enabled=True)
    tokens = [Tok(0, "a", 0, 800), Tok(1, "b", 5000, 5800)]
    spans = [
        _speech(0, 800), _silence(800, 3800),
        _speech(3800, 4500),  # 700ms token-less blip — dead air
        _silence(4500, 5000),
        _speech(5000, 5800),
    ]
    out = build_cut_spans(tokens, spans, 5800, cfg)
    nonspeech = [s for s in out if s.action == CUT and s.reason and "nonspeech" in s.reason]
    assert nonspeech, [(-s.action, s.src_in_ms, s.src_out_ms, s.reason) for s in out]


def test_nonspeech_cuts_wired_into_build_cut_spans_segment_mode():
    cfg = CutConfig(min_silence_ms=900, pad_pre_ms=250, pad_post_ms=120,
                     min_nonspeech_ms=400, nonspeech_enabled=True, rough_cut_mode=ROUGH_CUT_SEGMENT)
    tokens = [Tok(0, "a", 0, 800), Tok(1, "b", 5000, 5800)]
    spans = [
        _speech(0, 800), _silence(800, 3800),
        _speech(3800, 4500),  # 700ms token-less blip — no segment either
        _silence(4500, 5000),
        _speech(5000, 5800),
    ]
    segs = segment_tokens(tokens, spans, cfg)
    out = build_cut_spans(tokens, spans, 5800, cfg, segments=segs)
    nonspeech = [s for s in out if s.action == CUT and s.reason and "nonspeech" in s.reason]
    assert nonspeech


# ── 5.2 adaptive silence threshold ────────────────────────────────────────────

def test_adaptive_disabled_returns_fixed_threshold():
    cfg = CutConfig(min_silence_ms=250, adaptive_silence=False)
    assert _adaptive_min_silence_ms([(0, 300), (0, 900)], cfg) == 250


def test_adaptive_uniform_gaps_cuts_no_more_than_fixed_mode():
    fixed_cfg = CutConfig(min_silence_ms=250, adaptive_silence=False)
    adaptive_cfg = CutConfig(min_silence_ms=250, adaptive_silence=True, silence_percentile=60)
    silences = [(0, 300), (1000, 1300), (2000, 2300), (3000, 3300)]  # uniformly 300ms

    fixed_cuts = silence_cuts(silences, fixed_cfg)
    adaptive_threshold = _adaptive_min_silence_ms(silences, adaptive_cfg)
    adaptive_cuts = silence_cuts(silences, adaptive_cfg, adaptive_threshold)

    assert len(adaptive_cuts) <= len(fixed_cuts)
    assert adaptive_threshold >= adaptive_cfg.min_silence_ms


def test_adaptive_bimodal_threshold_lands_between_the_two_modes():
    cfg = CutConfig(min_silence_ms=100, adaptive_silence=True, silence_percentile=50)
    # Five 200ms gaps, five 800ms gaps.
    silences = [(i * 1000, i * 1000 + 200) for i in range(5)]
    silences += [(i * 1000 + 5000, i * 1000 + 5000 + 800) for i in range(5)]
    threshold = _adaptive_min_silence_ms(silences, cfg)
    assert 200 < threshold < 800


def test_adaptive_off_is_byte_identical_to_today():
    cfg = CutConfig(min_silence_ms=250, pad_pre_ms=50, pad_post_ms=25, adaptive_silence=False)
    tokens = [Tok(0, "a", 0, 800), Tok(1, "b", 5000, 5800)]
    spans = [_speech(0, 800), _silence(800, 5000), _speech(5000, 5800)]
    with_flag_absent = build_cut_spans(tokens, spans, 5800, CutConfig(
        min_silence_ms=250, pad_pre_ms=50, pad_post_ms=25))
    with_flag_off = build_cut_spans(tokens, spans, 5800, cfg)
    assert [(s.action, s.src_in_ms, s.src_out_ms) for s in with_flag_absent] == \
           [(s.action, s.src_in_ms, s.src_out_ms) for s in with_flag_off]


def test_adaptive_floor_never_drops_below_min_silence_ms():
    cfg = CutConfig(min_silence_ms=900, adaptive_silence=True, silence_percentile=10)
    silences = [(0, 150), (1000, 1160), (2000, 2140)]  # all short — percentile would be < 900
    assert _adaptive_min_silence_ms(silences, cfg) == 900
