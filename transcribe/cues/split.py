"""Cue splitting — word pieces in, subtitle-grade cues out.

Lifted verbatim out of `transcribe/engines/faster_whisper.py`, where it lived
interleaved with CUDA DLL loading, batched-decode OOM halving and VAD windowing
despite touching none of them: the input is a list of (text, start_ms, end_ms,
confidence) word pieces and the output is cues. Nothing here knows what produced
the words, so any whole-file engine can reuse it without importing a rival
adapter's privates.

This module must not import from `transcribe/engines/` — that direction is what
the Engine Contract forbids, and it is what the extraction exists to make true in
fact rather than only in documentation.

Public interface is exactly one function: `split_cues(words, policy)`. The greedy
and DP strategies below are an internal seam selected by `policy.algorithm`, not
public surface.
"""

from __future__ import annotations

import logging

from transcribe.cues.policy import CuePolicy

logger = logging.getLogger(__name__)

# DP cost weights (_split_dp). Initial heuristics, not tuned — same "principled
# floors, not tuned values" status as the greedy knobs in policy.py until the
# harness has an opinion. Size cost is deliberately asymmetric: quadratic once a
# cue exceeds target_chars (mirrors the greedy path's hard "close it now" trigger
# — an oversized cue gets punished hard), but only mildly linear when a cue
# undershoots (measured 2026-08-04: a symmetric quadratic here made DP prefer
# merging toward the target from BOTH directions, producing *fewer, longer* cues
# than the hand-recut references want — cue_boundary_error_rate regressed 0.3590
# -> 0.4554 vs the greedy baseline on the first probe. The gold set wants more,
# shorter cues, i.e. undershoot should be nearly free). A Whisper-emitted space is
# worth discounting like a ~7-char improvement; overflowing target_ms by a full
# extra second costs as much as a wildly oversized cue.
#
# Private by design: these are not a caller's concern and must not be promoted to
# the public policy.
_DP_UNDERSHOOT_WEIGHT = 0.08
_DP_OVERSHOOT_WEIGHT = 2.0
_DP_SPACE_DISCOUNT = 50.0
_DP_OVERFLOW_UNIT_MS = 100
_DP_OVERFLOW_WEIGHT = 4.0
_DP_RUNT_PENALTY = 1_000_000.0


def split_cues(words, policy: CuePolicy | None = None):
    """Group word pieces into subtitle-length phrase cues.

    `words`: list of (text, start_ms, end_ms, confidence) — confidence is the
    source word-piece's probability, or None if the engine didn't report one.

    `policy`: a `CuePolicy`. Omitted means the production defaults.

    Returns list of (text, start_ms, end_ms, confidence) — confidence is the mean
    of the constituent atoms' probabilities, or None if none carried one.

    Dispatches to one of two cue-boundary strategies (HANDOFF_CEILING_BREAK §5):
    the original greedy fill (default, unchanged — see `_split_greedy`) or the
    cost-minimising DP split (`policy.algorithm == "dp"`, see `_split_dp`). Kept
    as separate functions rather than branching deep inside one, so the greedy
    path stays provably untouched while the DP path is probed via `--experiment`
    per the handoff's A/B discipline. `config.yaml`'s
    `engines.faster_whisper.cue_split_algorithm` is the switch; delete the loser
    once the harness decides (handoff §5: "keep the greedy path behind a config
    flag for one release for A/B, then delete").
    """
    policy = policy or CuePolicy()
    if policy.algorithm == "dp":
        return _split_dp(words, policy)
    return _split_greedy(words, policy)


def _sentence_boundary_offsets(text: str) -> list[int]:
    """Character offsets in `text` where pythainlp's crfcut model believes a new
    sentence begins (offset 0 excluded — the first token always starts a cue
    regardless). crfcut is a CRF trained to segment *unpunctuated* running
    text, which is what Whisper's raw Thai output is (no periods/commas) —
    this is the intended use case, not a punctuation-based fallback.
    Best-effort: any failure (missing optional dependency, model fetch
    issue) degrades to no forced sentence breaks rather than raising, since
    the gap/length heuristics below still produce usable cues on their own.
    """
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


def _prepare(words, policy: CuePolicy):
    """Shared front half of both algorithms: rebuild the per-character timeline,
    glue break-atoms, and locate crfcut sentence starts in the glued coordinates.

    Returns (timed, boundary_offsets), or (None, None) when there is no text.
    """
    from cutdeck.words import timed_tokens
    from transcribe.thai.atoms import default_lexicon, glue_atoms, snap_boundary_offsets

    # 1-3. per-character timeline -> real word boundaries -> mapped time spans.
    # Shared with cutdeck/words.py (CutDeck Phase 1) so there is exactly one
    # implementation of Thai word-timeline reconstruction, not two.
    full_text, raw_timed = timed_tokens(words)
    if not full_text:
        return None, None

    # 3.5. glue bound units into atoms before any break decision runs.
    timed = glue_atoms(raw_timed, policy.lexicon or default_lexicon({}))

    # sentence-start offsets in the same char coordinates as `timed`.
    boundary_offsets = snap_boundary_offsets(_sentence_boundary_offsets(full_text), timed)
    return timed, boundary_offsets


def _split_greedy(words, policy: CuePolicy):
    """Group word pieces into subtitle-length phrase cues at real word boundaries.

    Whisper word-pieces for spaceless Thai are sub-word and only sporadically
    carry a leading space, so they cannot be used to find word boundaries — a
    long spaceless run would never break. Instead we rebuild the full text with
    a per-character timeline, segment it with pythainlp (Latin/whitespace
    preserved), glue the result into break-atoms (HANDOFF_THAI_BREAK_ATOMS.md —
    STYLE_GUIDE §7's unsplittable units, e.g. `ทะเลาะกัน`, `ผู้หญิงคนนั้น`,
    merged into one indivisible token), and group whole atoms into cues. Every
    boundary this loop can choose is therefore legal by construction — no veto
    check is needed at the break decision points below.

    A cue must never start mid-sentence: a long sentence can still be split into
    several cues (on a silence gap >= gap_ms, or once target_ms / target_chars is
    hit, same as before), but a cue break is also forced at every sentence
    boundary crfcut finds, so a cue never opens with the tail of one sentence
    fused to the head of the next. Sentence detection on raw ASR output (no
    punctuation, colloquial speech) is inherently imperfect — treat it as a
    heuristic that reduces mid-sentence cue starts, not a guarantee. A boundary
    crfcut places inside an atom is snapped outward to the atom's start
    (`snap_boundary_offsets`) rather than treated as license to split it.

    A space Whisper itself emitted inside Thai is a third break signal (see
    CUE_SPACE_MIN_CHARS): it marks a breath/clause boundary the acoustic model
    heard, and breaking there beats breaking wherever the character budget
    happens to run out. It applies only once the cue holds space_min_chars AND
    space_min_ms, so short interjections stay whole.
    """
    gap_ms = policy.gap_ms
    target_ms = policy.target_ms
    target_chars = policy.target_chars
    space_min_chars = policy.space_min_chars
    space_min_ms = policy.space_min_ms

    timed, boundary_offsets = _prepare(words, policy)
    if timed is None:
        return []
    boundary_idx = 0

    # 4. greedy group whole atoms into cues. Whitespace atoms are buffered and only
    # kept once a real atom follows in the same cue, so a cue never starts or ends on
    # whitespace (a trailing space carries the next atom's timing and would corrupt
    # the cue's end time and the gap check).
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
        """(chars, span_ms) of the open cue — 0/0 when nothing is open."""
        if not cur:
            return 0, 0
        return len("".join(x[0] for x in cur).strip()), cur[-1][2] - cur[0][1]

    def _remainder_stands_alone(i: int) -> bool:
        """Would the text AFTER this space form a viable cue on its own?

        Breaking at a space only helps if both sides are viable — otherwise it
        trades one bad boundary for a flash-frame runt (a 140ms 'โอเค' cue was
        exactly this). Scans forward to wherever the next break would land
        anyway: the next space, the next real pause, or end of stream.
        """
        chars, first_start, last_end = 0, None, None
        for t2, s2, e2, _conf2, _pos2 in timed[i + 1:]:
            if not t2.strip():
                break                        # the next space closes the remainder
            if last_end is not None and s2 - last_end >= gap_ms:
                break                        # a real pause closes it
            if first_start is None:
                first_start = s2
            chars += len(t2.strip())
            last_end = e2
            if chars >= target_chars:
                return True                  # long enough on its own regardless
        if first_start is None:
            return False
        return chars >= space_min_chars and (last_end - first_start) >= space_min_ms

    for i, (t, s, e, conf, char_pos) in enumerate(timed):
        if not t.strip():
            if not cur:
                continue
            n_chars, span = _cue_so_far()
            if (n_chars >= space_min_chars and span >= space_min_ms
                    and _remainder_stands_alone(i)):
                # Break on Whisper's own breath boundary. The whitespace itself is
                # dropped: a cue must not end on a space (it carries the *next*
                # atom's timing, which would corrupt the cue end and the gap check).
                _close()
                cur = []
                pending_ws = []
            else:
                pending_ws.append((t, s, e, conf))
            continue
        # Consume any sentence boundary at or before this token — forces a
        # break here even if the gap/length heuristics wouldn't have broken
        # on their own (e.g. no pause between "...ทั้งนั้น" and "อย่า...").
        new_sentence = False
        while boundary_idx < len(boundary_offsets) and char_pos >= boundary_offsets[boundary_idx]:
            new_sentence = True
            boundary_idx += 1
        if cur:
            gap = s - cur[-1][2]
            span = e - cur[0][1]
            n_chars = len("".join(x[0] for x in cur).strip())
            wants_break = new_sentence or gap >= gap_ms or span > target_ms or n_chars >= target_chars
            if wants_break:
                _close()
                cur = []
        if cur:
            cur.extend(pending_ws)  # interior whitespace only
        pending_ws = []
        cur.append((t, s, e, conf))
    if cur:
        _close()
    return cues


def _dp_split_segment(timed, real_idx, seg_start, seg_end,
                       target_ms, target_chars, min_chars, min_ms):
    """Cost-minimising split of one hard-delimited run of real atoms (local
    indices `seg_start:seg_end` into `real_idx`) into cues. Classic subtitle
    line-breaking DP: candidates are every inter-atom boundary — `timed` has
    already been through `glue_atoms` (HANDOFF_THAI_BREAK_ATOMS.md), so every
    such boundary is legal by construction and none need be excluded here;
    dp[c] is the min cost to cover local atoms [0, c)."""
    n_words = seg_end - seg_start

    # Legal candidate breaks (local atom index where a new cue may start) —
    # every inter-atom boundary, since an atom can never be split.
    candidates = list(range(n_words + 1))

    def had_whitespace_before(c) -> bool:
        """A raw whitespace piece sits between local words c-1 and c — Whisper's
        own breath/clause boundary signal (discounted, not required, unlike
        the greedy path's hard minima)."""
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


def _split_dp(words, policy: CuePolicy):
    """Cost-minimising cue split (HANDOFF_CEILING_BREAK §5): a classic
    subtitle line-breaking DP over pythainlp's real word boundaries, replacing
    the greedy fill's "close the instant the character budget is hit,
    wherever that lands" rule (measured F1-neutral: `_split_greedy`'s
    docstring / config.yaml's cue_space_min_* comment).

    Candidate breaks are every inter-atom boundary — `words` is glued into
    break-atoms first (HANDOFF_THAI_BREAK_ATOMS.md: STYLE_GUIDE §7's
    unsplittable units, e.g. mai yamok orphaning, a numeral split from its
    classifier, are unrepresentable once glued, not excluded per-candidate).
    Sentence boundaries (crfcut) and real silence gaps (>= gap_ms) stay hard
    splits — same "a cue must never cross either" invariant as the greedy
    path — dividing the atom stream into independent runs; within each run,
    DP picks the break set minimising deviation from target_chars/target_ms,
    penalising overflow past target_ms and cues under space_min_chars/space_min_ms
    (a "runt"), and discounting any point Whisper itself emitted a space.

    Returns list of (text, start_ms, end_ms, confidence), same contract as
    `_split_greedy`.
    """
    gap_ms = policy.gap_ms

    timed, boundary_offsets = _prepare(words, policy)
    if timed is None:
        return []

    real_idx = [k for k, tok in enumerate(timed) if tok[0].strip()]
    if not real_idx:
        return []

    # Hard split points: local index p (0..len(real_idx)) BEFORE which a cue
    # must start fresh, mirroring the greedy path's sentence/gap forcing.
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
    return cues
