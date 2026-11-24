from __future__ import annotations

import logging

from transcribe.cues.policy import CuePolicy
from transcribe.thai.atoms import (
    CLAUSE_CLOSERS,
    DANGLING_ENDS,
    LEADING_CONNECTIVES,
    NON_OPENERS,
    STRONG_OPENERS,
    TRAILING_PARTICLES,
    WEAK_OPENERS,
)

logger = logging.getLogger(__name__)

_DP_UNDERSHOOT_WEIGHT = 0.08
_DP_OVERSHOOT_WEIGHT = 2.0
_DP_SPACE_DISCOUNT = 50.0
_DP_OVERFLOW_UNIT_MS = 100
_DP_OVERFLOW_WEIGHT = 4.0
_DP_RUNT_PENALTY = 1_000_000.0

_PARTICLE_OVERSHOOT_MS = 500
_PARTICLE_OVERSHOOT_CHARS = 8


def split_cues(words, policy: CuePolicy | None = None, *, return_words: bool = False):
    """Group word pieces into subtitle-length phrase cues.

    `words`: list of (text, start_ms, end_ms, confidence) — confidence is the
    source word-piece's probability, or None if the engine didn't report one.

    `policy`: a `CuePolicy`. Omitted means the production defaults.

    Returns list of (text, start_ms, end_ms, confidence) — confidence is the mean
    of the constituent atoms' probabilities, or None if none carried one.
    """
    policy = policy or CuePolicy()
    if policy.algorithm == "dp":
        return _split_dp(words, policy, return_words=return_words)
    if policy.algorithm == "clause":
        return _split_clause(words, policy, return_words=return_words)
    return _split_greedy(words, policy, return_words=return_words)


_CLAUSE_PAUSE_MS = 100
_CLAUSE_W_PAUSE = 2.0
_CLAUSE_W_SPACE = 2.0
_CLAUSE_W_CLOSER = 1.5
_CLAUSE_W_STRONG_OPENER = 2.0
_CLAUSE_W_WEAK_OPENER = 1.2
_CLAUSE_W_NON_OPENER = -1.5
_CLAUSE_W_DANGLING = -2.0
_CLAUSE_LONG_CHARS = 26
_CLAUSE_SPLIT_EVIDENCE = 3.0
_CLAUSE_MIN_CHARS = 8
_CLAUSE_MIN_MS = 500
_CLAUSE_MOVE_GAIN = 2.5


def _clause_evidence(left, right, space_between: bool) -> float:
    lt, rt = left[0].strip(), right[0].strip()
    score = 0.0
    if right[1] - left[2] >= _CLAUSE_PAUSE_MS:
        score += _CLAUSE_W_PAUSE
    if space_between:
        score += _CLAUSE_W_SPACE
    if lt.endswith(tuple(TRAILING_PARTICLES)):
        score += _CLAUSE_W_CLOSER
    if rt in STRONG_OPENERS:
        score += _CLAUSE_W_STRONG_OPENER
    elif rt in WEAK_OPENERS:
        score += _CLAUSE_W_WEAK_OPENER
    elif rt in NON_OPENERS:
        score += _CLAUSE_W_NON_OPENER
    if lt in DANGLING_ENDS:
        score += _CLAUSE_W_DANGLING
    return score


def _split_clause(words, policy: CuePolicy, *, return_words: bool = False):
    cues, sub_words = _split_greedy(words, policy, return_words=True)
    timed, boundary_offsets = _prepare(words, policy)
    if not cues or timed is None:
        return (cues, sub_words) if return_words else cues

    real = [k for k, tok in enumerate(timed) if tok[0].strip()]
    chars = [len("".join(timed[k][0].split())) for k in real]
    sentence_start = set()
    b = 0
    for i, k in enumerate(real):
        while b < len(boundary_offsets) and timed[k][4] >= boundary_offsets[b]:
            sentence_start.add(i)
            b += 1

    ends, i = [], 0
    for text, *_ in cues:
        need = len("".join(text.split()))
        while need > 0 and i < len(real):
            need -= chars[i]
            i += 1
        ends.append(i)
    if ends[-1] != len(real) or any(a >= c for a, c in zip([0] + ends, ends)):
        logger.warning("clause split: could not map cues to atoms; keeping the greedy split")
        return (cues, sub_words) if return_words else cues

    def evidence(i: int) -> float:
        return _clause_evidence(timed[real[i - 1]], timed[real[i]], real[i] - real[i - 1] > 1)

    def fixed(i: int) -> bool:
        return i in sentence_start or timed[real[i]][1] - timed[real[i - 1]][2] >= policy.gap_ms

    def size(a: int, c: int) -> int:
        return sum(chars[a:c])

    def span(a: int, c: int) -> int:
        return timed[real[c - 1]][2] - timed[real[a]][1]

    def fits(a: int, c: int, limit_chars: int) -> bool:
        return (_CLAUSE_MIN_CHARS <= size(a, c) <= limit_chars
                and _CLAUSE_MIN_MS <= span(a, c) <= policy.target_ms + _PARTICLE_OVERSHOOT_MS)

    limit = policy.target_chars + _PARTICLE_OVERSHOOT_CHARS

    starts = [0] + ends[:-1]
    for n in range(1, len(starts)):
        at, lo, hi = starts[n], starts[n - 1], ends[n]
        if fixed(at):
            continue
        best, best_score = at, evidence(at) + _CLAUSE_MOVE_GAIN
        for cand in range(lo + 1, hi):
            if cand == at or any(fixed(j) for j in range(min(cand, at) + 1, max(cand, at) + 1)):
                continue
            if evidence(cand) > best_score and fits(lo, cand, limit) and fits(cand, hi, limit):
                best, best_score = cand, evidence(cand)
        starts[n] = best
        ends[n - 1] = best

    def split_long(a: int, c: int) -> list[int]:
        if size(a, c) <= _CLAUSE_LONG_CHARS:
            return [c]
        best, best_score = None, _CLAUSE_SPLIT_EVIDENCE
        for cand in range(a + 1, c):
            if (size(a, cand) < _CLAUSE_MIN_CHARS or size(cand, c) < _CLAUSE_MIN_CHARS
                    or span(a, cand) < _CLAUSE_MIN_MS or span(cand, c) < _CLAUSE_MIN_MS):
                continue
            if evidence(cand) >= best_score:
                if best is None or evidence(cand) > best_score or (
                        abs(size(a, cand) - size(cand, c)) < abs(size(a, best) - size(best, c))):
                    best, best_score = cand, evidence(cand)
        if best is None:
            return [c]
        return split_long(a, best) + split_long(best, c)

    new_ends: list[int] = []
    for a, c in zip(starts, ends):
        new_ends.extend(split_long(a, c))

    out: list[tuple[str, int, int, float | None]] = []
    a = 0
    for c in new_ends:
        lo, hi = real[a], real[c - 1]
        text = "".join(tok[0] for tok in timed[lo:hi + 1]).strip()
        confs = [tok[3] for tok in timed[lo:hi + 1] if tok[3] is not None]
        out.append((text, timed[lo][1], timed[hi][2], sum(confs) / len(confs) if confs else None))
        a = c
    return (out, sub_words) if return_words else out


def _sentence_boundary_offsets(text: str) -> list[int]:
    try:
        from pythainlp.tokenize import sent_tokenize
        sentences = sent_tokenize(text, engine="crfcut", keep_whitespace=True)
    except Exception:
        logger.warning("Sentence tokenization unavailable — cues will not be "
                        "forced to start on sentence boundaries", exc_info=True)
        return []
    offsets = []
    pos = 0
    for sent in sentences:
        if pos:
            offsets.append(pos)
        pos += len(sent)
    return offsets


def _prepare(words, policy: CuePolicy, *, return_words: bool = False):
    from cutdeck.words import timed_tokens, Word
    from transcribe.thai.atoms import default_lexicon, glue_atoms, snap_boundary_offsets

    def pause_runs(items, max_gap_ms):
        runs, prev_end = [], None
        for item in items:
            if prev_end is None or item[1] - prev_end >= max_gap_ms:
                runs.append([])
            runs[-1].append(item)
            prev_end = item[2]
        return runs

    full_text, raw_timed = "", []
    for run in pause_runs(words, policy.gap_ms):
        run_text, run_timed = timed_tokens(run)
        raw_timed += [(t, s, e, c, p + len(full_text)) for t, s, e, c, p in run_timed]
        full_text += run_text
    if not full_text:
        return (None, None, []) if return_words else (None, None)

    lexicon = policy.lexicon or default_lexicon({})
    timed = []
    for run in pause_runs(raw_timed, policy.target_ms):
        offset = run[0][4]
        local = [(t, s, e, c, p - offset) for t, s, e, c, p in run]
        timed += [(t, s, e, c, p + offset) for t, s, e, c, p in glue_atoms(local, lexicon)]

    boundary_offsets = snap_boundary_offsets(_sentence_boundary_offsets(full_text), timed)
    if return_words:
        sub_words = [Word(t, s, e, conf) for t, s, e, conf, _pos in raw_timed if t.strip()]
        return timed, boundary_offsets, sub_words
    return timed, boundary_offsets


def _split_greedy(words, policy: CuePolicy, *, return_words: bool = False):
    """Whisper word-pieces for spaceless Thai are sub-word and only sporadically
    carry a leading space, so they cannot be used to find word boundaries — a
    long spaceless run would never break."""
    gap_ms = policy.gap_ms
    target_ms = policy.target_ms
    target_chars = policy.target_chars
    space_min_chars = policy.space_min_chars
    space_min_ms = policy.space_min_ms

    if return_words:
        timed, boundary_offsets, sub_words = _prepare(words, policy, return_words=True)
    else:
        timed, boundary_offsets = _prepare(words, policy)
        sub_words = []
    if timed is None:
        return ([], []) if return_words else []
    boundary_idx = 0

    cues: list[tuple[str, int, int, float | None]] = []
    cur: list[tuple[str, int, int, float | None]] = []
    pending_ws: list[tuple[str, int, int, float | None]] = []

    def _close():
        text = "".join(x[0] for x in cur).strip()
        if text:
            confs = [x[3] for x in cur if x[3] is not None]
            conf = sum(confs) / len(confs) if confs else None
            cues.append((text, cur[0][1], cur[-1][2], conf))

    def _cue_so_far() -> tuple[int, int]:
        if not cur:
            return 0, 0
        return len("".join(x[0] for x in cur).strip()), cur[-1][2] - cur[0][1]

    def _remainder_stands_alone(i: int) -> bool:
        chars, first_start, last_end = 0, None, None
        for t2, s2, e2, _conf2, _pos2 in timed[i + 1:]:
            if not t2.strip():
                break
            if last_end is not None and s2 - last_end >= gap_ms:
                break
            if first_start is None:
                first_start = s2
            chars += len(t2.strip())
            last_end = e2
            if chars >= target_chars:
                return True
        if first_start is None:
            return False
        return chars >= space_min_chars and (last_end - first_start) >= space_min_ms

    def _short_tail_fits(i: int) -> bool:
        first_start = timed[i][1]
        last_end = first_start
        chars = 0
        next_boundary = (boundary_offsets[boundary_idx]
                         if boundary_idx < len(boundary_offsets) else None)
        for j in range(i, len(timed)):
            text, start, end, _conf, pos = timed[j]
            if not text.strip():
                continue
            if chars and ((next_boundary is not None and pos >= next_boundary)
                          or start - last_end >= gap_ms):
                break
            chars += len(text)
            last_end = end
            if chars > 8 or last_end - first_start >= 500:
                return False
        return (chars > 0
                and _cue_so_far()[0] + chars <= target_chars + 8
                and last_end - cur[0][1] <= target_ms + 500)

    for i, (t, s, e, conf, char_pos) in enumerate(timed):
        if not t.strip():
            if not cur:
                continue
            n_chars, span = _cue_so_far()
            if (n_chars >= space_min_chars and span >= space_min_ms
                    and _remainder_stands_alone(i)):
                _close()
                cur = []
                pending_ws = []
            else:
                pending_ws.append((t, s, e, conf))
            continue
        new_sentence = False
        while boundary_idx < len(boundary_offsets) and char_pos >= boundary_offsets[boundary_idx]:
            new_sentence = True
            boundary_idx += 1
        if cur:
            gap = s - cur[-1][2]
            span = e - cur[0][1]
            n_chars = len("".join(x[0] for x in cur).strip())
            wants_break = new_sentence or gap >= gap_ms or span > target_ms or n_chars >= target_chars
            if (wants_break and not new_sentence and gap < gap_ms
                    and _short_tail_fits(i)):
                wants_break = False
            if (wants_break and not new_sentence and gap < gap_ms
                    and t.strip() in TRAILING_PARTICLES
                    and span <= target_ms + _PARTICLE_OVERSHOOT_MS
                    and n_chars <= target_chars + _PARTICLE_OVERSHOOT_CHARS):
                wants_break = False
            if (not wants_break and not new_sentence
                    and t.strip() in LEADING_CONNECTIVES
                    and "".join(x[0] for x in cur).rstrip().endswith(tuple(CLAUSE_CLOSERS))
                    and n_chars >= space_min_chars and span >= space_min_ms):
                wants_break = True
            if wants_break:
                _close()
                cur = []
        if cur:
            cur.extend(pending_ws)
        pending_ws = []
        cur.append((t, s, e, conf))
    if cur:
        _close()
    if return_words:
        return cues, sub_words
    return cues


def _dp_split_segment(timed, real_idx, seg_start, seg_end,
                       target_ms, target_chars, min_chars, min_ms):
    n_words = seg_end - seg_start

    candidates = list(range(n_words + 1))

    def had_whitespace_before(c) -> bool:
        if c <= 0 or c >= n_words:
            return False
        return real_idx[seg_start + c] - real_idx[seg_start + c - 1] > 1

    def cue_text(a, c):
        lo = real_idx[seg_start + a]
        hi = real_idx[seg_start + c - 1]
        return "".join(tok[0] for tok in timed[lo:hi + 1]).strip()

    def cue_span(a, c):
        lo = real_idx[seg_start + a]
        hi = real_idx[seg_start + c - 1]
        return len(cue_text(a, c)), timed[lo][1], timed[hi][2]

    dp = {0: 0.0}
    back = {}
    for c in candidates:
        if c == 0:
            continue
        best_cost, best_a = float("inf"), None
        for a in candidates:
            if a not in dp or a >= c:
                continue
            chars, start_ms, end_ms = cue_span(a, c)
            span_ms = end_ms - start_ms
            if chars > target_chars:
                size_cost = ((chars - target_chars) ** 2) * _DP_OVERSHOOT_WEIGHT
            else:
                size_cost = (target_chars - chars) * _DP_UNDERSHOOT_WEIGHT
            overflow_ms = max(0, span_ms - target_ms)
            overflow_cost = ((overflow_ms // _DP_OVERFLOW_UNIT_MS) ** 2) * _DP_OVERFLOW_WEIGHT
            viable = (chars >= min_chars and span_ms >= min_ms) or chars >= target_chars
            runt_cost = 0.0 if viable else _DP_RUNT_PENALTY
            discount = _DP_SPACE_DISCOUNT if had_whitespace_before(c) else 0.0
            cost = dp[a] + size_cost + overflow_cost + runt_cost - discount
            if cost < best_cost:
                best_cost, best_a = cost, a
        dp[c] = best_cost
        back[c] = best_a

    breaks = []
    c = n_words
    while c != 0:
        a = back[c]
        breaks.append((a, c))
        c = a
    breaks.reverse()

    cues: list[tuple[str, int, int, float | None]] = []
    for a, c in breaks:
        lo = real_idx[seg_start + a]
        hi = real_idx[seg_start + c - 1]
        text = cue_text(a, c)
        if not text:
            continue
        confs = [tok[3] for tok in timed[lo:hi + 1] if tok[3] is not None]
        conf = sum(confs) / len(confs) if confs else None
        cues.append((text, timed[lo][1], timed[hi][2], conf))
    return cues


def _split_dp(words, policy: CuePolicy, *, return_words: bool = False):
    gap_ms = policy.gap_ms

    if return_words:
        timed, boundary_offsets, sub_words = _prepare(words, policy, return_words=True)
    else:
        timed, boundary_offsets = _prepare(words, policy)
        sub_words = []
    if timed is None:
        return ([], []) if return_words else []

    real_idx = [k for k, tok in enumerate(timed) if tok[0].strip()]
    if not real_idx:
        return ([], []) if return_words else []

    hard_splits = {0, len(real_idx)}
    b_idx = 0
    for p in range(1, len(real_idx)):
        k = real_idx[p]
        char_pos = timed[k][4]
        crossed = False
        while b_idx < len(boundary_offsets) and char_pos >= boundary_offsets[b_idx]:
            crossed = True
            b_idx += 1
        if crossed:
            hard_splits.add(p)
            continue
        prev_k = real_idx[p - 1]
        if timed[k][1] - timed[prev_k][2] >= gap_ms:
            hard_splits.add(p)
    hard_splits = sorted(hard_splits)

    cues: list[tuple[str, int, int, float | None]] = []
    for seg_start, seg_end in zip(hard_splits, hard_splits[1:]):
        cues.extend(_dp_split_segment(timed, real_idx, seg_start, seg_end,
                                       policy.target_ms, policy.target_chars,
                                       policy.space_min_chars, policy.space_min_ms))
    if return_words:
        return cues, sub_words
    return cues
