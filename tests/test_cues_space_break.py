"""Whisper's own spaces as cue-break candidates (transcribe.cues.split_cues).

Thai has no orthographic spaces, so any space Whisper emits inside Thai is a
breath/clause boundary the acoustic model heard — a free segmentation signal
that cue grouping used to discard, buffering whitespace as cue-interior only.

Two things this must NOT do: shatter short interjections into one-word cues,
and violate STYLE_GUIDE §7 unsplittable units — Whisper writes mai yamok as a
separate ' ๆ' piece, so a naive rule orphans it from the word it repeats on
almost every ๆ in the corpus.

Run: python -m pytest tests/test_cues_space_break.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import transcribe.cues.split as cues_split
from transcribe.cues import CuePolicy, split_cues


def group(words, **policy_kwargs):
    return split_cues(words, CuePolicy(**policy_kwargs))


@pytest.fixture(autouse=True)
def _no_sentence_forcing(monkeypatch):
    """Disable crfcut sentence-boundary forcing for this file.

    Not cosmetic: crfcut segments unpunctuated Thai *at spaces*, so on realistic
    synthetic input it splits at exactly the points under test here and every
    assertion below would pass whether the space-break logic worked or not.
    (Caught the hard way — an early version of the runt test passed because
    crfcut, not the space rule, was doing the splitting.) Sentence forcing has
    its own coverage in test_cues_grouping.py.
    """
    monkeypatch.setattr(cues_split, "_sentence_boundary_offsets", lambda text: [])


def _pieces(text: str, ms_per_char: int = 100, start: int = 0):
    """One piece per character, evenly spaced — mirrors Whisper's sub-word Thai."""
    out, t = [], start
    for ch in text:
        out.append((ch, t, t + ms_per_char, 0.9))
        t += ms_per_char
    return out


def test_space_breaks_a_long_enough_cue():
    # 22 chars before the space, 2.2s — comfortably over both minima, and well
    # under target_chars=42, so ONLY the space explains a break here.
    words = _pieces("เขาก็บอกกับพ่อกับแม่เรา จนกลายเป็นว่าหนู")
    cues = group(words, gap_ms=700, target_ms=10000, target_chars=42,
                 space_min_chars=12, space_min_ms=700)
    assert [c[0] for c in cues] == ["เขาก็บอกกับพ่อกับแม่เรา", "จนกลายเป็นว่าหนู"]
    # The dropped space must not leak into either cue's timing.
    assert cues[0][2] <= cues[1][1]


def test_short_interjection_is_not_shattered():
    # "โอเค โอเค" is 8 chars / 900ms — under the minima, so it stays one cue.
    words = [
        ("โ", 0, 200, 0.9), ("อ", 200, 300, 0.9), ("เค", 300, 500, 0.9),
        (" โ", 600, 700, 0.9), ("อ", 700, 750, 0.9), ("เค", 750, 900, 0.9),
    ]
    cues = group(words, gap_ms=700, space_min_chars=12, space_min_ms=700)
    assert [c[0] for c in cues] == ["โอเค โอเค"]


def test_duration_minimum_blocks_a_fast_break():
    # 20 chars but only 400ms of audio — a cue that short is a flash, not a cue.
    words = _pieces("อยากบอกทุกคนเลยนะครับ ว่าดีมาก", ms_per_char=20)
    cues = group(words, gap_ms=700, target_ms=10000, target_chars=42,
                 space_min_chars=12, space_min_ms=700)
    assert len(cues) == 1


def test_mai_yamok_is_never_orphaned_by_a_space_break():
    """STYLE_GUIDE §3/§7: `เด็กๆ` must never be separated from its word.
    Whisper emits ' ๆ' as its own space-prefixed piece, so this is the common
    case, not an edge case."""
    # 13 chars / 1.3s before the ' ๆ' piece clears both minima, so without the §7
    # veto the space would break and leave 'ๆ' stranded. A 1.1s silence after it
    # supplies a legitimate break so the assertion is about WHERE the cue splits,
    # not whether it splits at all.
    words = _pieces("เขาชอบเราจริง") + [(" ๆ", 1300, 1400, 0.9)] + _pieces("โอเคนะครับ", start=2500)
    cues = group(words, gap_ms=700, target_ms=10000, target_chars=42,
                 space_min_chars=12, space_min_ms=700)
    assert [c[0].replace(" ", "") for c in cues] == ["เขาชอบเราจริงๆ", "โอเคนะครับ"]
    assert not any(c[0].strip().startswith("ๆ") for c in cues), (
        f"mai yamok orphaned into its own cue: {[c[0] for c in cues]}")


def test_numeral_stays_with_its_classifier():
    """STYLE_GUIDE §7: never split a number from its unit/classifier."""
    words = _pieces("ราคาทั้งหมดอยู่ที่ 100") + [(" ", 2100, 2150, 0.9)] + _pieces("บาทครับ", start=2200)
    cues = group(words, gap_ms=700, target_ms=10000, target_chars=42,
                 space_min_chars=12, space_min_ms=700)
    assert any("100" in c[0] and "บาท" in c[0] for c in cues), (
        f"numeral split from its classifier: {[c[0] for c in cues]}")


def test_space_break_never_orphans_a_runt_cue():
    """Both sides must be viable. Observed: 'เขาชอบเราจริงๆ โอเค' broke at the
    space, and the following pause then closed 'โอเค' as a 140ms flash cue —
    unreadable, and well under the shortest cue in a hand-cut reference."""
    words = (_pieces("เขาชอบเราจริงๆ")            # 14 chars / 1.4s — minima met
             + [(" ", 1400, 1450, 0.9)]
             + _pieces("โอเค", start=1500)        # 3 chars / 0.3s — a runt
             + _pieces("เขารักเรา", start=3000))  # after a 1.2s pause
    cues = group(words, gap_ms=700, target_ms=10000, target_chars=42,
                 space_min_chars=12, space_min_ms=700)
    assert all(c[2] - c[1] >= 700 for c in cues), (
        f"space break produced a runt cue: {[(c[0], c[2] - c[1]) for c in cues]}")
    assert cues[0][0].replace(" ", "") == "เขาชอบเราจริงๆโอเค"


def test_break_still_fires_when_both_sides_are_viable():
    """The runt guard must not disable the feature — the remainder here stands
    on its own, so the space break goes ahead."""
    words = (_pieces("เขาก็บอกกับพ่อกับแม่เรา")
             + [(" ", 2300, 2350, 0.9)]
             + _pieces("จนกลายเป็นว่าหนูตัดสินใจ", start=2400))
    cues = group(words, gap_ms=700, target_ms=10000, target_chars=42,
                 space_min_chars=12, space_min_ms=700)
    assert len(cues) == 2


def test_space_break_can_be_disabled():
    words = _pieces("เขาก็บอกกับพ่อกับแม่เรา จนกลายเป็นว่าหนู")
    cues = group(words, gap_ms=700, target_ms=10000, target_chars=99,
                 space_min_chars=10**6, space_min_ms=10**6)
    assert len(cues) == 1, "an unreachable minimum must restore the old behaviour"


def test_no_characters_are_lost():
    text = "เขาก็บอกกับพ่อกับแม่เรา จนกลายเป็นว่าหนูตัดสินใจ เลิกกับคนเก่านะคะ"
    cues = group(_pieces(text), gap_ms=700, target_ms=10000, target_chars=42,
                 space_min_chars=12, space_min_ms=700)
    assert len(cues) > 1
    # Spaces at break points are dropped by design; nothing else may vanish.
    assert "".join(c[0] for c in cues).replace(" ", "") == text.replace(" ", "")
