"""Stitch dedup for sub-word pieces that disagree on the SPLIT POINT, not just
the boundary (issue #8).

The `_coincident` fix (2026-07-30) closed the case where two windows agree on
a piece's text but place it a few ms apart. It does not help when the two
windows tokenize the same overlap-zone syllables at different sub-word split
points: window A emits a truncated prefix ('หญ') where window B, with more
context, emits the full syllable run ('หญิง') covering the same audio; or the
two windows split the run at different points entirely ('หญิ' vs 'ญิง').
Neither pair is text-equal, so the exact-text `same_word` gate never even
reaches the temporal check, and both fragments survive to concatenate into a
doubled-syllable stutter ('ผหู้หญิญิง' instead of 'ผู้หญิง').

This fix went through four rounds of independent correctness-gate review,
each finding a real defect in the version before it:

1. A similarity-ratio version (SequenceMatcher >= 0.5) false-merged distinct
   2-character Thai particles sharing one character ('มา'/'นา', 'จะ'/'จา',
   'มี'/'ปี', 'ตา'/'ผา', 'คา'/'คำ' — ratio 0.5, indistinguishable from a
   genuine split-point match).
2. An anchored-text-overlap version (containment, or a suffix/prefix match
   of >= 2 characters, no duration check) false-merged real, unrelated,
   correctly-decoded words sharing a 2+ character boundary morpheme
   ('หมา'/'มานะ', 'ขนม'/'นมสด', 'ตลาด'/'ลาดยาง' — Thai's short morphemes
   recur as substrings of longer, unrelated words too).
3. A `_FUZZY_FRAGMENT_MAX_MS = 150` version (at least one side of a fuzzy
   match must be that brief) was itself miscalibrated on a bad citation —
   see round 4 — and a gate additionally showed it failed to dedupe a
   constructed longer split-point duplicate (~200ms both sides).
4. Raising the cap to 250ms to "cover" that case was **based on a misread**:
   the 160ms `อะไร` figure cited to justify it is the duration of an
   EXACT-text token from the pre-existing `_coincident` mechanism, not
   evidence about fuzzy-matched fragment durations — this codebase has no
   real measured example of the latter. At 250ms, a gate showed the round-2
   false-merge class was live across essentially the whole 0-250ms range for
   the documented dangerous word pairs — ordinary short-word speech, not an
   edge case.
5. The current version drops the invented cap and reuses the ONE duration
   figure this file already has real grounds for: `_COINCIDENT_MS`'s
   established 20-80ms range for genuine sub-word ASR pieces (see the
   module comment above `_COINCIDENT_MS`). This is deliberately
   conservative: a differently-split duplicate whose pieces both run longer
   than 80ms will NOT be caught here and may still ship as a stutter — an
   accepted, disclosed gap, not attempted without real data, because a
   missed cosmetic stutter is cheaper than dropping a real word.

Run: python -m pytest tests/test_stitch_fuzzy_seam_text.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.contracts import RecognizedToken
from transcribe.pipeline.stitch import ChunkTokens, _fuzzy_same_word, stitch


def _t(text, s, e, conf=0.9):
    return RecognizedToken(text, s, e, conf, "thai")


def test_truncated_prefix_vs_full_syllable_is_deduped():
    """Window A's fragment 'หญ' (70ms — sub-word scale, within
    `_FUZZY_FRAGMENT_MAX_MS`) and window B's full 'หญิง' cover the same audio
    at the same instant — currently they never dedupe at all, and both
    survive into the transcript as a doubled-syllable stutter. Which copy
    `_prefer`'s existing interiority/confidence tie-break keeps is out of
    scope here; only that exactly one survives is this fix's contract."""
    win_a = ChunkTokens(start_ms=0, end_ms=25000,
                         tokens=[_t("หญ", 21100, 21170)])
    win_b = ChunkTokens(start_ms=21000, end_ms=46000,
                         tokens=[_t("หญิง", 21100, 21300)])
    merged = stitch([win_a, win_b], seam_window_ms=4000)
    assert len(merged) == 1, "truncated/full seam duplicate survived as a stutter"
    assert merged[0].text in ("หญ", "หญิง")


def test_split_at_different_point_is_deduped():
    """Neither fragment contains the other — the split point itself moved
    ('หญิ' | 'ง' vs 'ห' | 'ญิง') — so only the anchored-overlap check catches
    it, not plain substring containment. Both pieces are sub-word scale
    (70ms), consistent with a genuine decode-boundary artifact and within
    `_FUZZY_FRAGMENT_MAX_MS`."""
    win_a = ChunkTokens(start_ms=0, end_ms=25000,
                         tokens=[_t("หญิ", 21100, 21170)])
    win_b = ChunkTokens(start_ms=21000, end_ms=46000,
                         tokens=[_t("ญิง", 21130, 21200)])
    merged = stitch([win_a, win_b], seam_window_ms=4000)
    assert len(merged) == 1, "differently-split seam duplicate survived as a stutter"


def test_longer_split_point_duplicate_is_a_disclosed_gap_not_a_bug():
    """A plausible longer split-point duplicate where BOTH fragments run
    ~200ms is NOT deduped by this fix — deliberately. An earlier version
    tried to widen `_FUZZY_FRAGMENT_MAX_MS` to catch this and, in doing so,
    reopened the round-2 false-merge class across ordinary short-word speech
    (see the module docstring history, round 4). No real evidence exists
    that fuzzy split-point duplicates actually run this long in production,
    so this fix does not chase it — a missed stutter here is cheaper than
    the false merges that chasing it caused. Recalibrating this boundary
    requires real fuzzy-dedup log data (TODO_LEDGER.md), not another
    synthetic example."""
    win_a = ChunkTokens(start_ms=0, end_ms=25000,
                         tokens=[_t("ทรมานใ", 21000, 21200)])
    win_b = ChunkTokens(start_ms=21000, end_ms=46000,
                         tokens=[_t("รมานใจ", 21050, 21250)])
    merged = stitch([win_a, win_b], seam_window_ms=4000)
    assert len(merged) == 2, (
        "if this now passes, _FUZZY_FRAGMENT_MAX_MS moved — re-check the false-merge "
        "regression tests below still pass before treating that as progress"
    )


def test_dissimilar_text_is_never_fuzzy_merged():
    """Two genuinely different, unrelated words must not be merged even when
    they happen to land close in time across a seam."""
    win_a = ChunkTokens(start_ms=0, end_ms=25000,
                         tokens=[_t("สวัสดี", 21000, 21400)])
    win_b = ChunkTokens(start_ms=21000, end_ms=46000,
                         tokens=[_t("ขอบคุณ", 21050, 21450)])
    merged = stitch([win_a, win_b], seam_window_ms=4000)
    assert sorted(t.text for t in merged) == ["ขอบคุณ", "สวัสดี"]


def test_distinct_short_particles_sharing_one_character_are_never_merged():
    """Round-1 gate finding: distinct 2-character Thai particles sharing one
    character, landing within `_coincident`'s duration-scaled tolerance
    across a seam. A ratio-based similarity test (SequenceMatcher >= 0.5)
    merged these; the anchored-overlap length requirement must not, since a
    1-character shared run never meets `_MIN_FUZZY_OVERLAP`."""
    for a_text, b_text in [("มา", "นา"), ("จะ", "จา"), ("มี", "ปี"),
                            ("ตา", "ผา"), ("คา", "คำ")]:
        win_a = ChunkTokens(start_ms=0, end_ms=25000,
                             tokens=[_t(a_text, 21000, 21200)])
        win_b = ChunkTokens(start_ms=21000, end_ms=46000,
                             tokens=[_t(b_text, 21100, 21300)])
        merged = stitch([win_a, win_b], seam_window_ms=4000)
        assert sorted(t.text for t in merged) == sorted([a_text, b_text]), (
            f"{a_text!r}/{b_text!r} were incorrectly merged"
        )


def test_distinct_real_words_sharing_a_boundary_morpheme_are_never_merged():
    """Round-2 gate finding: real, unrelated, correctly-decoded Thai words
    that happen to share a 2+ character morpheme at a boundary
    ('หมา'/'มานะ' both contain 'มา'; likewise 'ขนม'/'นมสด', 'ตลาด'/'ลาดยาง'),
    at realistic-to-generous spoken-word durations (100-150ms — a round-4
    gate demonstrated these false-merge up to 250ms when the cap sat there;
    `_FUZZY_FRAGMENT_MAX_MS = 80` must reject them well before that)."""
    for a_text, b_text in [("หมา", "มานะ"), ("ขนม", "นมสด"), ("ตลาด", "ลาดยาง")]:
        win_a = ChunkTokens(start_ms=0, end_ms=25000,
                             tokens=[_t(a_text, 21000, 21100)])   # 100ms
        win_b = ChunkTokens(start_ms=21000, end_ms=46000,
                             tokens=[_t(b_text, 21050, 21200)])   # 150ms
        merged = stitch([win_a, win_b], seam_window_ms=4000)
        assert sorted(t.text for t in merged) == sorted([a_text, b_text]), (
            f"{a_text!r}/{b_text!r} were incorrectly merged"
        )


def test_anchored_overlap_far_apart_in_time_survives():
    """'หญิ' and 'ญิง' pass the anchored-overlap + duration checks (both
    70ms, see test_fuzzy_same_word_helper) but occur ~21s apart here — real,
    distinct speech, not a seam artifact. The temporal gate (seam_window_ms
    cutoff) must still be what blocks the merge, exactly as it does for the
    exact-text/_coincident pair."""
    win_a = ChunkTokens(start_ms=0, end_ms=25000,
                         tokens=[_t("หญิ", 100, 170)])
    win_b = ChunkTokens(start_ms=21000, end_ms=46000,
                         tokens=[_t("ญิง", 21000, 21070)])
    merged = stitch([win_a, win_b], seam_window_ms=4000)
    assert sorted(t.text for t in merged) == sorted(["หญิ", "ญิง"])


def test_same_chunk_similar_fragments_are_not_fuzzy_merged():
    """The cross-chunk guard (ci != pci) still applies to the fuzzy path —
    two adjacent, similar-looking pieces from the SAME window are real
    sub-word structure, never a stitching artifact."""
    same = ChunkTokens(start_ms=0, end_ms=25000,
                        tokens=[_t("หญิ", 6660, 6730), _t("หญิง", 6730, 6850)])
    merged = stitch([same])
    assert [t.text for t in merged] == ["หญิ", "หญิง"]


def test_fuzzy_same_word_helper():
    assert _fuzzy_same_word(_t("หญ", 0, 70), _t("หญิง", 0, 300))        # substring, brief
    assert _fuzzy_same_word(_t("หญิ", 0, 70), _t("ญิง", 0, 70))          # anchored overlap, brief
    assert not _fuzzy_same_word(_t("หญิง", 0, 300), _t("หญิง", 0, 300))  # identical text is the exact-match gate's job
    assert not _fuzzy_same_word(_t("สวัสดี", 0, 400), _t("ขอบคุณ", 0, 400))  # unrelated words
    assert not _fuzzy_same_word(_t("", 0, 70), _t("ก", 0, 70))
    assert not _fuzzy_same_word(_t("ห", 0, 70), _t("หญิง", 0, 300))     # single-char overlap: below _MIN_FUZZY_OVERLAP
    for a_text, b_text in [("มา", "นา"), ("จะ", "จา"), ("มี", "ปี"),
                            ("ตา", "ผา"), ("คา", "คำ")]:
        assert not _fuzzy_same_word(_t(a_text, 0, 70), _t(b_text, 0, 70)), (
            f"{a_text!r}/{b_text!r} should not fuzzy-match"
        )
    # Real words at ordinary durations, well above fragment scale: anchored
    # text overlap present, but neither side is fragment-brief.
    for a_text, b_text in [("หมา", "มานะ"), ("ขนม", "นมสด"), ("ตลาด", "ลาดยาง")]:
        assert not _fuzzy_same_word(_t(a_text, 0, 100), _t(b_text, 0, 150)), (
            f"{a_text!r}/{b_text!r} should not fuzzy-match at ordinary word durations"
        )
    # Same text pair, but a clipped/fast rendering of the shorter word
    # (<= _FUZZY_FRAGMENT_MAX_MS = 80ms — genuinely brisk for a 2-3 character
    # word, not ordinary pace) falls under the fragment-duration cap and
    # still merges, since text+duration+temporal all agree. Documents the
    # accepted residual risk (see module comment on `_FUZZY_FRAGMENT_MAX_MS`)
    # — see test_brief_zero_gap_real_words_can_still_collide below for the
    # same risk exercised through stitch() itself, not just this helper.
    assert _fuzzy_same_word(_t("หมา", 0, 70), _t("มานะ", 0, 400))


def test_brief_zero_gap_real_words_can_still_collide():
    """Round-5 gate finding: the accepted residual `test_fuzzy_same_word_helper`
    documents at the helper level is trivially live through `stitch()` itself
    when two distinct, genuinely brief (both near/under `_COINCIDENT_MS`)
    real words are spoken with ~no gap — 'มา' immediately followed by 'มานี'
    with no natural pause collides, because `_coincident`'s tolerance floor
    (`_COINCIDENT_MS = 60`) exceeds the zero-gap centre-distance for tokens
    this brief regardless of whether they're a real duplicate or two
    separately-spoken short words. A mere 20ms natural gap is enough to
    separate them correctly (second half of this test). This is NOT a new
    defect — it is the known residual, now with a `stitch()`-level regression
    lock so it can't silently widen, and honest proof it is reachable rather
    than a theoretical concern."""
    win_a = ChunkTokens(start_ms=0, end_ms=25000,
                         tokens=[_t("มา", 21000, 21050)])
    win_b = ChunkTokens(start_ms=21000, end_ms=46000,
                         tokens=[_t("มานี", 21050, 21110)])
    merged = stitch([win_a, win_b], seam_window_ms=4000)
    assert len(merged) == 1, (
        "accepted residual widened or narrowed — re-check "
        "_FUZZY_FRAGMENT_MAX_MS/_COINCIDENT_MS before treating this as a fix"
    )

    # A natural 20ms gap between the two words is enough for them to survive.
    win_b_gapped = ChunkTokens(start_ms=21000, end_ms=46000,
                                tokens=[_t("มานี", 21070, 21130)])
    merged_gapped = stitch([win_a, win_b_gapped], seam_window_ms=4000)
    assert sorted(t.text for t in merged_gapped) == sorted(["มา", "มานี"]), (
        "a real 20ms gap should be enough to distinguish two real words"
    )
