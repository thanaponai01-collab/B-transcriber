"""Phrase-cue grouping for the faster-whisper adapter."""

from transcribe.engines.faster_whisper import _group_words_into_cues as group


def test_splits_on_gap_and_preserves_text():
    # Sub-word Thai pieces; a >700ms gap forces a cue break. pythainlp finds the
    # word boundaries — the leading-space convention is not relied upon.
    words = [
        ("โ", 0, 200), ("อ", 200, 300), ("เค", 300, 500),
        (" โ", 600, 700), ("อ", 700, 750), ("เค", 750, 900),
        (" แต", 4000, 4200), ("่", 4200, 4250), ("ละ", 4250, 4500),
    ]
    cues = group(words, gap_ms=700)
    assert [c[0] for c in cues] == ["โอเค โอเค", "แต่ละ"]
    assert cues[0][1] == 0 and cues[0][2] == 900


def test_spaceless_thai_run_still_splits():
    # The original bug: a long spaceless Thai run never breaks because no piece
    # carries a leading space. Build ~12s of real Thai words with NO spaces.
    word = "มาดูคอมพราวด์ยางก่อนนะครับ"  # 6 segmentable words
    pieces = []
    t = 0
    for _ in range(8):
        for ch in word:
            pieces.append((ch, t, t + 100))
            t += 100
    cues = group(pieces, gap_ms=700, target_ms=4000, target_chars=42)
    assert len(cues) >= 3                                  # actually splits
    assert all(c[2] - c[1] <= 5000 for c in cues)          # near the 4s target
    assert "".join(c[0] for c in cues) == word * 8         # no characters lost


def test_empty():
    assert group([]) == []
