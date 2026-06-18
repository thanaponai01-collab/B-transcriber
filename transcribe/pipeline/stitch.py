"""GAP-4 — overlap-aware chunk stitching.

Per-chunk transcription with offset-to-global timestamps duplicates (or
truncates) words wherever chunks overlap — and chunks *should* overlap ~0.5–1 s
so words are not lost at the boundaries. This module merges per-chunk token
streams back into one, removing the duplicates the overlap introduces.

Runs after each engine, before align_hyp. Pure timestamp/text logic — no model,
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


def _interiority(tok: RecognizedToken, chunk_start: int, chunk_end: int) -> int:
    """Distance from a token's centre to the nearest edge of its own chunk.

    A word near a chunk's seam (small distance) was likely cut off; the copy
    from the chunk where the same word sits deeper is the trustworthy one.
    """
    center = (tok.start_ms + tok.end_ms) // 2
    return min(center - chunk_start, chunk_end - center)


def stitch(chunks: list[ChunkTokens], iou_threshold: float = 0.5) -> list[RecognizedToken]:
    """Merge per-chunk token streams, dropping duplicates in overlap windows.

    Two tokens from *different* chunks that share text and overlap by at least
    ``iou_threshold`` are the same word seen twice; keep the copy more interior
    to its own chunk, tie-breaking on confidence then text length.
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
        if kept:
            ptok, pci, pcs, pce = kept[-1]
            same_word = tok.text.strip() == ptok.text.strip() and ci != pci
            if same_word and _iou(tok, ptok) >= iou_threshold:
                if _prefer(cand, kept[-1]):
                    kept[-1] = cand
                dropped += 1
                continue
        kept.append(cand)

    if dropped:
        logger.info("Stitch removed %d duplicate tokens across chunk seams", dropped)
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
