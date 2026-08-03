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
                prev.dissolved_ms += s.dissolved_ms
        else:
            out.append(CutSpan(0, s.src_in_ms, s.src_out_ms, s.action,
                               reason=s.reason, source=s.source,
                               dissolved_ms=s.dissolved_ms))
    for i, s in enumerate(out):
        s.idx = i
    return out


_STANDALONE = "min_clip_standalone"


def _has_token(tokens: Optional[list], span: CutSpan) -> bool:
    """True if any token's midpoint falls inside ``span``. Real transcribed
    content — never a pure VAD noise blip — so the merge must never erase it."""
    if not tokens:
        return False
    for t in tokens:
        mid = (t.start_ms + t.end_ms) / 2
        if span.src_in_ms <= mid < span.src_out_ms:
            return True
    return False


def apply_min_clip_merge(
    spans: list[CutSpan], min_clip_ms: int, max_dissolve_ms: Optional[int] = None,
    tokens: Optional[list] = None,
) -> list[CutSpan]:
    """Dissolve cuts adjacent to too-short kept clips, toward the longer neighbour.

    ``max_dissolve_ms`` caps how much dead air a *contiguous kept run* may
    re-admit in total (None = uncapped, the old behaviour) — not just the one
    cut being dissolved this iteration. A chain of several short blips each
    bordered by silences individually under the cap would otherwise dissolve
    one-by-one across iterations and stitch a large stretch of dead air back
    together anyway; tracking cumulative ``dissolved_ms`` per run closes that.
    A too-short keep island whose only merge options would blow the cumulative
    cap is dropped (turned into CUT) instead — otherwise a stray
    sub-``min_clip_ms`` blip between long silences forces the *whole* silence
    back into the kept timeline, which defeats the silence pass rather than
    merely tidying its edges.

    ``tokens`` (real-world bug, 2026-08-03, round 3): a too-short keep island
    that contains an actual transcribed word — e.g. two brief, separately
    spoken words either side of a real ~1.8s pause — is never merged or
    dropped, even though it is short and its neighbouring cut is well inside
    the dissolve cap. Forcing that pause back into the kept timeline just to
    satisfy ``min_clip_ms`` re-admits real dead air around real content;
    instead the island stands alone as its own short clip, and neighbouring
    cuts are barred from dissolving *through* it (which would silently absorb
    it via coalescing from the far side). Only genuinely empty islands — no
    token inside them — are still subject to merge/drop.

    Each pass either shrinks a cut to nothing (dissolve), grows one (drop), or
    settles a token-bearing island permanently, so the count of unsettled
    too-short keeps strictly decreases and the loop terminates. A lone kept
    clip with no neighbouring cut is left as-is.
    """
    spans = _coalesce(spans)
    while True:
        short = [i for i, s in enumerate(spans)
                 if s.action == KEEP and s.duration_ms < min_clip_ms
                 and s.reason != _STANDALONE]
        if not short:
            break
        # Shortest first; tie-break on position for determinism.
        i = min(short, key=lambda k: (spans[k].duration_ms, k))

        if _has_token(tokens, spans[i]):
            spans[i].reason = _STANDALONE
            continue

        has_left_cut = i - 1 >= 0 and spans[i - 1].action == CUT
        has_right_cut = i + 1 < len(spans) and spans[i + 1].action == CUT
        if not has_left_cut and not has_right_cut:
            break  # isolated keep, nothing to merge into

        def _reclaimed_total(cut_idx: int) -> int:
            """Dead air the resulting merged run would carry if ``cut_idx`` dissolves:
            the short keep's own accumulated total, this cut's full duration, and
            (if present) the far KEEP neighbour's accumulated total."""
            total = spans[i].dissolved_ms + spans[cut_idx].duration_ms
            far = cut_idx - 1 if cut_idx < i else cut_idx + 1
            if 0 <= far < len(spans) and spans[far].action == KEEP:
                total += spans[far].dissolved_ms
            return total

        def _far_is_protected(cut_idx: int) -> bool:
            """The far KEEP across this cut is a settled/token island — dissolving
            this cut would silently swallow it into the merged run via coalescing."""
            far = cut_idx - 1 if cut_idx < i else cut_idx + 1
            if not (0 <= far < len(spans) and spans[far].action == KEEP):
                return False
            return spans[far].reason == _STANDALONE or _has_token(tokens, spans[far])

        left_ok = (has_left_cut and not _far_is_protected(i - 1)
                   and (max_dissolve_ms is None
                        or _reclaimed_total(i - 1) <= max_dissolve_ms))
        right_ok = (has_right_cut and not _far_is_protected(i + 1)
                    and (max_dissolve_ms is None
                         or _reclaimed_total(i + 1) <= max_dissolve_ms))

        if not left_ok and not right_ok:
            # Both neighbouring cuts are too long to absorb cheaply — the short
            # island is more likely noise than a real utterance worth stitching
            # two long silences back together for. Drop it instead.
            spans[i] = CutSpan(0, spans[i].src_in_ms, spans[i].src_out_ms, CUT,
                               reason="min_clip_drop", source=SOURCE_RULE)
            spans = _coalesce(spans)
            continue

        if left_ok and right_ok:
            left_keep = spans[i - 2].duration_ms if i - 2 >= 0 else -1
            right_keep = spans[i + 2].duration_ms if i + 2 < len(spans) else -1
            dissolve = i - 1 if left_keep >= right_keep else i + 1
        else:
            dissolve = i - 1 if left_ok else i + 1

        spans[dissolve] = CutSpan(0, spans[dissolve].src_in_ms,
                                  spans[dissolve].src_out_ms, KEEP,
                                  dissolved_ms=spans[dissolve].duration_ms)
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
    return apply_min_clip_merge(assembled, cfg.min_clip_ms, cfg.max_dissolve_ms, tokens)
