"""Phase 4 — Hypothesis-to-hypothesis alignment.

Aligns two engine output sequences into comparison slots before reconciliation.
Each slot holds zero or more candidate tokens from Engine A and Engine B.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from transcribe.contracts import RecognizedToken


# Two tokens may only be matched if they are temporally near. Without this, two
# identical common words far apart in the file (e.g. "โอเค" … "โอเค") match on text
# alone, and reconcile's agreement-merge stretches one token across the whole file.
_MATCH_PROX_MS = 1500


@dataclass
class AlignSlot:
    candidates_a: list[RecognizedToken] = field(default_factory=list)
    candidates_b: list[RecognizedToken] = field(default_factory=list)


def _token_overlap_ms(a: RecognizedToken, b: RecognizedToken) -> int:
    """Millisecond overlap between two tokens' time spans."""
    return max(0, min(a.end_ms, b.end_ms) - max(a.start_ms, b.start_ms))


def _text_sim(a: str, b: str) -> float:
    """Simple character-level Jaccard similarity."""
    if not a and not b:
        return 1.0
    sa, sb = set(a.lower()), set(b.lower())
    if not sa | sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _score(a: RecognizedToken, b: RecognizedToken) -> float:
    """Higher = better alignment candidate pair."""
    overlap = _token_overlap_ms(a, b)
    duration_a = max(1, a.end_ms - a.start_ms)
    duration_b = max(1, b.end_ms - b.start_ms)
    overlap_ratio = overlap / max(duration_a, duration_b)
    sim = _text_sim(a.text, b.text)
    return 0.6 * overlap_ratio + 0.4 * sim


def align(
    tokens_a: list[RecognizedToken],
    tokens_b: list[RecognizedToken],
) -> list[AlignSlot]:
    """
    Align two hypothesis sequences into comparison slots.

    Strategy:
    1. For each token in A, find the best-scoring token in B (by timestamp
       overlap + text similarity) that hasn't been matched yet.
    2. Unmatched tokens become solo slots.
    3. Slots are sorted by the minimum start_ms of their tokens.
    """
    if not tokens_a and not tokens_b:
        return []

    matched_b: set[int] = set()
    pairs: list[tuple[RecognizedToken, RecognizedToken | None]] = []

    for ta in tokens_a:
        best_j, best_score = -1, -1.0
        for j, tb in enumerate(tokens_b):
            if j in matched_b:
                continue
            # Temporal gate: only match tokens that overlap or sit close in time.
            if _token_overlap_ms(ta, tb) == 0 and abs(ta.start_ms - tb.start_ms) > _MATCH_PROX_MS:
                continue
            s = _score(ta, tb)
            if s > best_score:
                best_score, best_j = s, j
        if best_j >= 0 and best_score > 0.1:
            matched_b.add(best_j)
            pairs.append((ta, tokens_b[best_j]))
        else:
            pairs.append((ta, None))

    # Unmatched B tokens become solo slots
    for j, tb in enumerate(tokens_b):
        if j not in matched_b:
            pairs.append((None, tb))

    # Build slots and sort by start time
    slots = []
    for ta, tb in pairs:
        slot = AlignSlot(
            candidates_a=[ta] if ta else [],
            candidates_b=[tb] if tb else [],
        )
        slots.append(slot)

    def slot_start(s: AlignSlot) -> int:
        all_tokens = s.candidates_a + s.candidates_b
        return min((t.start_ms for t in all_tokens), default=0)

    slots.sort(key=slot_start)
    return slots
