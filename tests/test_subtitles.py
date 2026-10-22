"""Acceptance tests for transcribe/subtitles/ — the shared SRT/VTT read+write
module (issue #7). Covers frame-exact cue snapping, SRT parsing (moved from test_phase7_makegold.py's
srt-parsing assertions), and the write->read round trip this module makes
newly expressible.

Run: python -m pytest tests/test_subtitles.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import math
from fractions import Fraction

import pytest

from transcribe.subtitles import frame_cues, read_subtitles, write_subtitles
from transcribe.timebase import Timebase, frame_to_ms


# ── frame-exact cues ──────────────────────────────────────────────────────────
# Premiere snaps each SRT time to a frame of the sequence. Every boundary we
# write must already name one frame, whichever way Premiere rounds, so what we
# wrote is what the timeline shows.

RATES = [Timebase(25, 1), Timebase(50, 1), Timebase(24000, 1001),
         Timebase(30000, 1001), Timebase(60000, 1001)]


def _frame_of(ms: int, tb: Timebase, rounding) -> int:
    return rounding(Fraction(ms * tb.fps_num, tb.fps_den * 1000))


@pytest.mark.parametrize("tb", RATES, ids=lambda tb: f"{tb.fps_num}/{tb.fps_den}")
def test_every_boundary_names_one_frame_under_round_or_ceil(tb):
    cues = [{"text": "x", "start_ms": ms, "end_ms": ms + 777} for ms in range(0, 600_000, 1_013)]
    for cue in frame_cues(cues, tb):
        for ms in (cue["start_ms"], cue["end_ms"]):
            nearest = _frame_of(ms, tb, round)
            assert _frame_of(ms, tb, math.ceil) == nearest, (ms, tb)
            assert frame_to_ms(nearest, tb) - 1 < ms <= frame_to_ms(nearest, tb)


def test_frame_cues_snaps_to_nearest_frame():
    out = frame_cues([{"text": "x", "start_ms": 1019, "end_ms": 2021}], Timebase(25, 1))
    assert (out[0]["start_ms"], out[0]["end_ms"]) == (1000, 2040)


def test_sub_frame_cue_keeps_one_frame():
    # Premiere drops a cue shorter than a frame (PREMIERE_FACTS "Sub-frame SRT cue").
    out = frame_cues([{"text": "x", "start_ms": 75_889, "end_ms": 75_890}], Timebase(30000, 1001))
    frames = [_frame_of(out[0][k], Timebase(30000, 1001), round) for k in ("start_ms", "end_ms")]
    assert frames[1] - frames[0] == 1


def test_cues_sharing_a_frame_never_overlap():
    cues = [{"text": "a", "start_ms": 1000, "end_ms": 1010},
            {"text": "b", "start_ms": 1010, "end_ms": 1015},
            {"text": "c", "start_ms": 1015, "end_ms": 2000}]
    out = frame_cues(cues, Timebase(25, 1))
    assert [(c["start_ms"], c["end_ms"]) for c in out] == [(1000, 1040), (1040, 1080), (1080, 2000)]


def test_pushed_cues_never_overlap_a_later_cue_past_a_real_gap():
    # a and b are each stretched to one frame, so b ends on frame 27; c starts 40 ms
    # after b's raw end (not a sub-frame gap) yet its nearest frame is 26.
    cues = [{"text": "a", "start_ms": 1000, "end_ms": 1001},
            {"text": "b", "start_ms": 1002, "end_ms": 1003},
            {"text": "c", "start_ms": 1043, "end_ms": 2000}]
    out = frame_cues(cues, Timebase(25, 1))
    assert [(c["start_ms"], c["end_ms"]) for c in out] == [(1000, 1040), (1040, 1080), (1080, 2000)]


def test_gapless_cues_stay_gapless_on_the_frame():
    tb = Timebase(30000, 1001)
    cues = [{"text": str(i), "start_ms": i * 1237, "end_ms": (i + 1) * 1237} for i in range(200)]
    out = frame_cues(cues, tb)
    assert all(a["end_ms"] == b["start_ms"] for a, b in zip(out, out[1:]))


def test_sub_frame_gap_closes_but_a_real_gap_stays():
    tb = Timebase(25, 1)
    cues = [{"text": "a", "start_ms": 0, "end_ms": 1019},      # end -> frame 25
            {"text": "b", "start_ms": 1044, "end_ms": 2000},   # 25 ms gap -> would be frame 26
            {"text": "c", "start_ms": 2080, "end_ms": 3000}]   # 2-frame gap is a pause
    out = frame_cues(cues, tb)
    assert out[1]["start_ms"] == out[0]["end_ms"] == 1000
    assert out[2]["start_ms"] - out[1]["end_ms"] == 80


def test_write_subtitles_with_fps_writes_frame_exact_stamps():
    content = write_subtitles([{"text": "hello", "start_ms": 1001, "end_ms": 2003}], "srt", fps=29.97)
    # frames 30 and 60 at 30000/1001: 1001.0 ms and 2002.0 ms exactly
    assert "00:00:01,001 --> 00:00:02,002" in content


def test_write_subtitles_without_fps_is_unquantized_passthrough():
    tokens = [{"text": "hello", "start_ms": 1001, "end_ms": 2003}]
    content = write_subtitles(tokens, "srt")
    assert "00:00:01,001 --> 00:00:02,003" in content


def test_write_subtitles_rejects_unknown_format():
    import pytest
    with pytest.raises(ValueError):
        write_subtitles([{"text": "x", "start_ms": 0, "end_ms": 100}], "ass")


def test_read_subtitles_rejects_unknown_format():
    import pytest
    with pytest.raises(ValueError):
        read_subtitles("1\n00:00:00,000 --> 00:00:01,000\nx\n\n", "ass")


# ── SRT parsing (moved from test_phase7_makegold.py) ──────────────────────────

def test_read_subtitles_parses_cues_with_bom_and_scripts():
    srt = (
        "﻿1\n00:00:00,000 --> 00:00:02,580\nสวัสดีครับ\n\n"
        "2\n00:00:02,580 --> 00:00:04,340\nHello world\n\n"
    )
    toks = read_subtitles(srt, "srt")
    assert toks == [
        {"text": "สวัสดีครับ", "script": "thai", "start_ms": 0, "end_ms": 2580},
        {"text": "Hello world", "script": "latin", "start_ms": 2580, "end_ms": 4340},
    ]


def test_read_subtitles_joins_multiline_cue_text():
    srt = "1\n00:00:01,000 --> 00:00:02,000\nline one\nline two\n\n"
    toks = read_subtitles(srt, "srt")
    assert toks[0]["text"] == "line one line two"


def test_read_subtitles_strips_nle_font_markup():
    # NLE exports (e.g. Premiere) can carry <font color=...> on-screen styling
    # markup — pinning the fix that stops it landing in a correction/gold row
    # as if it were transcript text.
    srt = (
        '1\n00:00:00,000 --> 00:00:01,000\n<font color="#FFFFFF">hello world</font>\n\n'
    )
    toks = read_subtitles(srt, "srt")
    assert toks[0]["text"] == "hello world"


# ── write -> read round trip ───────────────────────────────────────────────────
# The property no prior module could express: what we write, re-imported,
# comes back as the same cues. Exact when quantization is a no-op (the
# default, fps=None); still exercised under quantization to confirm the
# guarantee degrades to "same frame", not silent divergence.

def test_srt_round_trip_thai_and_mixed_no_quantization():
    tokens = [
        {"text": "สวัสดีครับ", "start_ms": 0, "end_ms": 1500},
        {"text": "Hello สวัสดี world", "start_ms": 1500, "end_ms": 3200},
    ]
    content = write_subtitles(tokens, "srt")
    parsed = read_subtitles(content, "srt")
    assert [{"text": p["text"], "start_ms": p["start_ms"], "end_ms": p["end_ms"]} for p in parsed] == tokens
    assert parsed[0]["script"] == "thai"
    assert parsed[1]["script"] == "mixed"


def test_vtt_round_trip():
    tokens = [
        {"text": "สวัสดีครับ", "start_ms": 0, "end_ms": 1500},
        {"text": "Hello world", "start_ms": 1500, "end_ms": 3200},
    ]
    content = write_subtitles(tokens, "vtt")
    assert content.startswith("WEBVTT\n")
    parsed = read_subtitles(content, "vtt")
    assert [{"text": p["text"], "start_ms": p["start_ms"], "end_ms": p["end_ms"]} for p in parsed] == tokens


def test_srt_round_trip_already_frame_aligned_is_lossless_under_quantization():
    fps = 25.0  # frame_ms = 40, exact — every multiple of 40ms is already on a frame
    tokens = [{"text": "hello", "start_ms": 40, "end_ms": 2000}]
    content = write_subtitles(tokens, "srt", fps=fps)
    parsed = read_subtitles(content, "srt")
    assert parsed[0]["start_ms"] == 40
    assert parsed[0]["end_ms"] == 2000


def test_write_skips_blank_cues_and_renumbers():
    tokens = [
        {"text": "one", "start_ms": 0, "end_ms": 500},
        {"text": "  ", "start_ms": 500, "end_ms": 900},
        {"text": "", "start_ms": 900, "end_ms": 950},
        {"text": "two", "start_ms": 1000, "end_ms": 2000},
    ]
    parsed = read_subtitles(write_subtitles(tokens, "srt"), "srt")
    assert [p["text"] for p in parsed] == ["one", "two"]
    assert write_subtitles(tokens, "srt").count("-->") == 2
    assert "\n2\n00:00:01,000" in write_subtitles(tokens, "srt")


def test_write_text_blank_line_cannot_split_a_cue():
    tokens = [{"text": "hi\n\n2\n00:00 --> x", "start_ms": 0, "end_ms": 1000}]
    out = write_subtitles(tokens, "srt")
    assert "\n\n" not in out.rstrip("\n")
