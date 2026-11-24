"""Word-start alignment (transcribe/pipeline/word_align.py): starts move, text and ends stay."""
from types import SimpleNamespace as Cue

from transcribe.pipeline.word_align import retime_cue_starts, retime_starts


def w(text, s, e):
    return {"text": text, "start_ms": s, "end_ms": e, "confidence": 0.9}


WORDS = [w("สวัสดี", 1000, 1500), w("ครับ", 1500, 1900), w("วันนี้", 3000, 3400), w("F1", 3400, 3700)]
CUES = [Cue(start_ms=1000, end_ms=1900), Cue(start_ms=3000, end_ms=3700)]


def fake(heard):
    """An aligner that heard each word start at ``heard[text]`` (None = nothing it can align)."""
    calls = []

    def align(lo, hi, texts):
        calls.append((lo, hi, texts))
        return [None if heard.get(t) is None else (heard[t], heard[t] + 100) for t in texts]
    return align, calls


def test_starts_move_to_what_the_aligner_heard_and_ends_stay():
    align, calls = fake({"สวัสดี": 1080, "ครับ": 1460, "วันนี้": 2960})
    new = retime_starts(WORDS, CUES, align, pad_ms=400, duration_ms=10_000)
    assert [(x["start_ms"], x["end_ms"]) for x in new] == [(1080, 1500), (1460, 1900), (2960, 3400), (3400, 3700)]
    assert [x["text"] for x in new] == [x["text"] for x in WORDS]
    assert calls == [(600, 2300, ["สวัสดี", "ครับ"]), (2600, 4100, ["วันนี้", "F1"])]  # one padded window per cue
    assert WORDS[0]["start_ms"] == 1000  # input untouched


def test_starts_never_go_backwards_and_a_word_keeps_one_ms():
    align, _ = fake({"สวัสดี": 1600, "ครับ": 1400})
    new = retime_starts(WORDS[:2], CUES[:1], align, pad_ms=0, duration_ms=10_000)
    assert [(x["start_ms"], x["end_ms"]) for x in new] == [(1600, 1601), (1600, 1900)]


def test_cue_starts_follow_their_first_word_without_overlapping_the_previous_cue():
    cues = [Cue(start_ms=1000, end_ms=1900), Cue(start_ms=1900, end_ms=3000), Cue(start_ms=3000, end_ms=3700)]
    old = [w("a", 1000, 1400), w("b", 1900, 2500), w("c", 3000, 3400)]
    new = [w("a", 1060, 1400), w("b", 1850, 2500), w("c", 3000, 3400)]
    retime_cue_starts(cues, old, new)
    assert [(c.start_ms, c.end_ms) for c in cues] == [(1060, 1900), (1900, 3000), (3000, 3700)]
