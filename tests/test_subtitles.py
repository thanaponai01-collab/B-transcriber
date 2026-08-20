"""Acceptance tests for transcribe/subtitles/ — the shared SRT/VTT read+write
module (issue #7). Covers frame-rate quantization (moved from
test_fps_quantize.py), SRT parsing (moved from test_phase7_makegold.py's
srt-parsing assertions), and the write->read round trip this module makes
newly expressible.

Run: python -m pytest tests/test_subtitles.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.subtitles import _quantize_ms, _quantize_tokens, read_subtitles, write_subtitles


# ── frame-rate quantization (moved from test_fps_quantize.py) ─────────────────

def test_quantize_ms_snaps_to_frame_boundary():
    fps = 25.0  # frame_ms = 40
    assert _quantize_ms(0, fps) == 0
    assert _quantize_ms(39, fps) == 40
    assert _quantize_ms(21, fps) == 40
    assert _quantize_ms(19, fps) == 0


def test_quantize_ms_handles_ntsc_drop_frame_rate():
    fps = 29.97
    frame_ms = 1000.0 / fps
    # The quantized ms (an int) can't be an exact multiple of the
    # irrational-ish frame_ms, but it must land on the *same* frame index
    # as the pre-quantized value — that's the actual invariant Premiere cares
    # about (which frame the cue boundary snaps to).
    ms = 12345
    q = _quantize_ms(ms, fps)
    assert round(q / frame_ms) == round(ms / frame_ms)


def test_quantize_tokens_never_collapses_a_cue():
    # A very short cue whose start/end round to the same frame must not
    # become zero-duration — that would make it invisible/unselectable
    # in Premiere.
    toks = [{"text": "x", "start_ms": 100, "end_ms": 105}]
    out = _quantize_tokens(toks, fps=25.0)
    assert out[0]["end_ms"] > out[0]["start_ms"]


def test_write_subtitles_without_fps_is_unquantized_passthrough():
    tokens = [{"text": "hello", "start_ms": 1001, "end_ms": 2003}]
    content = write_subtitles(tokens, "srt")
    assert "00:00:01,001 --> 00:00:02,003" in content


def test_write_subtitles_with_fps_quantizes_boundaries():
    tokens = [{"text": "hello", "start_ms": 1001, "end_ms": 2003}]
    content = write_subtitles(tokens, "srt", fps=25.0)
    # 1001ms -> nearest 40ms tick = 1000ms; 2003ms -> 2000ms
    assert "00:00:01,000 --> 00:00:02,000" in content


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
