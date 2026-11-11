"""Clause pass (algorithm="clause"): the greedy split plus two repairs that read the words.

Run: python -m pytest tests/test_cues_split_clause.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.cues import CUE_SPLIT_ALGORITHM, CuePolicy, split_cues
from transcribe.cues.split import _clause_evidence


def _pieces(text: str, ms_per_char: int = 70, start: int = 0):
    """One word piece per character; '|' inserts a 200 ms pause (shorter than gap_ms)."""
    out, t = [], start
    for ch in text:
        if ch == "|":
            t += 200
            continue
        out.append((ch, t, t + ms_per_char, 0.9))
        t += ms_per_char
    return out


def _texts(words, algorithm):
    return [c[0] for c in split_cues(words, CuePolicy(algorithm=algorithm))]


def _joined(texts):
    return "".join("".join(t.split()) for t in texts)


def test_default_is_still_greedy():
    assert CUE_SPLIT_ALGORITHM == "greedy"


def test_empty():
    assert split_cues([], CuePolicy(algorithm="clause")) == []
    assert split_cues([], CuePolicy(algorithm="clause"), return_words=True) == ([], [])


def test_no_characters_are_lost():
    words = _pieces("แต่หนูก็เลือกที่จะอยู่กับเขาเพราะว่าหนูรักเขาค่ะพี่เข้าใจแล้วหนูก็ไม่รู้จะทำยังไงต่อไปดี")
    assert _joined(_texts(words, "clause")) == _joined(_texts(words, "greedy"))


def test_size_forced_break_moves_to_the_clause_end():
    # Greedy closes the first cue when the 42-character budget runs out, which
    # strands "เขาค่ะ" at the head of the next cue.
    words = _pieces("แต่หนูก็เลือกที่จะอยู่กับเขาเพราะว่าหนูรักเขาค่ะ|พี่เข้าใจ")
    greedy, clause = _texts(words, "greedy"), _texts(words, "clause")
    assert not greedy[0].endswith("ค่ะ")
    assert clause[0].endswith("เขาค่ะ")
    assert clause[-1] == "พี่เข้าใจ"


def test_long_cue_splits_at_a_short_pause_before_an_opener():
    words = _pieces("หนูบอกว่าไม่ได้|เพราะว่าความผูกพันมันเยอะ")
    assert len(_texts(words, "greedy")) == 1
    assert _texts(words, "clause") == ["หนูบอกว่าไม่ได้", "เพราะว่าความผูกพันมันเยอะ"]


def test_long_cue_without_a_clause_boundary_stays_whole():
    words = _pieces("ทะเบียนสมรสไม่ได้ช่วยทำให้เป็นคนดีขึ้น")
    assert _texts(words, "clause") == _texts(words, "greedy")


def test_evidence_prefers_clause_ends():
    tok = lambda text, start: (text, start, start + 200, 0.9, 0)
    after_particle = _clause_evidence(tok("รักเขาค่ะ", 0), tok("แต่", 200), False)
    plain = _clause_evidence(tok("บ้าน", 0), tok("สวย", 200), False)
    dangling = _clause_evidence(tok("เพราะว่า", 0), tok("ให้", 200), False)
    assert after_particle > plain > dangling
