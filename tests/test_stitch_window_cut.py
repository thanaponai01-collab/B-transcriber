"""Overlapping decode windows must not interleave two segmentations of one speech.

Defect (CFD short D5, 2026-10-07): a pause-free span over 25 s is decoded as
windows sharing 4 s. Within the overlap the two decodes split the same speech
differently ('เขาไม่'+'ได้' vs 'เขา'+'ไม่ได้'), so token-level dedup kept pieces
of both and the transcript came out as 'เขไม่าได้'. With cut_seams each window
owns one side of a seam placed where both decodes have a boundary.

Run: python -m pytest tests/test_stitch_window_cut.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.audio.decode import AudioWindow, decode_windows
from transcribe.audio.stitch import ChunkTokens, cut_seams, stitch
from transcribe.contracts import RecognizedToken


def _t(text, a, b):
    return RecognizedToken(text, a, b, 0.9, "thai")


# Same speech 21000-25000 ms, split differently by the two windows.
A = ChunkTokens(start_ms=0, end_ms=25000, tokens=[
    _t("ก่อน", 20000, 21000),
    _t("เขา", 21000, 21600), _t("ไม่", 21600, 22200), _t("ได้", 22200, 22800),
    _t("ทำ", 22800, 23400), _t("ท่า", 23400, 24000), _t("ทาง", 24000, 24600),
])
B = ChunkTokens(start_ms=21000, end_ms=46000, tokens=[
    _t("เขาไม่", 21100, 22000), _t("ได้ทำ", 22000, 23300),
    _t("ท่าทาง", 23300, 24800), _t("ให้", 24800, 25500), _t("มัน", 25500, 26000),
])


def _text(tokens):
    return "".join(t.text for t in tokens)


def test_plain_stitch_interleaves_the_two_segmentations():
    """Documents the defect: no single decode's text survives."""
    out = _text(stitch([A, B], seam_window_ms=4000))
    assert out != "ก่อนเขาไม่ได้ทำท่าทางให้มัน"


def test_cut_seams_keeps_one_clean_version():
    out = stitch(cut_seams([A, B]), seam_window_ms=4000)
    assert _text(out) == "ก่อนเขาไม่ได้ทำท่าทางให้มัน"
    assert all(a.end_ms <= b.start_ms + 100 for a, b in zip(out, out[1:])), "tokens must not overlap in time"


def test_seam_sits_on_a_boundary_both_windows_share():
    cut = cut_seams([A, B])
    a_end = max(t.end_ms for t in cut[0].tokens)
    b_start = min(t.start_ms for t in cut[1].tokens)
    assert abs(a_end - b_start) <= 150


def test_non_overlapping_chunks_are_untouched():
    c0 = ChunkTokens([_t("ก", 0, 500)], 0, 1000)
    c1 = ChunkTokens([_t("ข", 1000, 1500)], 1000, 2000)
    cut = cut_seams([c0, c1])
    assert [t.text for c in cut for t in c.tokens] == ["ก", "ข"]


def test_decode_windows_cut_flag_is_opt_in():
    wins = [AudioWindow("a", 0, 25000), AudioWindow("b", 21000, 46000)]
    shifted = {"a": [(t.text, t.start_ms, t.end_ms) for t in A.tokens],
               "b": [(t.text, t.start_ms - 21000, t.end_ms - 21000) for t in B.tokens]}
    decode = lambda audio: [_t(*x) for x in shifted[audio]]
    # decode_windows offsets by window start: window a starts at 0, b at 21000
    plain = decode_windows(wins, decode, seam_window_ms=4000)
    cut = decode_windows(wins, decode, seam_window_ms=4000, cut_seams=True)
    assert _text(cut) == "ก่อนเขาไม่ได้ทำท่าทางให้มัน"
    assert _text(plain) != _text(cut)


def test_truncated_window_tail_does_not_swallow_the_next_windows_words():
    """Wealthy-40 clip: window 0 lost its last 5 s of speech and its final token
    ('ี') was stretched over the silence (19.5-25.0 s). The seam must not sit at
    that fake end, or window 1's real words before it are thrown away."""
    a = ChunkTokens(start_ms=0, end_ms=25000, tokens=[
        _t("วา", 19000, 19400), _t("ี", 19500, 25000), _t("ค", 25000, 25000)])
    b = ChunkTokens(start_ms=21000, end_ms=46000, tokens=[
        _t("AM", 21400, 21600), _t("D", 21600, 21800), _t("นะ", 21900, 22000),
        _t("ที่", 22400, 22500), _t("กำลัง", 22600, 23300), _t("ออก", 24100, 24400),
        _t("เป็น", 24900, 25300)])
    out = _text(stitch(cut_seams([a, b]), seam_window_ms=4000))
    assert out == "วาAMDนะที่กำลังออกเป็น"  # the stretched token is dropped, B's words kept
