"""Frame-rate quantization for SRT/VTT export (Premiere recut frame-sync fix).

Premiere rounds ms timecodes to the sequence's own frame boundaries on
import; doing that rounding once here, per clip, at the clip's own fps
means the cue boundary Premiere shows matches what we intended instead of
drifting off by up to half a frame per cue.

Run: python -m pytest tests/test_fps_quantize.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.pipeline.align_force import _quantize_ms, _quantize_tokens, export_srt


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


def test_export_srt_without_fps_is_unquantized_passthrough():
    tokens = [{"text": "hello", "start_ms": 1001, "end_ms": 2003}]
    out_path = Path(__file__).parent / "_tmp_no_fps.srt"
    try:
        export_srt(tokens, str(out_path))
        content = out_path.read_text(encoding="utf-8")
        assert "00:00:01,001 --> 00:00:02,003" in content
    finally:
        out_path.unlink(missing_ok=True)


def test_export_srt_with_fps_quantizes_boundaries():
    tokens = [{"text": "hello", "start_ms": 1001, "end_ms": 2003}]
    out_path = Path(__file__).parent / "_tmp_with_fps.srt"
    try:
        export_srt(tokens, str(out_path), fps=25.0)
        content = out_path.read_text(encoding="utf-8")
        # 1001ms -> nearest 40ms tick = 1000ms; 2003ms -> 2000ms
        assert "00:00:01,000 --> 00:00:02,000" in content
    finally:
        out_path.unlink(missing_ok=True)
