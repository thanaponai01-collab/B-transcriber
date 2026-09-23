"""xml_sequence.py — the one owner of facts read from an exported FCP7 sequence.

Sequence timing (frame grid, Premiere ticks, the analysis window), reference
audio track selection (including Premiere's exploded stereo channel groups) and
source-reference resolution (``<file>`` ids to media paths, clip source spans)
live here, so audio extraction, multi-cam sync, the Premiere helper and the
surgical rewrite in ``xml_recut`` all read the XML the same way. Everything
here only reads; rewriting stays in ``xml_recut``.

**Track selection:** one audio track is picked as the "reference" dialogue
track for VAD (default: the first track that is switched on and has any
clips). An explicit index is honored even when that track is switched off —
the editor chose it, and a lav track muted in the mix is still the best
thing to analyze. A sequence with several isolated mic tracks needs the
editor to say which one carries the dialogue that should drive silence
detection — this module does not guess by loudness or any other heuristic.

``check_reference_audio`` runs the same selection plus the checks that can
be made without decoding anything, so a job can be refused before ASR.
"""

from __future__ import annotations

import json
import shutil
import subprocess
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


def audio_track_groups(source_xml: str) -> list[int]:
    """The first XML track index of each Premiere audio track.

    Real exports expand each stereo track into two XML tracks. Treating A2
    as XML index 1 would silently analyze A1 again. Verify the grouping.
    """
    tracks = ET.fromstring(source_xml).findall("sequence/media/audio/track")
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


def clip_source_span_seconds(clipitem: ET.Element, tb: Timebase) -> tuple[float, float]:
    """(in_seconds, out_seconds) in the SOURCE file's own timeline. Prefers
    pproTicksIn/pproTicksOut (sub-frame precision) when present, falls back
    to the frame-based <in>/<out> otherwise."""
    ticks_in = clipitem.find("pproTicksIn")
    ticks_out = clipitem.find("pproTicksOut")
    if ticks_in is not None and ticks_in.text and ticks_out is not None and ticks_out.text:
        return (int(ticks_in.text) / PPRO_TICKS_PER_SECOND,
                int(ticks_out.text) / PPRO_TICKS_PER_SECOND)
    in_frame = int(child_text(clipitem, "in", "0"))
    out_frame = int(child_text(clipitem, "out", "0"))
    return (float(Fraction(in_frame * tb.fps_den, tb.fps_num)),
            float(Fraction(out_frame * tb.fps_den, tb.fps_num)))


def select_audio_track(sequence: ET.Element, audio_track_index: int | None) -> ET.Element:
    audio = sequence.find("media/audio")
    tracks = audio.findall("track") if audio is not None else []
    if not tracks:
        raise XmlRecutRefusal("sequence has no audio tracks to extract from")
    if audio_track_index is not None:
        if not 0 <= audio_track_index < len(tracks):
            raise XmlRecutRefusal(
                f"sequence has {len(tracks)} audio track(s), requested index "
                f"{audio_track_index} (0-based)"
            )
        return tracks[audio_track_index]
    with_clips = [track for track in tracks if track.findall("clipitem")]
    if not with_clips:
        raise XmlRecutRefusal("no audio track has any clips")
    for track in with_clips:
        if child_text(track, "enabled", "TRUE") == "TRUE":
            return track
    raise XmlRecutRefusal("every audio track with clips is switched off; "
                          "choose a Reference Audio track")


def enabled_clips(track: ET.Element) -> list[ET.Element]:
    """Clipitems that contribute audio: enabled and naming a source file."""
    return [clipitem for clipitem in track.findall("clipitem")
            if child_text(clipitem, "enabled", "TRUE") == "TRUE"
            and clipitem.find("file") is not None
            and clipitem.find("file").get("id") is not None]


def _has_audio_stream(path: Path) -> bool | None:
    """True/False from ffprobe, or None when ffprobe cannot answer (missing, unreadable)."""
    if shutil.which("ffprobe") is None:
        return None
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-of", "json", "-show_entries", "stream=codec_type",
         str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        return None
    try:
        streams = json.loads(result.stdout).get("streams", [])
    except ValueError:
        return None
    return any(stream.get("codec_type") == "audio" for stream in streams)


def check_reference_audio(source_xml: str, audio_track_index: int | None = None) -> dict:
    """Refuse, before any audio is extracted or transcribed, what ``extract_mixdown``
    would fail on or silently get wrong. Returns what will be analyzed.

    Checks: the reference track selection itself; every enabled clip names a
    source file that exists and has an audio stream; a clip without
    ``pproTicksIn``/``pproTicksOut`` has no ``<rate>`` of its own that differs
    from the sequence's (``clip_source_span_seconds`` would read its
    ``<in>``/``<out>`` on the wrong frame grid). A source frame rate that
    differs from the sequence is otherwise fine: extraction works in seconds.
    """
    sequence = ET.fromstring(source_xml).find("sequence")
    if sequence is None:
        raise XmlRecutRefusal("no <sequence> element found in source XML")
    tb = sequence_timebase(sequence)
    audio = sequence.find("media/audio")
    tracks = audio.findall("track") if audio is not None else []
    track = select_audio_track(sequence, audio_track_index)
    clips = enabled_clips(track)
    if not clips:
        raise XmlRecutRefusal("the reference audio track has no enabled clips")

    files: list[Path] = []
    for clipitem in clips:
        path = resolve_file_path(sequence, clipitem.find("file").get("id"))
        if path not in files:
            files.append(path)
        has_ticks = clipitem.find("pproTicksIn") is not None
        rate = clipitem.find("rate")
        if not has_ticks and rate is not None:
            clip_tb = sequence_timebase(clipitem)
            if clip_tb.fps_num * tb.fps_den != tb.fps_num * clip_tb.fps_den:
                raise XmlRecutRefusal(
                    f"clip {child_text(clipitem, 'name', '?')!r} has its own frame rate and no "
                    "tick positions, so its audio cannot be placed exactly")
    for path in files:
        if not path.is_file():
            raise XmlRecutRefusal(f"source media is missing or offline: {path}")
        if _has_audio_stream(path) is False:
            raise XmlRecutRefusal(f"source media has no audio stream: {path}")
    return {"xml_track": tracks.index(track), "track_name": child_text(track, "name"),
            "clip_count": len(clips), "files": [str(path) for path in files]}


def reference_media_path(source_xml: str, audio_track_index: int | None = None) -> Path:
    """The source media file backing the reference audio track's first real clip.

    Lets callers place outputs beside the footage the cuts were derived from.
    Track selection and the disabled-clip skip mirror ``extract_mixdown`` exactly,
    so "the footage" always names the media that was actually analyzed rather than
    whichever file the XML happens to list first.
    """
    sequence = ET.fromstring(source_xml).find("sequence")
    if sequence is None:
        raise XmlRecutRefusal("no <sequence> element found in source XML")
    track = select_audio_track(sequence, audio_track_index)
    for clipitem in enabled_clips(track):
        return resolve_file_path(sequence, clipitem.find("file").get("id"))
    raise XmlRecutRefusal("no enabled clip on the reference audio track names a source file")
