"""rules.py — the deterministic cut pass (IMPLEMENT_CUTDECK.md §B.3).

No LLM, ever. Three rules, in order:

  1. **Silence cuts.** Any VAD silence span longer than ``min_silence_ms`` (900)
     becomes a cut, *shrunk by the padding* — ``pad_post_ms`` of kept post-roll is
     left on the preceding speech and ``pad_pre_ms`` of kept pre-roll on the
     following speech (asymmetric: attack matters more than decay). Silences
     shorter than the threshold are *pace*, not dead air — left alone.
  2. **Filler removal** (config-gated, default off). Whole-token matches against
     the filler lexicon become cuts. Contextual entries (``แบบ``, ``ก็คือ``, ...)
     are only cut when *isolated* — silence ≥ ``contextual_isolation_ms`` on both
     sides — because they are real words mid-sentence.
  3. **Min-clip merge.** After all cuts, any kept clip shorter than
     ``min_clip_ms`` (1200) is absorbed into its neighbour (toward the longer
     side) by dissolving the adjoining cut. Prevents confetti timelines.

The output is a contiguous, exhaustive list of :class:`CutSpan` over
``[0, duration_ms]`` — keep and cut alternating, no gaps, no overlaps. The
boundary rule that makes cuts feel human: semantic layers decide *what* to cut;
Layer 0 (these VAD spans) decides *where* the blade lands.

The whole pass is a pure function of (tokens, spans, duration, cfg): identical
inputs yield a byte-identical plan (determinism is an acceptance criterion).
"""

from __future__ import annotations

from typing import Iterable, Optional, Protocol

from cutdeck.contracts import (
    CUT,
    KEEP,
    SOURCE_RULE,
    CutConfig,
    CutSpan,
)


class _Token(Protocol):
    idx: int
    text: str
    start_ms: int
    end_ms: int


class _Span(Protocol):
    start_ms: int
    end_ms: int
    kind: str


# A raw cut interval before assembly: (start_ms, end_ms, reason, source).
_RawCut = tuple[int, int, str, str]


# ── silence detection helpers ─────────────────────────────────────────────────

def _silence_intervals(spans: Optional[Iterable[_Span]]) -> list[tuple[int, int]]:
    if not spans:
        return []
    out = [(s.start_ms, s.end_ms) for s in spans if getattr(s, "kind", None) == "silence"]
    out.sort()
    return out


def _silence_overlap(lo: int, hi: int, silences: list[tuple[int, int]]) -> int:
    """Longest silence overlap with the window [lo, hi]. 0 if none or hi<=lo."""
    if hi <= lo:
        return 0
    longest = 0
    for s, e in silences:
        if e <= lo:
            continue
        if s >= hi:
            break
        ov = min(e, hi) - max(s, lo)
        if ov > longest:
            longest = ov
    return longest


# ── rule 1: silence cuts ──────────────────────────────────────────────────────

def silence_cuts(silences: list[tuple[int, int]], cfg: CutConfig) -> list[_RawCut]:
    """Silence spans longer than the threshold → cuts shrunk by the padding."""
    cuts: list[_RawCut] = []
    for s, e in silences:
        if (e - s) <= cfg.min_silence_ms:
            continue  # short silence is pace, not dead air
        cut_start = s + cfg.pad_post_ms   # leave post-roll on the preceding speech
        cut_end = e - cfg.pad_pre_ms      # leave pre-roll on the following speech
        if cut_end <= cut_start:
            # Padding consumes the whole silence — nothing left to cut. Guarantees
            # the two kept clips around a cut can never overlap.
            continue
        cuts.append((cut_start, cut_end, "silence", SOURCE_RULE))
    return cuts


# ── rule 2: filler removal ────────────────────────────────────────────────────

def filler_cuts(
    tokens: list[_Token],
    silences: list[tuple[int, int]],
    cfg: CutConfig,
) -> list[_RawCut]:
    """Whole-token filler matches → cuts. Off unless ``fillers_enabled``.

    Always-safe fillers cut unconditionally; contextual fillers only when isolated
    by silence on both sides (cutting them mid-sentence is how tools mangle Thai).
    """
    if not cfg.fillers_enabled:
        return []
    safe = {w.strip() for w in cfg.filler_lexicon}
    contextual = {w.strip() for w in cfg.filler_lexicon_contextual}
    iso = cfg.contextual_isolation_ms

    cuts: list[_RawCut] = []
    for t in tokens:
        word = t.text.strip()
        if word in safe:
            cuts.append((t.start_ms, t.end_ms, "filler", SOURCE_RULE))
        elif word in contextual:
            before = _silence_overlap(t.start_ms - iso, t.start_ms, silences)
            after = _silence_overlap(t.end_ms, t.end_ms + iso, silences)
            if before >= iso and after >= iso:
                cuts.append((t.start_ms, t.end_ms, "filler", SOURCE_RULE))
    return cuts


# ── interval merge + assembly ─────────────────────────────────────────────────

def _union(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """Deterministic union of two '+'-joined tag strings (sorted, de-duped)."""
    parts: set[str] = set()
    for x in (a, b):
        if x:
            parts.update(x.split("+"))
    return "+".join(sorted(parts)) if parts else None


def _merge_overlaps(cuts: list[_RawCut], duration_ms: int) -> list[_RawCut]:
    """Clamp to [0, duration], drop empties, merge overlapping/abutting cuts."""
    clamped: list[_RawCut] = []
    for s, e, reason, source in cuts:
        s2, e2 = max(0, s), min(duration_ms, e)
        if e2 > s2:
            clamped.append((s2, e2, reason, source))
    clamped.sort()

    merged: list[_RawCut] = []
    for s, e, reason, source in clamped:
        if merged and s <= merged[-1][1]:
            ps, pe, preason, psource = merged[-1]
            merged[-1] = (ps, max(pe, e), _union(preason, reason), _union(psource, source))
        else:
            merged.append((s, e, reason, source))
    return merged


def _assemble(cuts: list[_RawCut], duration_ms: int) -> list[CutSpan]:
    """Invert merged cuts into a contiguous keep/cut tiling of [0, duration]."""
    spans: list[CutSpan] = []
    pos = 0
    idx = 0
    for s, e, reason, source in cuts:
        if s > pos:
            spans.append(CutSpan(idx, pos, s, KEEP)); idx += 1
        spans.append(CutSpan(idx, s, e, CUT, reason=reason, source=source)); idx += 1
        pos = e
    if pos < duration_ms or not spans:
        spans.append(CutSpan(idx, pos, duration_ms, KEEP))
    return spans


# ── rule 3: min-clip merge ────────────────────────────────────────────────────

def _coalesce(spans: list[CutSpan]) -> list[CutSpan]:
    """Merge consecutive same-action spans; reindex. Reasons/sources unioned."""
    out: list[CutSpan] = []
    for s in spans:
        if out and out[-1].action == s.action:
            prev = out[-1]
            prev.src_out_ms = s.src_out_ms
            if s.action == CUT:
                prev.reason = _union(prev.reason, s.reason)
                prev.source = _union(prev.source, s.source)
        else:
            out.append(CutSpan(0, s.src_in_ms, s.src_out_ms, s.action,
                               reason=s.reason, source=s.source))
    for i, s in enumerate(out):
        s.idx = i
    return out


def apply_min_clip_merge(spans: list[CutSpan], min_clip_ms: int) -> list[CutSpan]:
    """Dissolve cuts adjacent to too-short kept clips, toward the longer neighbour.

    Each pass un-cuts exactly one cut, so cut count strictly decreases and the
    loop terminates. A lone kept clip with no neighbouring cut is left as-is.
    """
    spans = _coalesce(spans)
    while True:
        short = [i for i, s in enumerate(spans)
                 if s.action == KEEP and s.duration_ms < min_clip_ms]
        if not short:
            break
        # Shortest first; tie-break on position for determinism.
        i = min(short, key=lambda k: (spans[k].duration_ms, k))

        has_left_cut = i - 1 >= 0 and spans[i - 1].action == CUT
        has_right_cut = i + 1 < len(spans) and spans[i + 1].action == CUT
        if not has_left_cut and not has_right_cut:
            break  # isolated keep, nothing to merge into

        if has_left_cut and has_right_cut:
            left_keep = spans[i - 2].duration_ms if i - 2 >= 0 else -1
            right_keep = spans[i + 2].duration_ms if i + 2 < len(spans) else -1
            dissolve = i - 1 if left_keep >= right_keep else i + 1
        else:
            dissolve = i - 1 if has_left_cut else i + 1

        spans[dissolve] = CutSpan(0, spans[dissolve].src_in_ms,
                                  spans[dissolve].src_out_ms, KEEP)
        spans = _coalesce(spans)
    return spans


# ── orchestration ─────────────────────────────────────────────────────────────

def build_cut_spans(
    tokens: list[_Token],
    spans: Optional[Iterable[_Span]],
    duration_ms: int,
    cfg: Optional[CutConfig] = None,
) -> list[CutSpan]:
    """Run the full deterministic pass → contiguous keep/cut spans over the media.

    Pure: same (tokens, spans, duration, cfg) → identical output.
    """
    cfg = cfg or CutConfig()
    silences = _silence_intervals(spans)

    raw = silence_cuts(silences, cfg) + filler_cuts(tokens or [], silences, cfg)
    merged = _merge_overlaps(raw, duration_ms)
    assembled = _assemble(merged, duration_ms)
    return apply_min_clip_merge(assembled, cfg.min_clip_ms)
