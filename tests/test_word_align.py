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


def _speech(*spans_ms, total_ms=3000, level=0.3, floor=1e-4):
    """16 kHz audio: low noise, with a tone at ``level`` over each (start, end) in ms."""
    import numpy as np
    rng = np.random.default_rng(0)
    y = rng.normal(0, floor, total_ms * 16).astype(np.float32)
    for a, b in spans_ms:
        t = np.arange((b - a) * 16) / 16000
        y[a * 16:b * 16] += level * np.sin(2 * np.pi * 220 * t)
    return y


def test_a_late_start_after_a_pause_moves_back_onto_the_sound():
    from transcribe.pipeline.word_align import levels_db, snap_to_sound
    lev = levels_db(_speech((1000, 2000)), 16000)
    assert 970 <= snap_to_sound(1150, 0, lev) <= 1000  # CTC spike 150 ms in -> the sound's edge
    assert 970 <= snap_to_sound(900, 0, lev) <= 1000   # a start in the quiet moves forward onto it


def test_a_start_inside_running_speech_or_far_from_the_edge_stays():
    from transcribe.pipeline.word_align import levels_db, snap_to_sound
    lev = levels_db(_speech((1000, 2000)), 16000)
    assert snap_to_sound(1500, 0, lev) == 1500  # sound runs back more than 200 ms: no pause near
    assert snap_to_sound(500, 0, lev) == 500    # quiet for more than 200 ms ahead


def test_a_sound_before_a_dip_does_not_capture_the_start():
    from transcribe.pipeline.word_align import levels_db, snap_to_sound
    lev = levels_db(_speech((850, 950), (1000, 2000)), 16000)  # a breath, a 50 ms dip, the word
    assert snap_to_sound(1100, 0, lev) == 1100  # too short a dip to call a pause: CTC's start stands


def test_no_snap_where_the_sound_never_drops_into_a_real_pause():
    from transcribe.pipeline.word_align import levels_db, snap_to_sound
    lev = levels_db(_speech((1000, 2000), floor=0.05), 16000)  # music bed under the voice
    assert snap_to_sound(1150, 0, lev) == 1150


def test_snap_moves_every_start_then_the_clamps_hold():
    align, _ = fake({"สวัสดี": 1080, "ครับ": 1460, "วันนี้": 2960})
    new = retime_starts(WORDS, CUES, align, thai, pad_ms=400, duration_ms=10_000, snap=lambda s, prev: s - 100)
    assert [(x["start_ms"], x["end_ms"]) for x in new] == [(980, 1360), (1360, 1900), (2860, 3300), (3300, 3700)]


def test_the_second_word_of_a_phrase_keeps_its_start():
    """ก็ at the phrase onset, then ทำ 150 ms in with no pause between: only ก็ moves."""
    from transcribe.pipeline.word_align import levels_db, snap_to_sound
    lev = levels_db(_speech((1000, 2000)), 16000)
    words = [w("ก็", 1080, 1150), w("ทำ", 1150, 1600)]
    align, _ = fake({"ก็": 1080, "ทำ": 1150})
    new = retime_starts(words, [Cue(start_ms=1000, end_ms=2000)], align, thai, pad_ms=0, duration_ms=3000,
                        snap=lambda s, prev: snap_to_sound(s, prev, lev))
    assert 970 <= new[0]["start_ms"] <= 1000
    assert new[1]["start_ms"] == 1150 and new[0]["end_ms"] == 1150


def test_a_missing_checkpoint_names_the_export_command():
    import pytest
    from transcribe.pipeline.word_align import model_path
    with pytest.raises(FileNotFoundError, match="export_checkpoint"):
        model_path("models/never-exported.pt")
