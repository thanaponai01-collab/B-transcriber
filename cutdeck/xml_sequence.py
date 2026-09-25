"""xml_sequence.py — facts read from an exported FCP7 sequence's XML.

Sequence timing (frame grid, Premiere ticks, the analysis window), Premiere's exploded stereo
channel groups and source-reference resolution (``<file>`` ids to media paths) live here.
``cutdeck.sequence_model.from_fcp7_xml`` builds the typed ``Sequence`` the analysis reads from
these; ``xml_recut`` uses them for the surgical rewrite. Everything here only reads; rewriting
stays in ``xml_recut``.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

from cutdeck.contracts import Timebase


# Premiere's internal high-precision tick rate (ticks/sec), constant across
# every frame rate — confirmed against a real export's own pproTicksOut
# (278977305600000 ticks for a 32948-frame @30fps clip => exactly
# 254016000000 ticks/sec, 2026-08-29). <pproTicksIn>/<pproTicksOut> are what
# Premiere's *audio* engine reads for playback precision; <in>/<out> are the
# frame-based numbers video playback and the rest of this transform use.
# Trimming a clip and updating only <in>/<out> leaves pproTicks pointing at
# the ORIGINAL untrimmed source range — video then plays from the right
# frame while audio silently plays from wherever the stale ticks pointed
# (confirmed on a real Premiere import, 2026-08-29: cuts landed correctly,
# every audio track was silent). Every trim must update both.
PPRO_TICKS_PER_SECOND = 254016000000


def frame_to_ticks(frame: int, tb: Timebase) -> int:
    exact = Fraction(frame * PPRO_TICKS_PER_SECOND * tb.fps_den, tb.fps_num)
    return exact.numerator // exact.denominator


class XmlRecutRefusal(ValueError):
    """Raised when the transform hits something it must not guess about."""


def child_text(el, tag, default=None):
    child = el.find(tag)
    return child.text if child is not None and child.text is not None else default


def sequence_timebase(sequence: ET.Element) -> Timebase:
    rate = sequence.find("rate")
    if rate is None:
        raise XmlRecutRefusal("sequence has no <rate> — cannot recut without a frame grid")
    timebase_el = rate.find("timebase")
    ntsc_el = rate.find("ntsc")
    if timebase_el is None or timebase_el.text is None:
        raise XmlRecutRefusal("sequence <rate> has no <timebase>")
    timebase_int = int(timebase_el.text)
    is_ntsc = (ntsc_el is not None and (ntsc_el.text or "").strip().upper() == "TRUE")
    fps_num, fps_den = (timebase_int * 1000, 1001) if is_ntsc else (timebase_int, 1)
    return Timebase(fps_num=fps_num, fps_den=fps_den)


def range_window_frames(tb: Timebase, seq_frames: int, frame_range: tuple[int, int],
                        pad_seconds: float = 2.0) -> tuple[int, int]:
    """Sequence-frame window ``[lo, hi]`` = the In/Out range plus ``pad_seconds``
    of context each side, clamped to the sequence. The pad is defined in seconds
    so the recognizer gets the same context at any frame rate."""
    pad = int(round(pad_seconds * tb.fps_num / tb.fps_den))
    return max(0, frame_range[0] - pad), min(seq_frames, frame_range[1] + pad)


def audio_track_groups(tracks: list[ET.Element]) -> list[int]:
    """The first XML track index of each Premiere audio track, from the export's audio <track>s.

    Real exports expand each stereo track into two XML tracks. Treating A2
    as XML index 1 would silently analyze A1 again. Verify the grouping.
    """
    groups = []
    index = 0
    while index < len(tracks):
        track = tracks[index]
        count = int(track.get("totalExplodedTrackCount", "1"))
        if count < 1 or index + count > len(tracks):
            raise ValueError("Cannot map the selected audio track from this export")
        for channel in range(count):
            item = tracks[index + channel]
            if (int(item.get("currentExplodedTrackIndex", "0")) != channel
                    or int(item.get("totalExplodedTrackCount", "1")) != count):
                raise ValueError("Audio channel grouping in the export is inconsistent")
        groups.append(index)
        index += count
    return groups


def pathurl_to_path(pathurl: str) -> Path:
    """Inverse of ``xml_export._pathurl`` — ``file://localhost/C%3A/...`` -> ``C:/...``."""
    parsed = urlparse(pathurl)
    raw = unquote(parsed.path)
    if len(raw) >= 3 and raw[0] == "/" and raw[2] == ":":
        raw = raw[1:]  # strip the leading '/' before a Windows drive letter
    return Path(raw)


def resolve_file_path(sequence: ET.Element, file_id: str) -> Path:
    """The real source path for a file id — found on whichever <file> element
    carries the full listing (the one with a <pathurl> child)."""
    for file_el in sequence.iter("file"):
        if file_el.get("id") == file_id:
            pathurl_el = file_el.find("pathurl")
            if pathurl_el is not None and pathurl_el.text:
                return pathurl_to_path(pathurl_el.text)
    raise XmlRecutRefusal(f"no <pathurl> found anywhere for file id {file_id!r} — "
                           f"source media path unknown")
