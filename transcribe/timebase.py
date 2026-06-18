"""Timebase — the single authority for millisecond↔frame conversion.

GAP-1. Once XML export exists, every millisecond stored on a token must be
convertible to an exact frame number under the source media's true rational
frame rate. Float frame rates accumulate drift over long timelines, so this
module does *exact integer math on the rational rate only*.

Grep-able rule enforced by tests: a decimal NTSC fps literal must never appear in
the codebase. Rates are always carried as the integer pair ``(fps_num, fps_den)``
— NTSC 30 is 30000/1001, NTSC 24 is 24000/1001, PAL 25 is 25/1.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional

logger = logging.getLogger(__name__)

_TARGET_SR = 16000


@dataclass(frozen=True)
class Timebase:
    """The exact, rational frame rate of a piece of source media.

    fps_num/fps_den is the truth; ``ntsc`` and the decimal rate are derived
    views for human display and FCP7 XML — never inputs to frame math.
    """
    fps_num: int
    fps_den: int
    sample_rate: int = _TARGET_SR
    duration_ms: Optional[int] = None
    is_vfr: bool = False

    def __post_init__(self) -> None:
        if self.fps_num <= 0 or self.fps_den <= 0:
            raise ValueError(f"Invalid frame rate {self.fps_num}/{self.fps_den}")

    @property
    def ntsc(self) -> bool:
        """FCP7 expresses 30000/1001 etc. as an integer timebase + ntsc flag.

        Map: fps_den == 1001 → ntsc TRUE; else ntsc FALSE.
        """
        return self.fps_den == 1001

    @property
    def fps_fraction(self) -> Fraction:
        return Fraction(self.fps_num, self.fps_den)


def ms_to_frame(ms: float, tb: Timebase) -> int:
    """Convert a millisecond offset to the nearest frame index.

    Exact: frame = round(ms * fps_num / (fps_den * 1000)) evaluated over
    ``Fraction`` so no float fps ever enters the arithmetic.
    """
    exact = Fraction(int(round(ms)) * tb.fps_num, tb.fps_den * 1000)
    return _round_half_up(exact)


def frame_to_ms(frame: int, tb: Timebase) -> float:
    """Convert a frame index back to its exact millisecond offset.

    ms = frame * fps_den * 1000 / fps_num. Returned as float for storage, but
    computed exactly first so round-tripping never compounds error.
    """
    exact = Fraction(frame * tb.fps_den * 1000, tb.fps_num)
    return float(exact)


def _round_half_up(value: Fraction) -> int:
    """Round a Fraction to the nearest int, ties going up — deterministic and
    float-free (Python's round() is banker's rounding and takes floats)."""
    floor = value.numerator // value.denominator
    remainder = value - floor
    return floor + 1 if remainder >= Fraction(1, 2) else floor


def probe(media_path: str) -> Timebase:
    """Probe a media file's true frame rate, sample rate, and duration via ffprobe.

    Uses ``avg_frame_rate`` as truth. If ``r_frame_rate != avg_frame_rate`` the
    source is variable-frame-rate (VFR) — flagged via ``is_vfr`` so downstream
    frame-based export (GAP-2) can refuse or conform a CFR proxy.

    Falls back to a 25/1 timebase if ffprobe is unavailable or the file has no
    video stream (audio-only) — frame math is only meaningful once a video
    track exists, but a sane default keeps the contract total.
    """
    try:
        info = _ffprobe(media_path)
    except Exception as e:  # ffprobe missing, malformed file, etc.
        logger.warning("ffprobe failed for %s (%s); defaulting to 25fps CFR", media_path, e)
        return Timebase(fps_num=25, fps_den=1)

    duration_ms = info.get("duration_ms")
    sample_rate = info.get("sample_rate") or _TARGET_SR

    v = info.get("video")
    if v is None:
        # Audio-only: no frames to convert against, but stay total.
        return Timebase(fps_num=25, fps_den=1, sample_rate=sample_rate, duration_ms=duration_ms)

    avg_num, avg_den = v["avg"]
    r_num, r_den = v["r"]
    # VFR when the average rate disagrees with the nominal container rate.
    is_vfr = (avg_num * r_den) != (r_num * avg_den)
    return Timebase(
        fps_num=avg_num,
        fps_den=avg_den,
        sample_rate=sample_rate,
        duration_ms=duration_ms,
        is_vfr=is_vfr,
    )


def _parse_rate(rate: str) -> tuple[int, int]:
    """Parse an ffprobe rate string like '30000/1001' into (num, den)."""
    if "/" in rate:
        num, den = rate.split("/", 1)
        num, den = int(num), int(den)
    else:
        num, den = int(rate), 1
    if den == 0:
        return 0, 1
    return num, den


def _ffprobe(media_path: str) -> dict:
    """Run ffprobe and extract video rate(s), audio sample rate, duration_ms."""
    cmd = [
        "ffprobe", "-v", "error", "-of", "json",
        "-show_entries",
        "stream=codec_type,r_frame_rate,avg_frame_rate,sample_rate:format=duration",
        media_path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    data = json.loads(out)

    result: dict = {}
    fmt = data.get("format", {})
    if "duration" in fmt:
        try:
            result["duration_ms"] = int(round(float(fmt["duration"]) * 1000))
        except (TypeError, ValueError):
            pass

    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and "video" not in result:
            avg = _parse_rate(stream.get("avg_frame_rate", "0/1"))
            r = _parse_rate(stream.get("r_frame_rate", "0/1"))
            # ffprobe reports 0/0 for some still streams; guard against it.
            if avg == (0, 1):
                avg = r if r != (0, 1) else (25, 1)
            if r == (0, 1):
                r = avg
            result["video"] = {"avg": avg, "r": r}
        elif stream.get("codec_type") == "audio" and "sample_rate" not in result:
            try:
                result["sample_rate"] = int(stream["sample_rate"])
            except (TypeError, ValueError, KeyError):
                pass

    return result
