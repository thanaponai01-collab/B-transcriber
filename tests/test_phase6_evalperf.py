"""Phase 6 acceptance — eval perf + hygiene (rapidfuzz, align linearization).

Run: python -m pytest tests/test_phase6_evalperf.py -v
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.contracts import RecognizedToken
from transcribe.pipeline import align_hyp


# ── 6.1 rapidfuzz edit distance matches the pure-Python fallback ──────────────

def test_edit_distance_matches_pure_python():
    from transcribe.eval.metrics import _edit_distance, _edit_distance_py
    cases = [
        ("kitten", "sitting"),
        ("", "abc"),
        ("สวัสดีครับ", "สวัสดีคระ"),
        (["a", "b", "c"], ["a", "x", "c"]),
    ]
    for ref, hyp in cases:
        assert _edit_distance(ref, hyp) == _edit_distance_py(ref, hyp)


# ── 6.3 windowed align == brute-force align on random token sets ──────────────

def _brute_align(tokens_a, tokens_b):
    """Reference implementation: the pre-linearization O(A×B) full scan."""
    from transcribe.pipeline.align_hyp import _token_overlap_ms, _score, AlignSlot, _MATCH_PROX_MS
    if not tokens_a and not tokens_b:
        return []
    matched_b = set()
    pairs = []
    for ta in tokens_a:
        best_j, best_score = -1, -1.0
        for j, tb in enumerate(tokens_b):
            if j in matched_b:
                continue
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
    for j, tb in enumerate(tokens_b):
        if j not in matched_b:
            pairs.append((None, tb))
    slots = [AlignSlot([ta] if ta else [], [tb] if tb else []) for ta, tb in pairs]
    slots.sort(key=lambda s: min((t.start_ms for t in s.candidates_a + s.candidates_b), default=0))
    return slots


def _rand_tokens(n, rng):
    vocab = ["โอเค", "ครับ", "hello", "world", "นะ", "AI", "test"]
    toks = []
    t = 0
    for _ in range(n):
        t += rng.randint(0, 800)
        dur = rng.randint(200, 6000)  # realistic ASR cue durations
        toks.append(RecognizedToken(rng.choice(vocab), t, t + dur, 0.9, "thai"))
        t += dur
    return toks


def _key(slots):
    return [
        ([(t.text, t.start_ms) for t in s.candidates_a],
         [(t.text, t.start_ms) for t in s.candidates_b])
        for s in slots
    ]


def test_windowed_align_equals_bruteforce():
    rng = random.Random(1234)
    for _ in range(200):
        a = _rand_tokens(rng.randint(0, 12), rng)
        b = _rand_tokens(rng.randint(0, 12), rng)
        assert _key(align_hyp.align(a, b)) == _key(_brute_align(a, b))
