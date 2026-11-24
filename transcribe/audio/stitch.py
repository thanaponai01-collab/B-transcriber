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
_COINCIDENT_MS = 60
_COINCIDENT_DUR_FRAC = 0.6

_MIN_FUZZY_OVERLAP = 2
_FUZZY_FRAGMENT_MAX_MS = 80


def _fuzzy_same_word(a: RecognizedToken, b: RecognizedToken) -> bool:
    at, bt = a.text.strip(), b.text.strip()
    if not at or not bt or at == bt:
        return False
    if len(at) < _MIN_FUZZY_OVERLAP or len(bt) < _MIN_FUZZY_OVERLAP:
        return False
    if at in bt or bt in at:
        overlaps = True
    else:
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
    centre_a = (a.start_ms + a.end_ms) / 2
    centre_b = (b.start_ms + b.end_ms) / 2
    mean_dur = ((a.end_ms - a.start_ms) + (b.end_ms - b.start_ms)) / 2
    tol = max(_COINCIDENT_MS, _COINCIDENT_DUR_FRAC * mean_dur)
    return abs(centre_a - centre_b) <= tol


def _interiority(tok: RecognizedToken, chunk_start: int, chunk_end: int) -> int:
    center = (tok.start_ms + tok.end_ms) // 2
    return min(center - chunk_start, chunk_end - center)


_SEAM_BOUNDARY_TOL_MS = 120
_MAX_PIECE_MS = 1500


def _seam_between(a: ChunkTokens, b: ChunkTokens, tol_ms: int) -> int | None:
    lo, hi = b.start_ms, a.end_ms
    if hi <= lo:
        return None
    a_stretch = [t.start_ms for t in a.tokens if t.end_ms > lo and t.end_ms - t.start_ms > _MAX_PIECE_MS]
    b_stretch = [t.end_ms for t in b.tokens if t.start_ms < hi and t.end_ms - t.start_ms > _MAX_PIECE_MS]
    if a_stretch:
        hi = max(lo, min(hi, min(a_stretch)))
    if b_stretch:
        lo = min(hi, max(lo, max(b_stretch)))
    mid = (lo + hi) // 2
    a_bounds = sorted({t.end_ms for t in a.tokens if lo <= t.end_ms <= hi})
    b_bounds = [x for t in b.tokens for x in (t.start_ms, t.end_ms) if lo <= x <= hi]
    shared = [x for x in a_bounds if any(abs(x - y) <= tol_ms for y in b_bounds)]
    pool = shared or a_bounds
    return min(pool, key=lambda x: abs(x - mid)) if pool else mid


def cut_seams(chunks: list[ChunkTokens], tol_ms: int = _SEAM_BOUNDARY_TOL_MS) -> list[ChunkTokens]:
    """Trim consecutive overlapping chunks so each token is owned by one chunk.

    A chunk keeps tokens whose centre lies between its two seams (the left seam
    with the previous chunk, the right seam with the next). Non-overlapping
    neighbours get no seam, so their tokens are untouched. Returns new
    ChunkTokens; the inputs are not modified. Run ``stitch`` on the result to
    mop up any token that still straddles a seam."""
    order = sorted(range(len(chunks)), key=lambda i: chunks[i].start_ms)
    seams = [_seam_between(chunks[order[k]], chunks[order[k + 1]], tol_ms)
             for k in range(len(order) - 1)]
    out: list[ChunkTokens | None] = [None] * len(chunks)
    for k, i in enumerate(order):
        left = seams[k - 1] if k > 0 else None
        right = seams[k] if k < len(seams) else None
        keep = [t for t in chunks[i].tokens
                if (left is None or (t.start_ms + t.end_ms) / 2 >= left)
                and (right is None or (t.start_ms + t.end_ms) / 2 < right)]
        out[i] = ChunkTokens(keep, chunks[i].start_ms, chunks[i].end_ms)
    return out


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
    tagged: list[tuple[RecognizedToken, int, int, int]] = []
    for ci, ch in enumerate(chunks):
        for tok in ch.tokens:
            tagged.append((tok, ci, ch.start_ms, ch.end_ms))
    tagged.sort(key=lambda t: (t[0].start_ms, t[0].end_ms))

    kept: list[tuple[RecognizedToken, int, int, int]] = []
    dropped = 0
    for cand in tagged:
        tok, ci, cs, ce = cand
        dup_idx = None
        for i in range(len(kept) - 1, -1, -1):
            ptok, pci, pcs, pce = kept[i]
            if tok.start_ms - ptok.end_ms > seam_window_ms:
                break
            exact = tok.text.strip() == ptok.text.strip()
            fuzzy = not exact and _fuzzy_same_word(tok, ptok)
            same_word = ci != pci and (exact or fuzzy)
            if same_word and (_iou(tok, ptok) >= iou_threshold
                              or _coincident(tok, ptok)):
                if fuzzy:
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
    kept.sort(key=lambda t: (t[0].start_ms, t[0].end_ms))
    return [t[0] for t in kept]


def _prefer(cand, incumbent) -> bool:
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
