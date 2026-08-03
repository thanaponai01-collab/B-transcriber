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

**``cfg.rough_cut_mode`` (HANDOFF_CUTDECK_WORDLEVEL.md Phase 4, default
``"interval"``)** picks which rule builds rule 1's base keep/cut tiling.
``"interval"`` is the three rules above — silence intervals subtracted out of
the whole timeline, then rule 3 repairs any too-short kept island the
subtraction left behind. ``"segment"`` replaces rules 1+3 with
``label_segments``/``_segment_gap_cuts``: keeps are built *outward* from
``segments`` (Layer 2) instead, so a kept segment is an utterance by
construction and a short one is just a short utterance — nothing merges,
nothing dissolves, because nothing ever subtracted an interval out of it.
Filler and repeat cuts (rule 2, word-level) apply identically in both modes.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional, Protocol

from cutdeck.contracts import (
    BLADE_VAD,
    BLADE_WORD,
    CUT,
    KEEP,
    LABEL_KEEP_WORTHY,
    ROUGH_CUT_SEGMENT,
    SOURCE_LLM,
    SOURCE_RULE,
    CutConfig,
    CutSpan,
    Label,
    Segment,
)
from cutdeck.words import Word

logger = logging.getLogger(__name__)


class _Token(Protocol):
    idx: int
    text: str
    start_ms: int
    end_ms: int


class _Span(Protocol):
    start_ms: int
    end_ms: int
    kind: str


# A raw cut interval before assembly: (start_ms, end_ms, reason, source, blade).
_RawCut = tuple[int, int, str, str, str]


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

def _adaptive_min_silence_ms(silences: list[tuple[int, int]], cfg: CutConfig) -> int:
    """Percentile-based silence threshold (Phase 5.2).

    Replaces the fixed ``min_silence_ms`` floor with a percentile of the job's
    own inter-speech gap distribution, linearly interpolated between ranks —
    floored at ``min_silence_ms`` so the result can only ever be *more*
    conservative (fewer cuts) than the fixed threshold, never more aggressive.
    Off (returns ``cfg.min_silence_ms`` unchanged) unless ``adaptive_silence``.
    """
    if not cfg.adaptive_silence or not silences:
        return cfg.min_silence_ms
    durations = sorted(e - s for s, e in silences)
    rank = (cfg.silence_percentile / 100) * (len(durations) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(durations) - 1)
    frac = rank - lo
    pct = durations[lo] + (durations[hi] - durations[lo]) * frac
    return max(cfg.min_silence_ms, round(pct))


def silence_cuts(
    silences: list[tuple[int, int]],
    cfg: CutConfig,
    min_silence_ms: Optional[int] = None,
) -> list[_RawCut]:
    """Silence spans longer than the threshold → cuts shrunk by the padding.

    ``min_silence_ms`` overrides ``cfg.min_silence_ms`` when given — used by
    ``build_cut_spans`` to thread the Phase 5.2 adaptive threshold through
    without every caller having to know about it.
    """
    threshold = cfg.min_silence_ms if min_silence_ms is None else min_silence_ms
    cuts: list[_RawCut] = []
    for s, e in silences:
        if (e - s) <= threshold:
            continue  # short silence is pace, not dead air
        cut_start = s + cfg.pad_post_ms   # leave post-roll on the preceding speech
        cut_end = e - cfg.pad_pre_ms      # leave pre-roll on the following speech
        if cut_end <= cut_start:
            # Padding consumes the whole silence — nothing left to cut. Guarantees
            # the two kept clips around a cut can never overlap.
            continue
        cuts.append((cut_start, cut_end, "silence", SOURCE_RULE, BLADE_VAD))
    return cuts


# ── rule 2: filler removal ────────────────────────────────────────────────────

def filler_cuts(
    words: list[Word],
    silences: list[tuple[int, int]],
    cfg: CutConfig,
    job_id: Optional[int] = None,
) -> list[_RawCut]:
    """Whole-word filler matches → cuts. Off unless ``fillers_enabled``.

    Operates on the Phase 1 word timeline, not phrase-cue tokens — tokens are
    multi-word phrase cues since granularity 5.4 and will never ``==`` a filler
    (HANDOFF_CUTDECK_WORDLEVEL.md F1). Always-safe fillers cut unconditionally;
    contextual fillers only when isolated by silence on both sides (cutting
    them mid-sentence is how tools mangle Thai).
    """
    if not cfg.fillers_enabled:
        return []
    if not words:
        # Silently doing nothing here is exactly what hid F1 for two months.
        logger.warning(
            "job %s: fillers_enabled but no word timeline available "
            "(words_for_job returned []) — filler cuts skipped", job_id,
        )
        return []
    safe = {w.strip() for w in cfg.filler_lexicon}
    contextual = {w.strip() for w in cfg.filler_lexicon_contextual}
    iso = cfg.contextual_isolation_ms

    cuts: list[_RawCut] = []
    for w in words:
        word = w.text.strip()
        if word in safe:
            cuts.append((w.start_ms, w.end_ms, "filler", SOURCE_RULE, BLADE_WORD))
        elif word in contextual:
            before = _silence_overlap(w.start_ms - iso, w.start_ms, silences)
            after = _silence_overlap(w.end_ms, w.end_ms + iso, silences)
            if before >= iso and after >= iso:
                cuts.append((w.start_ms, w.end_ms, "filler", SOURCE_RULE, BLADE_WORD))
    return cuts


# ── rule 2b: repeated words / stutters ────────────────────────────────────────

_MAI_YAMOK = "ๆ"  # ๆ


def _word_seq_text(ws: list[Word]) -> list[str]:
    return [w.text.strip() for w in ws]


def repeat_cuts(
    words: list[Word],
    segments: list[Segment],
    cfg: CutConfig,
) -> list[_RawCut]:
    """Stutter / duplicated-word removal. Deterministic, no LLM.

    Detection runs independently per segment — a repeat spanning a segment
    boundary is a retake (Phase 6's job), not a stutter, and must never be cut
    here. Keeps the last occurrence of a repeated n-gram, cuts the earlier ones.
    """
    if not cfg.repeats_enabled:
        return []
    cuts: list[_RawCut] = []
    for seg in segments:
        seg_words = [
            w for w in words
            if seg.start_ms <= (w.start_ms + w.end_ms) / 2 < seg.end_ms
        ]
        cuts.extend(_repeat_cuts_in_words(seg_words, cfg))
    return cuts


def _repeat_cuts_in_words(seg_words: list[Word], cfg: CutConfig) -> list[_RawCut]:
    cuts: list[_RawCut] = []
    n_words = len(seg_words)
    i = 0
    while i < n_words:
        matched = False
        top_n = min(cfg.repeat_max_ngram, (n_words - i) // 2)
        for n in range(top_n, 0, -1):
            first = seg_words[i:i + n]
            if n == 1 and len(first[0].text.strip()) <= 1:
                continue  # never cut a single-character "repeat" (noise, not a stutter)

            occurrences = [first]
            k = i + n
            while k + n <= n_words:
                cand = seg_words[k:k + n]
                gap = cand[0].start_ms - occurrences[-1][-1].end_ms
                if gap > cfg.repeat_max_gap_ms:
                    break  # too far apart — deliberate emphasis or a real retake
                if _word_seq_text(cand) != _word_seq_text(first):
                    break
                occurrences.append(cand)
                k += n
            if len(occurrences) < 2:
                continue

            after = seg_words[k] if k < n_words else None
            if after is not None and after.text.strip() == _MAI_YAMOK:
                continue  # เด็กๆ-style reduplication marker, not a real repeat

            for occ in occurrences[:-1]:
                cuts.append((occ[0].start_ms, occ[-1].end_ms, "repeat", SOURCE_RULE, BLADE_WORD))
            i = k
            matched = True
            break
        if not matched:
            i += 1
    return cuts


# ── rule 1c: token-less speech spans (Phase 5.1) ──────────────────────────────

def nonspeech_cuts(
    spans: Optional[Iterable[_Span]],
    tokens: Optional[list],
    words: list[Word],
    cfg: CutConfig,
) -> list[_RawCut]:
    """VAD-misclassified dead air → cuts.

    VAD marks breaths, lip smacks, coughs and camera noise as *speech*, so
    they survive the silence pass as kept pace forever — the largest
    remaining gap between "silence removal" and a real rough cut
    (HANDOFF_CUTDECK_WORDLEVEL.md 5.1). A speech-classified span with no
    token midpoint inside it and longer than ``min_nonspeech_ms`` is cut
    outright, entire, no padding — there is no real content on either edge to
    protect. Guarded twice: only spans VAD already called ``speech`` are
    candidates (silence is already rule 1's job), and a span carrying a word
    from the Phase 1 timeline is never touched even if no phrase-cue token
    covers it.

    Off unless ``cfg.nonspeech_enabled`` — same discipline as fillers/repeats:
    a new cutting behaviour ships off until an eval baseline exists.
    """
    if not cfg.nonspeech_enabled or not spans:
        return []
    cuts: list[_RawCut] = []
    for s in spans:
        if getattr(s, "kind", None) != "speech":
            continue
        if (s.end_ms - s.start_ms) <= cfg.min_nonspeech_ms:
            continue
        probe = CutSpan(0, s.start_ms, s.end_ms, KEEP)
        if _has_token(tokens, probe):
            continue
        if any(s.start_ms <= (w.start_ms + w.end_ms) / 2 < s.end_ms for w in words):
            continue
        cuts.append((s.start_ms, s.end_ms, "nonspeech", SOURCE_RULE, BLADE_VAD))
    return cuts


# ── retake marker pre-pass (Phase 6) ──────────────────────────────────────────

def retake_marker_segments(segments: list[Segment], cfg: CutConfig) -> list[int]:
    """Deterministic explicit-mistake marker detection.

    Whole-phrase substring match of ``cfg.retake_markers`` against each
    segment's text. Whether a marker phrase is present is never the LLM's
    call (IMPLEMENT_CUTDECK.md §B.3 ``takes.py``) — only *how far back* the
    retake it flags reaches is, and that resolution happens in
    ``cutdeck.takes``, not here.
    """
    markers = [m.strip() for m in cfg.retake_markers if m and m.strip()]
    if not markers or not segments:
        return []
    return [seg.id for seg in segments if any(m in seg.text for m in markers)]


def label_cuts(labels: list[Label], segments: list[Segment]) -> list[_RawCut]:
    """Convert Layer-3 CUT labels (``cutdeck.takes.label_takes`` — retake,
    false-start, explicit-mistake judgements) into raw cut intervals over the
    labelled segment's own span. These are judgment cuts, not VAD silence, so
    they carry ``BLADE_WORD`` like filler/repeat cuts — review-UI attention
    goes to the risky ones. Deliberately takes already-computed ``Label``s
    rather than importing ``cutdeck.takes`` itself (which imports
    ``retake_marker_segments`` from this module) — the caller (``plan.py``)
    glues the two together instead of a circular import.
    """
    by_id = {seg.id: seg for seg in segments}
    cuts: list[_RawCut] = []
    for label in labels:
        if label.action != CUT:
            continue
        seg = by_id.get(label.segment_id)
        if seg is None:
            continue
        cuts.append((seg.start_ms, seg.end_ms, label.kind, SOURCE_LLM, BLADE_WORD))
    return cuts


# ── rule 1, segment-first variant (Phase 4) ───────────────────────────────────

def label_segments(segments: list[Segment]) -> list[Label]:
    """Layer 3 — one keep/cut judgement per segment.

    No cut-worthy classifier exists yet (that's Phase 6's retake/false-start
    resolver — the ``Label`` contract type has sat unused since Phase 1
    waiting for it), so every segment keeps for now. ``_segment_gap_cuts``
    reads through this rather than iterating ``segments`` directly so Phase 6
    only has to change what this function returns.
    """
    return [
        Label(segment_id=seg.id, action=KEEP, kind=LABEL_KEEP_WORTHY, source=SOURCE_RULE)
        for seg in segments
    ]


def _segment_gap_cuts(
    segments: list[Segment],
    duration_ms: int,
    cfg: CutConfig,
    min_silence_ms: Optional[int] = None,
) -> list[_RawCut]:
    """Cuts for the space *between* kept segments (Phase 4 — the segment-first
    rough cut). A kept segment is an utterance by construction; there is
    nothing to merge or dissolve because nothing subtracts an interval out of
    it in the first place. Only the gaps — before the first segment, between
    two segments, after the last — are candidates for a cut, gated by the same
    ``min_silence_ms``/pad thresholds the interval pass uses, so segments
    replace VAD silence spans as the source of *where* a boundary sits without
    changing *how big* the padding is.

    A gap with no segments in it at all (nothing kept anywhere) becomes one
    cut over the whole duration — there is no utterance to pad around.
    """
    kept_ids = {l.segment_id for l in label_segments(segments) if l.action == KEEP}
    kept = sorted((s for s in segments if s.id in kept_ids), key=lambda s: s.start_ms)
    if not kept:
        return [(0, duration_ms, "no_speech", SOURCE_RULE, BLADE_VAD)] if duration_ms > 0 else []

    threshold = cfg.min_silence_ms if min_silence_ms is None else min_silence_ms
    cuts: list[_RawCut] = []

    lead_gap = kept[0].start_ms
    if lead_gap > threshold:
        cut_end = kept[0].start_ms - cfg.pad_pre_ms
        if cut_end > 0:
            cuts.append((0, cut_end, "silence", SOURCE_RULE, BLADE_VAD))

    for a, b in zip(kept, kept[1:]):
        gap = b.start_ms - a.end_ms
        if gap <= threshold:
            continue  # short gap is pace, not dead air — segments stay one kept run
        cut_start = a.end_ms + cfg.pad_post_ms
        cut_end = b.start_ms - cfg.pad_pre_ms
        if cut_end > cut_start:
            cuts.append((cut_start, cut_end, "silence", SOURCE_RULE, BLADE_VAD))

    trail_gap = duration_ms - kept[-1].end_ms
    if trail_gap > threshold:
        cut_start = kept[-1].end_ms + cfg.pad_post_ms
        if cut_start < duration_ms:
            cuts.append((cut_start, duration_ms, "silence", SOURCE_RULE, BLADE_VAD))

    return cuts


# ── interval merge + assembly ─────────────────────────────────────────────────

def _union(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """Deterministic union of two '+'-joined tag strings (sorted, de-duped)."""
    parts: set[str] = set()
    for x in (a, b):
        if x:
            parts.update(x.split("+"))
    return "+".join(sorted(parts)) if parts else None


def _union_blade(a: str, b: str) -> str:
    """A merged cut is a word-blade if either half is — the splice risk a
    word-blade edge carries doesn't go away because it overlapped a VAD cut."""
    return BLADE_WORD if BLADE_WORD in (a, b) else BLADE_VAD


def _merge_overlaps(cuts: list[_RawCut], duration_ms: int) -> list[_RawCut]:
    """Clamp to [0, duration], drop empties, merge overlapping/abutting cuts."""
    clamped: list[_RawCut] = []
    for s, e, reason, source, blade in cuts:
        s2, e2 = max(0, s), min(duration_ms, e)
        if e2 > s2:
            clamped.append((s2, e2, reason, source, blade))
    clamped.sort()

    merged: list[_RawCut] = []
    for s, e, reason, source, blade in clamped:
        if merged and s <= merged[-1][1]:
            ps, pe, preason, psource, pblade = merged[-1]
            merged[-1] = (ps, max(pe, e), _union(preason, reason),
                         _union(psource, source), _union_blade(pblade, blade))
        else:
            merged.append((s, e, reason, source, blade))
    return merged


def _assemble(cuts: list[_RawCut], duration_ms: int) -> list[CutSpan]:
    """Invert merged cuts into a contiguous keep/cut tiling of [0, duration]."""
    spans: list[CutSpan] = []
    pos = 0
    idx = 0
    for s, e, reason, source, blade in cuts:
        if s > pos:
            spans.append(CutSpan(idx, pos, s, KEEP)); idx += 1
        spans.append(CutSpan(idx, s, e, CUT, reason=reason, source=source, blade=blade)); idx += 1
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
                prev.blade = _union_blade(prev.blade, s.blade)
            else:
                prev.dissolved_ms += s.dissolved_ms
        else:
            out.append(CutSpan(0, s.src_in_ms, s.src_out_ms, s.action,
                               reason=s.reason, source=s.source,
                               dissolved_ms=s.dissolved_ms, blade=s.blade))
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
    words: Optional[list[Word]] = None,
    segments: Optional[list[Segment]] = None,
    job_id: Optional[int] = None,
    labels: Optional[list[Label]] = None,
) -> list[CutSpan]:
    """Run the full deterministic pass → contiguous keep/cut spans over the media.

    ``words`` (Phase 1 word timeline) and ``segments`` (utterance grouping) are
    optional and independent of ``tokens``: fillers/repeats need real word spans,
    not phrase-cue tokens (HANDOFF_CUTDECK_WORDLEVEL.md F1); a caller with no
    word timeline degrades to no filler/repeat cuts (``filler_cuts`` logs a
    warning), not a crash.

    ``cfg.rough_cut_mode`` (Phase 4) picks which rule builds the base keep/cut
    tiling: ``interval`` (default) subtracts VAD silences from the whole
    timeline, then repairs too-short kept islands with ``apply_min_clip_merge``.
    ``segment`` builds keeps outward from ``segments`` instead — a kept segment
    is an utterance by construction, so a short one is just a short utterance,
    never a merge/dissolve candidate. Filler and repeat cuts (word-level) apply
    identically in both modes; only the base silence pass differs.

    Two Phase 5 wins apply on top, identically in both modes: token-less
    "speech" spans (VAD-misclassified dead air, ``nonspeech_cuts``) and, when
    ``cfg.adaptive_silence`` is on, a percentile-derived silence threshold
    (``_adaptive_min_silence_ms``) in place of the fixed ``min_silence_ms``
    floor — both default off, byte-identical output when off.

    ``labels`` (Phase 6, optional): pre-computed ``cutdeck.takes.label_takes``
    output — retake/false-start/mistake CUT judgements are folded in via
    ``label_cuts`` exactly like filler/repeat cuts. Building the labels
    themselves (segmentation + LLM call) is the caller's job (``plan.py``),
    same reasoning as ``words``/``segments`` above; ``None`` degrades to no
    judgment cuts, not a crash.

    Pure: same (tokens, spans, duration, cfg, words, segments, labels) →
    identical output.
    """
    cfg = cfg or CutConfig()
    words = words or []
    segments = segments or []
    silences = _silence_intervals(spans)
    effective_min_silence_ms = _adaptive_min_silence_ms(silences, cfg)
    word_cuts = (
        filler_cuts(words, silences, cfg, job_id)
        + repeat_cuts(words, segments, cfg)
        + nonspeech_cuts(spans, tokens, words, cfg)
        + (label_cuts(labels, segments) if labels else [])
    )

    if cfg.rough_cut_mode == ROUGH_CUT_SEGMENT:
        raw = _segment_gap_cuts(segments, duration_ms, cfg, effective_min_silence_ms) + word_cuts
        merged = _merge_overlaps(raw, duration_ms)
        return _assemble(merged, duration_ms)

    raw = silence_cuts(silences, cfg, effective_min_silence_ms) + word_cuts
    merged = _merge_overlaps(raw, duration_ms)
    assembled = _assemble(merged, duration_ms)
    return apply_min_clip_merge(assembled, cfg.min_clip_ms, cfg.max_dissolve_ms, tokens)
