"""GAP-4 — overlap-aware chunk stitching.

Per-chunk transcription with offset-to-global timestamps duplicates (or
truncates) words wherever chunks overlap — and chunks *should* overlap ~0.5–1 s
so words are not lost at the boundaries. This module merges per-chunk token
streams back into one, removing the duplicates the overlap introduces.

The other half of `windows.py`'s `WindowPolicy.overlap_s`: that field decides
how much consecutive windows share, this module removes what the sharing
duplicates. Moved here from `transcribe/pipeline/` (issue #13) so the pair
lives in one module instead of on opposite sides of the Engine Contract —
see `decode.py`'s `decode_windows`, which composes the two directly. Runs
after each engine, before align_hyp. Pure timestamp/text logic — no model,
no GPU — so the seam behaviour is unit-testable with MockEngine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from transcribe.contracts import RecognizedToken

logger = logging.getLogger(__name__)


@dataclass
class ChunkTokens:
    """One chunk's tokens (already offset to global ms) plus the chunk's own
    global span — needed to judge how interior a token is to its chunk."""
    tokens: list[RecognizedToken]
    start_ms: int
    end_ms: int


def _iou(a: RecognizedToken, b: RecognizedToken) -> float:
    """Temporal intersection-over-union of two token spans."""
    inter = max(0, min(a.end_ms, b.end_ms) - max(a.start_ms, b.start_ms))
    union = max(a.end_ms, b.end_ms) - min(a.start_ms, b.start_ms)
    return inter / union if union > 0 else 0.0


# IoU is the right duplicate test for word-length tokens, but Whisper's Thai
# output is sub-word: pieces run 20-80 ms and are frequently ZERO-length (a
# combining mark lands at start == end), where IoU is structurally 0.0 and no
# threshold can ever match. Two windows decoding the same short syllable place
# it 20-80 ms apart, giving IoU ~0.25-0.45 — under any sane threshold — so the
# duplicate survived into the transcript as visible stutter ('อะไรกก็ตาม',
# 'ทรมานใจจ', 'ไกลกลไกกล' were all this, measured on a 46s clip).
#
# Centre-coincidence catches those without loosening IoU for real words, because
# it scales with the tokens' own duration: two copies of one 60ms syllable sit
# ~20ms apart and match, while a *genuinely* repeated character in the same
# breath ('แบบ', 'รักกับ' — Thai does this constantly) sits a full character
# duration apart and does not. The cross-chunk guard (ci != pci) still carries
# the real safety: repetition inside one chunk is never a stitching artifact.
_COINCIDENT_MS = 60
_COINCIDENT_DUR_FRAC = 0.6

# The exact-text gate above still misses the case where the two windows don't
# just disagree on WHERE a sub-word piece starts/ends but on the split point
# itself: window A emits 'หญ' (a truncated prefix) where window B, with more
# surrounding context, emits the full 'หญิง' covering that same audio; or the
# two windows split the run at different points entirely ('หญิ' vs 'ญิง').
# Neither pair is text-equal, so the exact-text gate never even reaches the
# temporal check, and both fragments survive to concatenate into a doubled-
# syllable stutter (issue #8). _fuzzy_same_word supplements — never replaces
# — the exact-text gate for this case.
#
# A generic similarity RATIO (e.g. difflib's SequenceMatcher) was tried first
# and rejected: for short strings it is too coarse to separate "same speech,
# different split point" from "two distinct words that happen to share one
# character" — every pair of distinct 2-character Thai words sharing exactly
# one character (common: 'มา'/'นา', 'จะ'/'จา', 'มี'/'ปี' — short, high-
# frequency particles constantly recur) scores exactly 0.5, indistinguishable
# from a genuine split-point match. Requiring an ANCHORED overlap (a's suffix
# equals b's prefix, or the reverse, or one fully contains the other) of at
# least `_MIN_FUZZY_OVERLAP` characters closes that specific collision.
#
# It does not close the general one: Thai's short, high-frequency morphemes
# recur as substrings of longer, otherwise-unrelated words too, not just as
# whole short words — 'มา' ("come") is a real word AND the literal prefix of
# 'มานะ' ("diligence"); 'หมา' ("dog") anchors onto 'มานะ' the same way. Text
# alone, at any overlap length, cannot tell "same audio decoded twice" from
# "two real, different words that happen to share a boundary morpheme" — an
# independent correctness gate demonstrated exactly this against an earlier
# version of this fix (หมา/มานะ, ขนม/นมสด, ตลาด/ลาดยาง all false-merged).
#
# The discriminator that actually exists is DURATION, not text: a real
# independently-spoken word — even a short one — takes noticeably longer to
# say than a truncated/misaligned decode fragment. `_FUZZY_FRAGMENT_MAX_MS`
# requires at least one side of a fuzzy (non-exact-text) match to be that
# brief, so a coincidental textual overlap between two normal-duration real
# words is not, by itself, sufficient evidence.
#
# Two earlier values were tried and both wrong, in opposite directions —
# 150ms still let real short-word pairs ('หมา'/'มานะ' etc.) false-merge
# across essentially their whole ordinary spoken-duration range, and a
# subsequent attempt to fix that by raising it to 250ms was reasoned from a
# MISAPPLIED citation: the "อะไร, 160ms" measurement in the IoU-failure
# comment above is the duration of an EXACT-text token from the pre-existing
# `_coincident` mechanism (same text, jittered timestamp) — it was never
# evidence about how long a *differently-segmented* fuzzy-matched fragment
# runs, and citing it to justify widening this constant was an error, not a
# calibration. There is no real measured example of a genuine fuzzy
# split-point duplicate's duration anywhere in this codebase.
#
# In the absence of that evidence, this reuses the ONE duration figure this
# file already has real grounds for: `_COINCIDENT_MS`'s own established
# range for genuine sub-word ASR pieces (20-80ms, cited above from real
# clip measurements). This is deliberately conservative — a differently-
# split duplicate whose pieces both run longer than 80ms (plausible; not
# evidenced either way) will NOT be caught by this path and may still ship
# as a stutter — but the cost of a missed stutter (cosmetic, and the
# project's own workflow already has the user hand-recutting SRTs in
# Premiere) is far lower than the cost of this path silently dropping a
# real spoken word, which is what every wider value tried so far did to
# real, ordinary-duration Thai word pairs. Recalibrate only from real
# fuzzy-dedup log data (see the debug log this path emits below and
# TODO_LEDGER.md's trigger for pulling it) — not from another synthetic
# example, which is how the 150ms and 250ms attempts both went wrong.
#
# This narrower cap still has a live, confirmed-reachable residual (a
# correctness-gate run proved it through stitch() itself, not just as a
# theoretical helper-level case): two distinct real words BOTH under
# `_COINCIDENT_MS` with ~no natural gap between them (e.g. 'มา' immediately
# followed by 'มานี') collide, because `_coincident`'s 60ms tolerance floor
# exceeds the zero-gap centre-distance for tokens that brief regardless of
# whether they're a genuine duplicate. See
# test_brief_zero_gap_real_words_can_still_collide — a mere ~20ms natural
# gap is enough to separate them correctly. Kept as an accepted trade-off
# (not tightened further) because the alternative — requiring both sides
# brief, or shrinking the cap below the sub-word range that motivates this
# path at all — would reopen a false negative on the bug this fix exists to
# catch, the exact mistake rounds 3-4 made in the other direction.
_MIN_FUZZY_OVERLAP = 2
_FUZZY_FRAGMENT_MAX_MS = 80


def _fuzzy_same_word(a: RecognizedToken, b: RecognizedToken) -> bool:
    """True if two tokens with DIFFERENT text look like different sub-word
    segmentations of the same underlying speech rather than two distinct
    words.

    Only ever consulted alongside the temporal coincidence check below (never
    on its own) — text similarity alone is common in Thai (short, high-
    frequency syllables recur constantly) and would over-merge without the
    "same instant" constraint carrying the real safety, exactly as it does
    for the exact-text/_coincident pairing above.
    """
    at, bt = a.text.strip(), b.text.strip()
    if not at or not bt or at == bt:
        return False
    if len(at) < _MIN_FUZZY_OVERLAP or len(bt) < _MIN_FUZZY_OVERLAP:
        return False  # too short for any overlap to be meaningful evidence
    if at in bt or bt in at:
        overlaps = True
    else:
        # Different split point: one text's suffix is the other's prefix (or
        # vice versa). Try the longest possible anchored overlap first so two
        # texts that share their whole shorter length at a boundary aren't
        # stopped at a smaller match.
        overlaps = False
        max_overlap = min(len(at), len(bt)) - 1
        for k in range(max_overlap, _MIN_FUZZY_OVERLAP - 1, -1):
            if at[-k:] == bt[:k] or bt[-k:] == at[:k]:
                overlaps = True
                break
    if not overlaps:
        return False
    a_dur = a.end_ms - a.start_ms
    b_dur = b.end_ms - b.start_ms
    return min(a_dur, b_dur) <= _FUZZY_FRAGMENT_MAX_MS


def _coincident(a: RecognizedToken, b: RecognizedToken) -> bool:
    """True if two same-text tokens occupy essentially the same instant.

    Duration-relative, so it degrades gracefully from zero-length combining
    marks up to full words rather than needing a per-granularity threshold.
    """
    centre_a = (a.start_ms + a.end_ms) / 2
    centre_b = (b.start_ms + b.end_ms) / 2
    mean_dur = ((a.end_ms - a.start_ms) + (b.end_ms - b.start_ms)) / 2
    tol = max(_COINCIDENT_MS, _COINCIDENT_DUR_FRAC * mean_dur)
    return abs(centre_a - centre_b) <= tol


def _interiority(tok: RecognizedToken, chunk_start: int, chunk_end: int) -> int:
    """Distance from a token's centre to the nearest edge of its own chunk.

    A word near a chunk's seam (small distance) was likely cut off; the copy
    from the chunk where the same word sits deeper is the trustworthy one.
    """
    center = (tok.start_ms + tok.end_ms) // 2
    return min(center - chunk_start, chunk_end - center)


def stitch(chunks: list[ChunkTokens], iou_threshold: float = 0.5,
           seam_window_ms: int = 1000) -> list[RecognizedToken]:
    """Merge per-chunk token streams, dropping duplicates in overlap windows.

    Two tokens from *different* chunks that share text (exactly, or per
    ``_fuzzy_same_word`` — different sub-word split points over the same
    speech, see issue #8) and either overlap by at least ``iou_threshold`` or
    are centre-coincident (see ``_coincident`` — this is what catches sub-word
    and zero-length Thai pieces) are the same word seen twice; keep the copy
    more interior to its own chunk, tie-breaking on confidence then text
    length.

    A duplicate is searched for among ALL recently-kept tokens whose span ends
    within ``seam_window_ms`` of the candidate's start — not just the single
    most recent one — so an A-B-A' pattern (the two copies of the same word
    separated in the sorted stream by an intervening token from the other
    chunk) still dedupes. Pass the active chunk overlap (e.g. config
    ``chunk_overlap_ms``) as ``seam_window_ms`` so the search covers exactly
    the zone where a word can legitimately appear twice.
    """
    # Flatten, tagging each token with its chunk's identity and span.
    tagged: list[tuple[RecognizedToken, int, int, int]] = []
    for ci, ch in enumerate(chunks):
        for tok in ch.tokens:
            tagged.append((tok, ci, ch.start_ms, ch.end_ms))
    tagged.sort(key=lambda t: (t[0].start_ms, t[0].end_ms))

    kept: list[tuple[RecognizedToken, int, int, int]] = []
    dropped = 0
    for cand in tagged:
        tok, ci, cs, ce = cand
        # Scan recently-kept tokens newest-first; stop once a kept token ended
        # more than seam_window_ms before the candidate starts — anything that
        # far back can no longer overlap enough to be the same word. (Word
        # tokens are short, so start-order ≈ end-order within a window.)
        dup_idx = None
        for i in range(len(kept) - 1, -1, -1):
            ptok, pci, pcs, pce = kept[i]
            if tok.start_ms - ptok.end_ms > seam_window_ms:
                break
            exact = tok.text.strip() == ptok.text.strip()
            fuzzy = not exact and _fuzzy_same_word(tok, ptok)
            same_word = ci != pci and (exact or fuzzy)
            # Either test is sufficient: IoU for word-length tokens, centre
            # coincidence for the sub-word/zero-length pieces IoU cannot see.
            # Purely additive — this can only ever dedupe more, never less.
            if same_word and (_iou(tok, ptok) >= iou_threshold
                              or _coincident(tok, ptok)):
                if fuzzy:
                    # _FUZZY_FRAGMENT_MAX_MS is calibrated from one cited
                    # example, not a measured distribution (see the constant's
                    # comment) — this line is what lets a real job's log
                    # supply that data instead of another guess.
                    logger.debug(
                        "Fuzzy seam dedup: %r (%dms) <-> %r (%dms)",
                        tok.text, tok.end_ms - tok.start_ms,
                        ptok.text, ptok.end_ms - ptok.start_ms,
                    )
                dup_idx = i
                break
        if dup_idx is not None:
            if _prefer(cand, kept[dup_idx]):
                kept[dup_idx] = cand
            dropped += 1
            continue
        kept.append(cand)

    if dropped:
        logger.info("Stitch removed %d duplicate tokens across chunk seams", dropped)
    # An interior replacement can nudge a kept token's start past its successor's;
    # re-sort so the output stream stays time-ordered.
    kept.sort(key=lambda t: (t[0].start_ms, t[0].end_ms))
    return [t[0] for t in kept]


def _prefer(cand, incumbent) -> bool:
    """True if the candidate should replace the incumbent duplicate."""
    ctok, _, ccs, cce = cand
    itok, _, ics, ice = incumbent
    ci = _interiority(ctok, ccs, cce)
    ii = _interiority(itok, ics, ice)
    if ci != ii:
        return ci > ii
    cc = ctok.confidence if ctok.confidence is not None else -1.0
    ic = itok.confidence if itok.confidence is not None else -1.0
    if cc != ic:
        return cc > ic
    return len(ctok.text) > len(itok.text)
