"""Phrase-cue grouping for the faster-whisper adapter."""

from transcribe.engines.faster_whisper import _group_words_into_cues as group


def test_thai_pieces_rejoin_and_split_on_gap():
    # Sub-word Thai pieces; leading space marks word boundary. >700ms gap splits.
    words = [
        ("โ", 0, 200), ("อ", 200, 300), ("เค", 300, 500),
        (" โ", 600, 700), ("อ", 700, 750), ("เค", 750, 900),
        (" แต", 4000, 4200), ("่", 4200, 4250), ("ละ", 4250, 4500),
    ]
    cues = group(words, gap_ms=700, max_cue_ms=6000)
    assert [c[0] for c in cues] == ["โอเค โอเค", "แต่ละ"]
    assert cues[0][1] == 0 and cues[0][2] == 900


def test_long_run_splits_on_max_duration():
    words = [(f" w{i}", i * 1000, i * 1000 + 900) for i in range(10)]  # 10s, no gaps
    cues = group(words, gap_ms=700, max_cue_ms=6000)
    assert len(cues) >= 2
    assert all(c[2] - c[1] <= 7000 for c in cues)


def test_empty():
    assert group([]) == []
