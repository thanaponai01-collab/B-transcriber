"""segment.py — utterance segmentation (IMPLEMENT_CUTDECK.md §B.3, Layer 2).

Group the token stream into segments. Thai has no sentence punctuation to lean
on, so *gaps are the honest signal* — we deliberately do not import a sentence
tokenizer. A new segment starts when either:

  * the gap from the previous token's end to this token's start exceeds
    ``gap_ms`` (default 700), **or**
  * a VAD silence span sitting between the two tokens is longer than
    ``segment_vad_silence_ms`` (default 500) — a stronger, sample-accurate signal
    even when the token timestamps happen to abut.

Inputs are duck-typed: a *token* is anything with ``idx, text, start_ms, end_ms``
(both ``transcribe`` ``TokenRow`` and ``PipelineToken`` qualify); a *speech span*
is anything with ``start_ms, end_ms, kind`` (the ``SpeechSpanRow`` from GAP-3).
"""

from __future__ import annotations

from typing import Iterable, Optional, Protocol

from cutdeck.contracts import CutConfig, Segment


class _Token(Protocol):
    idx: int
    text: str
    start_ms: int
    end_ms: int


class _Span(Protocol):
    start_ms: int
    end_ms: int
    kind: str


def _silence_intervals(spans: Optional[Iterable[_Span]]) -> list[tuple[int, int]]:
    """Extract (start_ms, end_ms) for VAD silence spans, sorted by start."""
    if not spans:
        return []
    out = [(s.start_ms, s.end_ms) for s in spans if getattr(s, "kind", None) == "silence"]
    out.sort()
    return out


def _max_silence_between(lo: int, hi: int, silences: list[tuple[int, int]]) -> int:
    """Longest silence-span duration overlapping the open interval (lo, hi).

    Used to decide a VAD-driven segment split independently of token timestamps.
    """
    if hi <= lo:
        return 0
    longest = 0
    for s, e in silences:
        if e <= lo:
            continue
        if s >= hi:
            break  # silences are sorted by start
        overlap = min(e, hi) - max(s, lo)
        if overlap > longest:
            longest = overlap
    return longest


def segment_tokens(
    tokens: list[_Token],
    spans: Optional[Iterable[_Span]] = None,
    cfg: Optional[CutConfig] = None,
) -> list[Segment]:
    """Group ``tokens`` (assumed ordered by time) into :class:`Segment` objects.

    Empty input yields an empty list. A single token yields one segment.
    """
    cfg = cfg or CutConfig()
    if not tokens:
        return []

    silences = _silence_intervals(spans)

    segments: list[Segment] = []
    cur: list[_Token] = [tokens[0]]

    def _flush(group: list[_Token]) -> None:
        seg_id = len(segments)
        text = " ".join(t.text for t in group).strip()
        segments.append(Segment(
            id=seg_id,
            start_ms=group[0].start_ms,
            end_ms=group[-1].end_ms,
            token_ids=[t.idx for t in group],
            text=text,
        ))

    for prev, tok in zip(tokens, tokens[1:]):
        gap = tok.start_ms - prev.end_ms
        vad_silence = _max_silence_between(prev.end_ms, tok.start_ms, silences)
        boundary = gap > cfg.gap_ms or vad_silence > cfg.segment_vad_silence_ms
        if boundary:
            _flush(cur)
            cur = [tok]
        else:
            cur.append(tok)
    _flush(cur)
    return segments
