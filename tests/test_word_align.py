"""Word-start alignment (transcribe/pipeline/word_align.py): starts move, text stays."""
from types import SimpleNamespace as Cue

from transcribe.pipeline.word_align import retime_cue_starts, retime_starts


def w(text, s, e):
    return {"text": text, "start_ms": s, "end_ms": e, "confidence": 0.9}


def thai(text):
    return not text.isascii()


WORDS = [w("สวัสดี", 1000, 1500), w("ครับ", 1500, 1900), w("วันนี้", 3000, 3400), w("F1", 3400, 3700)]
CUES = [Cue(start_ms=1000, end_ms=1900), Cue(start_ms=3000, end_ms=3700)]


def fake(heard):
    """An aligner that heard each word start at ``heard[text]``."""
    calls = []

    def align(lo, hi, texts):
        calls.append((lo, hi, texts))
        return [None if heard.get(t) is None else (heard[t], heard[t] + 100) for t in texts]
    return align, calls


def test_starts_move_to_what_the_aligner_heard_and_a_word_ends_by_the_next_start():
    align, calls = fake({"สวัสดี": 1080, "ครับ": 1460, "วันนี้": 2960})
    new = retime_starts(WORDS, CUES, align, thai, pad_ms=400, duration_ms=10_000)
    assert [(x["start_ms"], x["end_ms"]) for x in new] == [(1080, 1460), (1460, 1900), (2960, 3400), (3400, 3700)]
    assert [x["text"] for x in new] == [x["text"] for x in WORDS]
    assert calls[0] == (600, 2300, ["สวัสดี", "ครับ"])  # one padded window per cue
    assert WORDS[0]["start_ms"] == 1000  # input untouched


def test_a_word_the_model_cannot_align_walls_off_its_own_audio():
    words = [w("ปี", 1000, 1300), w("20", 1300, 1600), w("อย่างนี้", 1600, 2000)]
    align, calls = fake({"ปี": 950, "อย่างนี้": 1620})
    new = retime_starts(words, [Cue(start_ms=1000, end_ms=2000)], align, thai, pad_ms=400, duration_ms=10_000)
    assert calls == [(600, 1300, ["ปี"]), (1600, 2400, ["อย่างนี้"])]
    assert [x["start_ms"] for x in new] == [950, 1300, 1620]


def test_starts_never_go_backwards_and_a_word_keeps_one_ms():
    align, _ = fake({"สวัสดี": 1600, "ครับ": 1400})
    new = retime_starts(WORDS[:2], CUES[:1], align, thai, pad_ms=0, duration_ms=10_000)
    assert [(x["start_ms"], x["end_ms"]) for x in new] == [(1600, 1601), (1600, 1900)]


def test_touching_cues_move_their_shared_boundary_either_way():
    cues = [Cue(start_ms=1000, end_ms=1900), Cue(start_ms=1900, end_ms=3000), Cue(start_ms=3000, end_ms=3700)]
    old = [w("a", 1000, 1400), w("b", 1900, 2500), w("c", 3000, 3400)]
    new = [w("a", 1060, 1400), w("b", 1850, 2500), w("c", 3080, 3400)]
    retime_cue_starts(cues, old, new)
    assert [(c.start_ms, c.end_ms) for c in cues] == [(1060, 1850), (1850, 3080), (3080, 3700)]


def test_a_cue_after_a_pause_never_reaches_into_the_previous_one():
    cues = [Cue(start_ms=1000, end_ms=1900), Cue(start_ms=2100, end_ms=3000)]
    old = [w("a", 1000, 1400), w("b", 2100, 2500)]
    new = [w("a", 1000, 1400), w("b", 1800, 2500)]
    retime_cue_starts(cues, old, new)
    assert [(c.start_ms, c.end_ms) for c in cues] == [(1000, 1900), (1900, 3000)]
