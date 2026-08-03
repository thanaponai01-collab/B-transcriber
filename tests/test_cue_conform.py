"""Phase 7b — cue-timing conform (align_force.conform_cues).

The fixed defect: the monotonic/no-overlap invariant lived *inside*
forced_align, and run.py skips Phase 7 entirely whenever the engine reports
timestamps_final — which faster_whisper always does. So on the only active
engine path the invariant was enforced nowhere, and an overlapping cue pair
(20 ending 42,740 / 21 starting 42,660) reached an exported SRT.

Run: python -m pytest tests/test_cue_conform.py -v
"""

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.contracts import PipelineToken
from transcribe.pipeline.align_force import ForcedToken, conform_cues, forced_align


@dataclass
class _Cue:
    """Minimal duck-typed cue — conform_cues must not require PipelineToken."""
    start_ms: int
    end_ms: int


def _tok(idx, start, end):
    return PipelineToken(idx=idx, text=f"t{idx}", start_ms=start, end_ms=end,
                         script="thai", confidence=None, source_engine="a")


def test_overlapping_cues_are_separated():
    # The exact shape observed in output/Short4.srt cues 20-21.
    toks = [_tok(0, 40800, 42740), _tok(1, 42660, 45120)]
    report = conform_cues(toks)
    assert report["overlaps_fixed"] == 1
    assert toks[1].start_ms == 42740
    assert toks[0].end_ms <= toks[1].start_ms


def test_no_overlap_survives_any_input():
    toks = [_tok(0, 0, 500), _tok(1, 400, 900), _tok(2, 850, 860), _tok(3, 855, 2000)]
    conform_cues(toks)
    for a, b in zip(toks, toks[1:]):
        assert a.end_ms <= b.start_ms, "conform_cues must guarantee no overlap"
        assert a.start_ms < a.end_ms, "every cue must have positive duration"


def test_small_gaps_are_closed_but_real_pauses_are_kept():
    # 140ms is timestamp noise (flickers a burned-in subtitle); 900ms is a pause.
    toks = [_tok(0, 0, 1000), _tok(1, 1140, 2000), _tok(2, 2900, 3500)]
    report = conform_cues(toks, max_close_gap_ms=200)
    assert report["gaps_closed"] == 1
    assert toks[0].end_ms == 1140          # noise gap closed
    assert toks[1].end_ms == 2000          # real pause untouched
    assert toks[2].start_ms == 2900


def test_gap_closing_is_off_by_default():
    toks = [_tok(0, 0, 1000), _tok(1, 1140, 2000)]
    report = conform_cues(toks)
    assert report["gaps_closed"] == 0
    assert toks[0].end_ms == 1000


def test_bounds_are_clamped_to_audio_duration():
    toks = [_tok(0, -50, 500), _tok(1, 9000, 99000)]
    report = conform_cues(toks, duration_ms=10000)
    assert report["bounds_clamped"] == 2
    assert toks[0].start_ms == 0
    assert toks[1].end_ms == 10000


def test_zero_length_cue_gets_positive_duration():
    toks = [_tok(0, 500, 500)]
    conform_cues(toks)
    assert toks[0].end_ms > toks[0].start_ms


def test_idx_is_reindexed_when_sorting_moves_a_token():
    toks = [_tok(0, 2000, 3000), _tok(1, 0, 1000)]
    conform_cues(toks)
    assert [t.start_ms for t in toks] == [0, 2000]
    assert [t.idx for t in toks] == [0, 1], "idx is positional for every consumer"


def test_works_on_objects_without_idx():
    cues = [_Cue(100, 500), _Cue(400, 900)]
    conform_cues(cues)               # must not raise on a token type lacking idx
    assert cues[1].start_ms == 500


def test_empty_input():
    assert conform_cues([]) == {"overlaps_fixed": 0, "gaps_closed": 0, "bounds_clamped": 0}


def test_forced_align_still_clamps_and_does_not_close_gaps():
    """forced_align delegates to conform_cues now — word-level behaviour unchanged.
    Gaps between words are real pauses, so gap-closing must stay off there."""
    import numpy as np

    class _Aligner:
        def align(self, audio, sr, words):
            # Deliberately broken: overlapping, out of bounds, and gapped.
            return [ForcedToken("a", -100, 600), ForcedToken("b", 500, 700),
                    ForcedToken("c", 800, 99999)]

    audio = np.zeros(16000, dtype="float32")  # 1000 ms at 16 kHz
    out = forced_align(audio, 16000, ["a", "b", "c"], aligner=_Aligner())
    assert out[0].start_ms == 0
    assert out[1].start_ms == 600            # overlap pushed to previous end
    assert out[2].end_ms == 1000             # clamped to duration
    assert out[1].end_ms == 700              # 100ms word gap NOT closed
