"""Phrase-cue grouping for the faster-whisper adapter."""

from transcribe.engines.faster_whisper import (
    _group_words_into_cues as group,
    _sentence_boundary_offsets,
)


def test_splits_on_gap_and_preserves_text():
    # Sub-word Thai pieces; a >700ms gap forces a cue break. pythainlp finds the
    # word boundaries — the leading-space convention is not relied upon.
    words = [
        ("โ", 0, 200, 0.9), ("อ", 200, 300, 0.9), ("เค", 300, 500, 0.9),
        (" โ", 600, 700, 0.9), ("อ", 700, 750, 0.9), ("เค", 750, 900, 0.9),
        (" แต", 4000, 4200, 0.9), ("่", 4200, 4250, 0.9), ("ละ", 4250, 4500, 0.9),
    ]
    cues = group(words, gap_ms=700)
    assert [c[0] for c in cues] == ["โอเค โอเค", "แต่ละ"]
    assert cues[0][1] == 0 and cues[0][2] == 900


def test_cue_confidence_is_mean_of_constituent_words():
    words = [
        ("โ", 0, 200, 1.0), ("อ", 200, 300, 0.5), ("เค", 300, 500, None),
    ]
    cues = group(words, gap_ms=700)
    assert len(cues) == 1
    assert cues[0][3] == 0.75  # mean of 1.0 and 0.5; None words are excluded


def test_spaceless_thai_run_still_splits():
    # The original bug: a long spaceless Thai run never breaks because no piece
    # carries a leading space. Build ~12s of real Thai words with NO spaces.
    word = "มาดูคอมพราวด์ยางก่อนนะครับ"  # 6 segmentable words
    pieces = []
    t = 0
    for _ in range(8):
        for ch in word:
            pieces.append((ch, t, t + 100, 0.9))
            t += 100
    cues = group(pieces, gap_ms=700, target_ms=4000, target_chars=42)
    assert len(cues) >= 3                                  # actually splits
    assert all(c[2] - c[1] <= 5000 for c in cues)          # near the 4s target
    assert "".join(c[0] for c in cues) == word * 8         # no characters lost


def test_empty():
    assert group([]) == []


# ── sentence-boundary forcing ───────────────────────────────────────────────
# A cue must never open with the tail of one sentence fused to the head of
# the next. crfcut detects sentence boundaries in unpunctuated running text
# (Whisper's raw Thai output has no periods/commas) — these tests confirm
# that boundary forces a cue break even when nothing else would.

def test_sentence_boundary_offsets_finds_the_split():
    text = "ผมชื่อสมชายทำงานที่กรุงเทพ วันนี้อากาศดีมากเหมาะกับการเดินเล่น"
    offsets = _sentence_boundary_offsets(text)
    assert offsets == [len("ผมชื่อสมชายทำงานที่กรุงเทพ ")]


def test_sentence_boundary_offsets_degrades_to_empty_on_failure(monkeypatch):
    import pythainlp.tokenize as pt
    from transcribe.engines.faster_whisper import _sentence_boundary_offsets

    def boom(*a, **k):
        raise RuntimeError("model unavailable")

    # _sentence_boundary_offsets imports sent_tokenize locally from
    # pythainlp.tokenize on each call, so patching it here is what it sees.
    monkeypatch.setattr(pt, "sent_tokenize", boom)
    assert _sentence_boundary_offsets("ทดสอบ") == []


def test_group_words_forces_break_at_sentence_boundary_even_without_gap():
    # Two unrelated declarative sentences, zero silence between them, and
    # each character 50ms apart so the whole first sentence spans ~1.3s —
    # comfortably under target_ms/target_chars. Only sentence-boundary
    # detection explains a break here; gap/length heuristics alone would
    # keep everything in one cue.
    text = "ผมชื่อสมชายทำงานที่กรุงเทพ วันนี้อากาศดีมากเหมาะกับการเดินเล่น"
    words = []
    t = 0
    for ch in text:
        words.append((ch, t, t + 50, 0.9))
        t += 50
    cues = group(words, gap_ms=700, target_ms=4000, target_chars=42)
    assert len(cues) == 2
    assert cues[0][0] == "ผมชื่อสมชายทำงานที่กรุงเทพ"
    assert cues[1][0] == "วันนี้อากาศดีมากเหมาะกับการเดินเล่น"
    assert cues[0][2] <= cues[1][1]  # first cue ends at/before the second starts
