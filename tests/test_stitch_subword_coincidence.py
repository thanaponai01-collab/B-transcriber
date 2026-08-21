"""Stitch dedup for sub-word / zero-length Thai pieces (_coincident).

The fixed defect was misdiagnosed for a long time as an exact-text-matching
problem (see the old note in faster_whisper.py's _LONG_SPAN_SAFE_S block). It
was not: the seam duplicates matched on text fine, and were lost to the IoU
gate. Whisper's Thai output is sub-word — pieces run 20-80ms and combining
marks land at start == end, where IoU is structurally 0.0 and no threshold can
ever match. Real spans measured at a 42-46s window seam, all of which escaped
dedup and reached the transcript as stutter:

    'อะไร' 42580-42740  vs  ' อะไร' 42660-42760   IoU 0.44
    'ก'    42740-42880  vs  'ก'     42760-42820   IoU 0.43
    'ก'    43600-43600  vs  'ก'     43620-43620   IoU 0.00  (both zero-length)
    'จ'    45880-45960  vs  'จ'     45920-46000   IoU 0.33

Run: python -m pytest tests/test_stitch_subword_coincidence.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.contracts import RecognizedToken
from transcribe.audio.stitch import ChunkTokens, _coincident, _iou, stitch


def _t(text, s, e, conf=0.9):
    return RecognizedToken(text, s, e, conf, "thai")


def test_the_measured_seam_duplicates_are_all_below_the_iou_gate():
    """Guards the diagnosis itself: if IoU could see these, the fix is misplaced."""
    for a, b in [
        (_t("อะไร", 42580, 42740), _t("อะไร", 42660, 42760)),
        (_t("ก", 42740, 42880), _t("ก", 42760, 42820)),
        (_t("ก", 43600, 43600), _t("ก", 43620, 43620)),
        (_t("จ", 45880, 45960), _t("จ", 45920, 46000)),
    ]:
        assert _iou(a, b) < 0.5, f"{a.text!r} IoU {_iou(a, b):.2f} — no longer needs _coincident"
        assert _coincident(a, b), f"{a.text!r} not caught by _coincident either"


def test_zero_length_pieces_are_deduped_across_a_seam():
    """IoU is mathematically 0.0 for start == end pieces. This is the case that
    can never be fixed by tuning iou_threshold."""
    win2 = ChunkTokens(start_ms=21000, end_ms=46000, tokens=[_t("ก", 43600, 43600)])
    win3 = ChunkTokens(start_ms=42000, end_ms=46600, tokens=[_t("ก", 43620, 43620)])
    merged = stitch([win2, win3], seam_window_ms=4000)
    assert len(merged) == 1, "zero-length seam duplicate survived"


def test_short_subword_seam_duplicate_is_deduped():
    win2 = ChunkTokens(start_ms=21000, end_ms=46000, tokens=[_t("จ", 45880, 45960)])
    win3 = ChunkTokens(start_ms=42000, end_ms=46600, tokens=[_t("จ", 45920, 46000)])
    merged = stitch([win2, win3], seam_window_ms=4000)
    assert [t.text for t in merged] == ["จ"]


def test_genuine_repeated_thai_consonant_is_not_collapsed():
    """Thai repeats consonants constantly ('แบบ' = แ+บ+บ, 'รักกับ' = ...ก+ก).
    Real spans from the same clip, at a position covered by two windows — these
    are real speech and must both survive even when they are ~30ms apart."""
    # Same chunk: the ci != pci guard is the primary protection.
    same = ChunkTokens(start_ms=0, end_ms=25000,
                       tokens=[_t("บ", 6660, 6800), _t("บ", 6800, 6920)])
    assert len([t for t in stitch([same]) if t.text == "บ"]) == 2

    # Cross-chunk: centre distance (130ms) exceeds the duration-scaled tolerance,
    # so two genuinely distinct consonants still survive a seam.
    a = ChunkTokens(start_ms=0, end_ms=25000, tokens=[_t("บ", 6660, 6800)])
    b = ChunkTokens(start_ms=21000, end_ms=46000, tokens=[_t("บ", 6800, 6920)])
    assert len([t for t in stitch([a, b], seam_window_ms=4000) if t.text == "บ"]) == 2


def test_coincidence_scales_with_token_duration():
    # Two copies of one long word land far apart in absolute ms but are the same word.
    assert _coincident(_t("สวัสดี", 1000, 1600), _t("สวัสดี", 1200, 1800))
    # Two real utterances of a short word, back to back, are not.
    assert not _coincident(_t("นะ", 1000, 1200), _t("นะ", 1200, 1400))


def test_different_text_is_never_merged():
    """The loosened temporal test must not let unrelated characters collapse."""
    win2 = ChunkTokens(start_ms=21000, end_ms=46000, tokens=[_t("ก", 43600, 43600)])
    win3 = ChunkTokens(start_ms=42000, end_ms=46600, tokens=[_t("จ", 43610, 43610)])
    merged = stitch([win2, win3], seam_window_ms=4000)
    assert sorted(t.text for t in merged) == ["ก", "จ"]
