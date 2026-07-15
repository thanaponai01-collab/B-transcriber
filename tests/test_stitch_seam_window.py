"""Stitch seam-window dedup: a duplicate separated from its twin by an
intervening token (A-B-A' in the time-sorted stream) must still be deduped.

The fixed defect: stitch() compared each candidate only against kept[-1], so a
short token from the other chunk landing between the two copies of a seam word
hid the duplicate. The comparison now covers every recently-kept token within
seam_window_ms of the candidate's start, keeping the existing
interiority/confidence tie-break.

Run: python -m pytest tests/test_stitch_seam_window.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.contracts import RecognizedToken
from transcribe.pipeline.stitch import ChunkTokens, stitch


def test_intervening_token_does_not_hide_a_seam_duplicate():
    chunk0 = ChunkTokens(
        start_ms=0, end_ms=1200,
        tokens=[
            RecognizedToken("hello", 0, 400, 0.9, "latin"),
            RecognizedToken("there", 400, 800, 0.9, "latin"),
            RecognizedToken("world", 800, 1200, 0.8, "latin"),  # near right seam
        ],
    )
    chunk1 = ChunkTokens(
        start_ms=800, end_ms=2400,
        tokens=[
            # Short filler only the second decode heard — sorts BETWEEN the two
            # copies of "world", which is exactly what defeated the kept[-1] check.
            RecognizedToken("uh", 810, 900, 0.4, "latin"),
            RecognizedToken("world", 820, 1220, 0.7, "latin"),  # deeper in its chunk
            RecognizedToken("again", 1250, 1700, 0.9, "latin"),
        ],
    )
    merged = stitch([chunk0, chunk1], iou_threshold=0.5)
    worlds = [t for t in merged if t.text == "world"]
    assert len(worlds) == 1, "A-B-A' seam duplicate not deduped"
    # Interiority tie-break unchanged: chunk1's copy sits deeper in its chunk.
    assert worlds[0].start_ms == 820
    assert [t.text for t in merged] == ["hello", "there", "uh", "world", "again"]
    # Output must stay time-ordered even after an interior replacement.
    starts = [t.start_ms for t in merged]
    assert starts == sorted(starts)


def test_legitimate_repetition_outside_the_seam_survives():
    # The same word said twice, far apart — no temporal overlap, never a dup.
    chunk0 = ChunkTokens(
        start_ms=0, end_ms=1200,
        tokens=[RecognizedToken("ครับ", 0, 300, 0.9, "thai")],
    )
    chunk1 = ChunkTokens(
        start_ms=800, end_ms=6000,
        tokens=[RecognizedToken("ครับ", 5000, 5300, 0.9, "thai")],
    )
    merged = stitch([chunk0, chunk1])
    assert [t.text for t in merged] == ["ครับ", "ครับ"]


def test_same_chunk_repetition_in_window_survives():
    # Both copies from the SAME chunk are real speech (stutter/repeat), not a
    # seam artifact — the ci != pci guard must keep applying across the window.
    chunk0 = ChunkTokens(
        start_ms=0, end_ms=2000,
        tokens=[
            RecognizedToken("ไป", 100, 300, 0.9, "thai"),
            RecognizedToken("นะ", 120, 140, 0.9, "thai"),
            RecognizedToken("ไป", 150, 350, 0.9, "thai"),  # IoU 0.6 with the first
        ],
    )
    merged = stitch([chunk0])
    assert [t.text for t in merged].count("ไป") == 2
