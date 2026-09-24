"""Rough Cut input as JSON (docs/arch-design-helper-v2.md move 6).

The panel reads the sequence's audio tracks natively (media path, start, source In/Out in
ticks, clip disabled, track muted) and sends them in `prepare`, instead of exporting the whole
sequence as FCP7 XML. This module validates that JSON and writes the small FCP7 subset that
`check_reference_audio`, `extract_mixdown` and `xml_recut` already read, so the analysis code
is unchanged:

- ``sequence/duration`` and ``rate`` (timebase + ntsc) from ``end_ticks`` / ``ticks_per_frame``;
- one ``media/audio/track`` per Premiere audio track (so Premiere's A1 is XML track 0; a real
  export splits a stereo track into two, which ``audio_track_groups`` then regroups);
- per clip: ``enabled``, ``start``/``end`` frames, ``pproTicksIn``/``pproTicksOut`` and a
  ``file`` with its ``pathurl``.

Channels don't matter: the extractor mixes every channel of each file to mono (``ffmpeg -ac 1``),
exactly as it did for an exported clipitem. A clip's start is rounded to the nearest frame, as
``<start>`` is in a real export.
"""
from __future__ import annotations

from pathlib import PureWindowsPath, PurePosixPath
from xml.etree import ElementTree as ET

from cutdeck.xml_export import _pathurl
from cutdeck.xml_sequence import PPRO_TICKS_PER_SECOND

MAX_TRACKS = 128
MAX_CLIPS = 20000


def _ticks(value, what: str) -> int:
    if not isinstance(value, str) or not value.isdigit() or len(value) > 24:
        raise ValueError(f"{what} must be a whole number of ticks as a string")
    return int(value)


def _is_absolute(path: str) -> bool:
    return PureWindowsPath(path).is_absolute() or PurePosixPath(path).is_absolute()


def timebase(ticks_per_frame: int) -> tuple[int, bool]:
    """(timebase, ntsc) of an FCP7 <rate> for Premiere's ticks per frame."""
    if ticks_per_frame <= 0:
        raise ValueError("ticks_per_frame must be positive")
    whole, rest = divmod(PPRO_TICKS_PER_SECOND, ticks_per_frame)
    if not rest:
        return whole, False
    ntsc, rest = divmod(PPRO_TICKS_PER_SECOND * 1001, ticks_per_frame * 1000)
    if not rest:
        return ntsc, True
    raise ValueError("Unsupported sequence frame rate")


def validate(sequence) -> dict:
    """The panel's sequence read, checked; refused whole before any job folder is made."""
    if not isinstance(sequence, dict):
        raise ValueError("sequence must be an object")
    tpf = _ticks(sequence.get("ticks_per_frame"), "ticks_per_frame")
    timebase(tpf)
    end = _ticks(sequence.get("end_ticks"), "end_ticks")
    tracks = sequence.get("audio_tracks")
    if not isinstance(tracks, list) or not 0 < len(tracks) <= MAX_TRACKS:
        raise ValueError("The sequence has no audio tracks to analyse")
    out, total = [], 0
    for index, track in enumerate(tracks, start=1):
        if not isinstance(track, dict) or type(track.get("enabled")) is not bool or not isinstance(track.get("clips"), list):
            raise ValueError(f"Audio track A{index} is malformed")
        clips = []
        for clip in track["clips"]:
            total += 1
            if total > MAX_CLIPS:
                raise ValueError(f"More than {MAX_CLIPS} audio clips; mark a shorter In/Out range")
            if not isinstance(clip, dict) or type(clip.get("enabled")) is not bool:
                raise ValueError(f"A clip on A{index} is malformed")
            path = clip.get("path")
            if not isinstance(path, str) or not _is_absolute(path):
                # The XML route refused nested sequences outright; a clip with no media file
                # would otherwise be silence in the analysis.
                raise ValueError(f"A clip on A{index} has no media file (a nested sequence?); "
                                 "CutDeck can't analyse it")
            start = _ticks(clip.get("start_ticks"), "start_ticks")
            media_in = _ticks(clip.get("in_ticks"), "in_ticks")
            media_out = _ticks(clip.get("out_ticks"), "out_ticks")
            if media_out <= media_in:
                raise ValueError(f"A clip on A{index} has its Out before its In")
            clips.append({"path": path, "enabled": clip["enabled"], "start_ticks": start,
                          "in_ticks": media_in, "out_ticks": media_out})
        out.append({"enabled": track["enabled"], "clips": clips})
    return {"ticks_per_frame": tpf, "end_ticks": end, "audio_tracks": out}


def to_fcp7_xml(sequence: dict, name: str = "CutDeck") -> str:
    """The FCP7 subset the analysis reads, from a `validate`d sequence."""
    tpf = sequence["ticks_per_frame"]
    base, ntsc = timebase(tpf)
    frames = lambda ticks: (ticks + tpf // 2) // tpf  # noqa: E731 — nearest frame, as <start> is

    root = ET.Element("xmeml", version="4")
    seq = ET.SubElement(root, "sequence", id="sequence-1")
    ET.SubElement(seq, "name").text = name
    ET.SubElement(seq, "duration").text = str(sequence["end_ticks"] // tpf)
    rate = ET.SubElement(seq, "rate")
    ET.SubElement(rate, "timebase").text = str(base)
    ET.SubElement(rate, "ntsc").text = "TRUE" if ntsc else "FALSE"
    audio = ET.SubElement(ET.SubElement(seq, "media"), "audio")
    file_ids: dict[str, str] = {}
    clip_number = 0
    for track in sequence["audio_tracks"]:
        track_el = ET.SubElement(audio, "track")
        for clip in track["clips"]:
            clip_number += 1
            start = frames(clip["start_ticks"])
            item = ET.SubElement(track_el, "clipitem", id=f"clipitem-{clip_number}")
            ET.SubElement(item, "name").text = PureWindowsPath(clip["path"]).name
            ET.SubElement(item, "enabled").text = "TRUE" if clip["enabled"] else "FALSE"
            ET.SubElement(item, "start").text = str(start)
            ET.SubElement(item, "end").text = str(frames(clip["start_ticks"] + clip["out_ticks"] - clip["in_ticks"]))
            ET.SubElement(item, "in").text = str(frames(clip["in_ticks"]))
            ET.SubElement(item, "out").text = str(frames(clip["out_ticks"]))
            ET.SubElement(item, "pproTicksIn").text = str(clip["in_ticks"])
            ET.SubElement(item, "pproTicksOut").text = str(clip["out_ticks"])
            file_id = file_ids.setdefault(clip["path"], f"file-{len(file_ids) + 1}")
            file_el = ET.SubElement(item, "file", id=file_id)
            ET.SubElement(file_el, "pathurl").text = _pathurl(clip["path"])
        ET.SubElement(track_el, "enabled").text = "TRUE" if track["enabled"] else "FALSE"
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")
