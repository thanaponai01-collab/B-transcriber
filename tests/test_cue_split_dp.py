"""DP cue split (HANDOFF_CEILING_BREAK §5, algorithm="dp").

The greedy path (`_group_words_into_cues_greedy`, tested in
test_faster_whisper_cues.py / test_cue_space_break.py) is untouched and stays
the production default — these tests exercise only the new cost-minimising
split, verifying it upholds the same STYLE_GUIDE §7 invariants and hard
boundaries the greedy path guarantees, via a genuinely different algorithm
(candidate breaks at every pythainlp word boundary, not just Whisper's
sporadic spaces).

Run: python -m pytest tests/test_cue_split_dp.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import transcribe.engines.faster_whisper as fw
from transcribe.engines.faster_whisper import _group_words_into_cues as group
from transcribe.engines.registry import get_engine


def _pieces(text: str, ms_per_char: int = 100, start: int = 0):
    out, t = [], start
    for ch in text:
        out.append((ch, t, t + ms_per_char, 0.9))
        t += ms_per_char
    return out


def test_empty():
    assert group([], algorithm="dp") == []


def test_no_characters_are_lost():
    text = "เขาก็บอกกับพ่อกับแม่เรา จนกลายเป็นว่าหนูตัดสินใจ เลิกกับคนเก่านะคะ"
    cues = group(_pieces(text), gap_ms=700, target_ms=10000, target_chars=42,
                 algorithm="dp")
    assert len(cues) > 1
    assert "".join(c[0] for c in cues).replace(" ", "") == text.replace(" ", "")


def test_cues_land_close_to_target_chars():
    text = "เขาก็บอกกับพ่อกับแม่เรา จนกลายเป็นว่าหนูตัดสินใจ เลิกกับคนเก่านะคะ"
    cues = group(_pieces(text), gap_ms=700, target_ms=10000, target_chars=42,
                 algorithm="dp")
    # DP minimises deviation from target_chars — no cue should wildly overshoot.
    assert all(len(c[0]) <= 42 + 15 for c in cues)


def test_mai_yamok_is_never_orphaned():
    """STYLE_GUIDE §3/§7: `เด็กๆ`-shaped repeats must never be split — the veto
    excludes the candidate outright, so DP can never choose it regardless of
    cost."""
    words = (_pieces("เขาชอบเราจริง") + [(" ๆ", 1300, 1400, 0.9)]
             + _pieces("โอเคนะครับ", start=2500))
    cues = group(words, gap_ms=700, target_ms=10000, target_chars=42, algorithm="dp")
    assert not any(c[0].strip().startswith("ๆ") for c in cues), (
        f"mai yamok orphaned into its own cue: {[c[0] for c in cues]}")
    assert "".join(c[0] for c in cues).replace(" ", "") == "เขาชอบเราจริงๆโอเคนะครับ"


def test_numeral_stays_with_its_classifier():
    """STYLE_GUIDE §7: never split a number from its unit/classifier."""
    words = (_pieces("ราคาทั้งหมดอยู่ที่ 100") + [(" ", 2100, 2150, 0.9)]
             + _pieces("บาทครับ", start=2200))
    cues = group(words, gap_ms=700, target_ms=10000, target_chars=42, algorithm="dp")
    assert any("100" in c[0] and "บาท" in c[0] for c in cues), (
        f"numeral split from its classifier: {[c[0] for c in cues]}")


def test_sentence_boundary_still_forces_a_hard_split():
    """A cue must never open with the tail of one sentence fused to the head
    of the next, same invariant as the greedy path — DP must not trade this
    away for a lower-cost merge."""
    text = "ผมชื่อสมชายทำงานที่กรุงเทพ วันนี้อากาศดีมากเหมาะกับการเดินเล่น"
    words = []
    t = 0
    for ch in text:
        words.append((ch, t, t + 50, 0.9))
        t += 50
    cues = group(words, gap_ms=700, target_ms=4000, target_chars=42, algorithm="dp")
    assert len(cues) == 2
    assert cues[0][0] == "ผมชื่อสมชายทำงานที่กรุงเทพ"
    assert cues[1][0] == "วันนี้อากาศดีมากเหมาะกับการเดินเล่น"
    assert cues[0][2] <= cues[1][1]


def test_real_pause_still_forces_a_hard_split():
    words = _pieces("โอเคโอเค") + [("แต่ละ", 4000, 4500, 0.9)]
    cues = group(words, gap_ms=700, target_ms=10000, target_chars=42, algorithm="dp")
    assert len(cues) == 2
    assert cues[0][2] <= cues[1][1]


def test_no_runt_cues_when_a_longer_alternative_exists():
    """A DP break that produces a sub-700ms/sub-12-char cue is penalised
    heavily — it must not fragment a run that has a viable single-cue
    alternative."""
    text = "เขาก็บอกกับพ่อกับแม่เรา จนกลายเป็นว่าหนูตัดสินใจ เลิกกับคนเก่านะคะ"
    cues = group(_pieces(text), gap_ms=700, target_ms=10000, target_chars=42,
                 space_min_chars=12, space_min_ms=700, algorithm="dp")
    assert all(c[2] - c[1] >= 700 or len(c[0]) >= 12 for c in cues), (
        f"runt cue produced: {[(c[0], c[2] - c[1]) for c in cues]}")


def test_short_interjection_is_not_shattered():
    words = [
        ("โ", 0, 200, 0.9), ("อ", 200, 300, 0.9), ("เค", 300, 500, 0.9),
        (" โ", 600, 700, 0.9), ("อ", 700, 750, 0.9), ("เค", 750, 900, 0.9),
    ]
    cues = group(words, gap_ms=700, algorithm="dp")
    assert [c[0] for c in cues] == ["โอเค โอเค"]


def test_confidence_is_mean_of_constituent_words():
    words = [
        ("โ", 0, 200, 1.0), ("อ", 200, 300, 0.5), ("เค", 300, 500, None),
    ]
    cues = group(words, gap_ms=700, algorithm="dp")
    assert len(cues) == 1
    assert cues[0][3] == 0.75


def test_default_algorithm_is_still_greedy():
    """The production default must not silently change underneath callers who
    don't pass `algorithm` — this is the whole point of gating the swap."""
    words = [(f"word{i} ", i * 300, i * 300 + 250, 0.9) for i in range(8)]
    default = group(words, gap_ms=700, target_ms=60000, target_chars=200)
    greedy = fw._group_words_into_cues_greedy(words, gap_ms=700, target_ms=60000,
                                                target_chars=200)
    assert default == greedy


def test_engine_constructor_accepts_cue_split_algorithm_override():
    eng = get_engine("faster_whisper", device="cpu", cue_split_algorithm="dp")
    assert eng._cue_split_algorithm == "dp"


def test_engine_constructor_default_is_greedy():
    eng = get_engine("faster_whisper", device="cpu")
    assert eng._cue_split_algorithm == "greedy" == fw._CUE_SPLIT_ALGORITHM
