"""Phase 3 acceptance — ffmpeg concat-demuxer preview render (HANDOFF_CUTDECK_WORDLEVEL.md).

Uses the real ffmpeg on PATH against a tiny synthetic ``lavfi testsrc`` clip so the
acceptance criteria (duration match, shorter-by-cuts, missing-ffmpeg message) are
checked against actual ffmpeg behaviour, not a mock of it.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from cutdeck.contracts import CUT, KEEP, CutPlan, CutSpan, Timebase
from cutdeck.preview import FfmpegNotFoundError, keep_ranges_ms, render_preview

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

pytestmark = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe not on PATH")


def _synthetic_media(tmp_path: Path, seconds: int = 6) -> Path:
    """A tiny CFR H.264+AAC clip with keyframes every 0.5s, so stream-copy cuts
    land close to the requested boundaries."""
    out = tmp_path / "source.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=64x64:rate=25",
        "-f", "lavfi", "-i", f"sine=duration={seconds}:frequency=440",
        "-c:v", "libx264", "-g", "12", "-force_key_frames", "expr:gte(t,n_forced*0.5)",
        "-c:a", "aac", str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out


def _probe_duration_ms(path: Path) -> int:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "json", str(path)]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return round(float(json.loads(out)["format"]["duration"]) * 1000)


def _plan(spans, duration_ms):
    tb = Timebase(fps_num=25, fps_den=1, duration_ms=duration_ms)
    return CutPlan(job_id=1, media_sha256="x" * 64, timebase=tb, spans=spans)


def test_keep_ranges_ms_extracts_only_keep_spans():
    plan = _plan([
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=KEEP),
        CutSpan(idx=1, src_in_ms=1000, src_out_ms=2000, action=CUT),
        CutSpan(idx=2, src_in_ms=2000, src_out_ms=3000, action=KEEP),
    ], 3000)
    assert keep_ranges_ms(plan) == [(0, 1000), (2000, 3000)]


def test_all_keep_plan_reproduces_source_duration_within_one_gop(tmp_path):
    src = _synthetic_media(tmp_path, seconds=4)
    src_ms = _probe_duration_ms(src)
    plan = _plan([CutSpan(idx=0, src_in_ms=0, src_out_ms=src_ms, action=KEEP)], src_ms)

    out = render_preview(plan, str(src), tmp_path / "preview.mp4")
    out_ms = _probe_duration_ms(out)

    gop_ms = 500  # matches the forced keyframe interval in _synthetic_media
    assert abs(out_ms - src_ms) <= gop_ms


def test_plan_with_cuts_is_shorter_by_approximately_the_cut_total(tmp_path):
    src = _synthetic_media(tmp_path, seconds=6)
    src_ms = _probe_duration_ms(src)
    cut_ms = 2000
    plan = _plan([
        CutSpan(idx=0, src_in_ms=0, src_out_ms=2000, action=KEEP),
        CutSpan(idx=1, src_in_ms=2000, src_out_ms=2000 + cut_ms, action=CUT, reason="silence"),
        CutSpan(idx=2, src_in_ms=2000 + cut_ms, src_out_ms=src_ms, action=KEEP),
    ], src_ms)

    out = render_preview(plan, str(src), tmp_path / "preview.mp4")
    out_ms = _probe_duration_ms(out)

    gop_ms = 500
    assert abs((src_ms - out_ms) - cut_ms) <= gop_ms


def test_missing_ffmpeg_raises_clear_error_not_traceback(tmp_path):
    plan = _plan([CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=KEEP)], 1000)
    with pytest.raises(FfmpegNotFoundError, match="not found on PATH"):
        render_preview(plan, "unused.mp4", tmp_path / "out.mp4", ffmpeg_bin="not-a-real-ffmpeg-binary")


def test_no_keep_spans_raises_value_error(tmp_path):
    plan = _plan([CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=CUT)], 1000)
    with pytest.raises(ValueError, match="no keep"):
        render_preview(plan, "unused.mp4", tmp_path / "out.mp4")


def test_single_keep_span_copies_without_concat(tmp_path):
    src = _synthetic_media(tmp_path, seconds=2)
    src_ms = _probe_duration_ms(src)
    plan = _plan([CutSpan(idx=0, src_in_ms=0, src_out_ms=src_ms, action=KEEP)], src_ms)

    out = render_preview(plan, str(src), tmp_path / "preview.mp4")
    assert out.exists()
    assert _probe_duration_ms(out) > 0


def test_reencode_is_frame_accurate(tmp_path):
    src = _synthetic_media(tmp_path, seconds=6)
    src_ms = _probe_duration_ms(src)
    cut_ms = 2000
    plan = _plan([
        CutSpan(idx=0, src_in_ms=0, src_out_ms=2000, action=KEEP),
        CutSpan(idx=1, src_in_ms=2000, src_out_ms=2000 + cut_ms, action=CUT),
        CutSpan(idx=2, src_in_ms=2000 + cut_ms, src_out_ms=src_ms, action=KEEP),
    ], src_ms)

    out = render_preview(plan, str(src), tmp_path / "preview.mp4", reencode=True)
    out_ms = _probe_duration_ms(out)

    # Re-encoded cuts land on the requested frame, not the nearest keyframe —
    # a much tighter tolerance than the stream-copy GOP case above.
    assert abs((src_ms - out_ms) - cut_ms) <= 100
