"""A trailing particle (เนี้ย) stays with the clause it ends instead of opening the next cue."""
from transcribe.cues import split_cues
from transcribe.cues.policy import CuePolicy


def _words(particle):
    # 3.9 s of speech, then the particle: adding it crosses the 4 s limit.
    return [("ซึ่งในช่วงแห้ง", 0, 3900, None), (particle, 3900, 4150, None),
            ("มันหาตำแหน่งกัน", 4150, 6000, None)]


def test_particle_stays_with_its_clause():
    cues = split_cues(_words("เนี้ย"), CuePolicy(target_ms=4000))
    assert cues[0][0].endswith("เนี้ย") and cues[1][0] == "มันหาตำแหน่งกัน"


def test_ordinary_word_still_breaks_at_the_limit():
    cues = split_cues(_words("แล้ว"), CuePolicy(target_ms=4000))
    assert cues[1][0].startswith("แล้ว")


def test_overshoot_is_bounded():
    words = [("ซึ่งในช่วงแห้ง", 0, 4900, None), ("เนี้ย", 4900, 5200, None)]
    cues = split_cues(words, CuePolicy(target_ms=4000))
    assert cues[-1][0] == "เนี้ย"


def test_connective_after_closing_particle_opens_a_new_cue():
    words = [("มันหาตำแหน่งกันค่อนข้างยากนะในโค้งแรกครับ", 0, 3000, None),
             ("แล้วก็", 3100, 3500, None), ("แต่ในฝนมันจะวุ่นวายหน่อยครับ", 3500, 5500, None)]
    cues = split_cues(words, CuePolicy())
    assert cues[0][0].endswith("ครับ") and cues[1][0].startswith("แล้วก็")


def test_connective_mid_clause_does_not_break():
    words = [("มันหาตำแหน่งกันยากนะ", 0, 3000, None),
             ("แล้วก็", 3100, 3500, None), ("แต่ในฝนมัน", 3500, 4500, None)]
    assert split_cues(words, CuePolicy())[0][0].endswith("แล้วก็")
