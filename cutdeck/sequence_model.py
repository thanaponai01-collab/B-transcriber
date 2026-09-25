"""sequence_model.py — the sequence's audio, as the analysis reads it (docs/arch-design-helper-v3.md move 3).

One typed model of what Rough Cut analyses: the audio tracks, and on each the clips' media file,
timeline position and source In/Out, all in Premiere ticks. Two doors build it:

- ``from_panel_json`` — the panel's native read (``prepare``'s ``sequence``), validated whole;
- ``from_fcp7_xml`` — an exported FCP7 XML (the MCP ``rough_cut`` tool, the ``xml_recut`` CLI, and
  jobs prepared by an earlier helper, which hold ``source.xml``). Premiere's exploded stereo
  channel tracks are regrouped here, so a track index is always a Premiere audio track.

``range_from_ticks``, ``reference_audio_track``, ``check_reference_audio``, ``extract_mixdown``
and ``xml_recut.main`` read a ``Sequence``; none of them parses XML for the timeline. Rewriting
an XML export (``xml_recut.recut``) still works on the XML itself.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path, PurePosixPath, PureWindowsPath
from xml.etree import ElementTree as ET

from cutdeck.contracts import Timebase
from cutdeck.xml_sequence import (PPRO_TICKS_PER_SECOND, XmlRecutRefusal, audio_track_groups, child_text,
                                  frame_to_ticks, resolve_file_path, sequence_timebase)

MAX_TRACKS = 128
MAX_CLIPS = 20000


@dataclass(frozen=True)
class Clip:
    path: str | None  # None: an XML export that names the file but never gives its pathurl
    start_ticks: int  # where it sits on the sequence
    in_ticks: int     # source In / Out
    out_ticks: int
    enabled: bool

    @property
    def end_ticks(self) -> int:
        return self.start_ticks + self.out_ticks - self.in_ticks

    @property
    def media_path(self) -> str:
        """The source file, for an analysis that reads this clip's audio."""
        if self.path is None:
            raise XmlRecutRefusal("a clip has no <pathurl> anywhere in the export — source media path unknown")
        return self.path


@dataclass(frozen=True)
class Track:
    index: int  # 0-based Premiere audio track (A1 is 0)
    muted: bool
    clips: tuple[Clip, ...]


@dataclass(frozen=True)
class Sequence:
    ticks_per_frame: int
    end_ticks: int
    tracks: tuple[Track, ...]

    @property
    def timebase(self) -> Timebase:
        base, ntsc = timebase(self.ticks_per_frame)
        return Timebase(fps_num=base * 1000, fps_den=1001) if ntsc else Timebase(fps_num=base, fps_den=1)

    @property
    def duration_frames(self) -> int:
        return self.end_ticks // self.ticks_per_frame

    def reference_track(self, index: int | None) -> Track:
        """The dialogue track VAD reads: ``index``, or the first switched-on track with clips.

        An explicit index is honored even when that track is switched off: the editor chose it,
        and a lav track muted in the mix is still the best thing to analyze. Nothing here guesses
        by loudness."""
        if not self.tracks:
            raise XmlRecutRefusal("sequence has no audio tracks to extract from")
        if index is not None:
            if not 0 <= index < len(self.tracks):
                raise XmlRecutRefusal(f"sequence has {len(self.tracks)} audio track(s), requested index "
                                      f"{index} (0-based)")
            return self.tracks[index]
        with_clips = [track for track in self.tracks if track.clips]
        if not with_clips:
            raise XmlRecutRefusal("no audio track has any clips")
        for track in with_clips:
            if not track.muted:
                return track
        raise XmlRecutRefusal("every audio track with clips is switched off; choose a Reference Audio track")


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


def from_panel_json(sequence) -> Sequence:
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
            clips.append(Clip(path, start, media_in, media_out, clip["enabled"]))
        out.append(Track(index - 1, not track["enabled"], tuple(clips)))
    return Sequence(tpf, end, tuple(out))


def _source_span_ticks(clipitem: ET.Element, tb: Timebase) -> tuple[int, int]:
    """The clip's source In/Out in ticks: Premiere's own ``pproTicks`` (sub-frame) when the export
    has them, else the frame-based ``<in>``/``<out>``."""
    ticks_in, ticks_out = clipitem.find("pproTicksIn"), clipitem.find("pproTicksOut")
    if ticks_in is not None and ticks_in.text and ticks_out is not None and ticks_out.text:
        return int(ticks_in.text), int(ticks_out.text)
    return (frame_to_ticks(int(child_text(clipitem, "in", "0")), tb),
            frame_to_ticks(int(child_text(clipitem, "out", "0")), tb))


def _xml_clip(sequence: ET.Element, clipitem: ET.Element, tb: Timebase) -> Clip | None:
    """One ``<clipitem>`` as a Clip; None when it contributes nothing (no source file, or an empty span)."""
    file_el = clipitem.find("file")
    if file_el is None or file_el.get("id") is None:
        return None
    enabled = child_text(clipitem, "enabled", "TRUE") == "TRUE"
    try:
        path = str(resolve_file_path(sequence, file_el.get("id")))
    except XmlRecutRefusal:
        path = None  # only an analysis that reads this clip's audio needs it (`media_path`)
    if enabled and clipitem.find("pproTicksIn") is None and clipitem.find("rate") is not None:
        clip_tb = sequence_timebase(clipitem)
        if clip_tb.fps_num * tb.fps_den != tb.fps_num * clip_tb.fps_den:
            raise XmlRecutRefusal(
                f"clip {child_text(clipitem, 'name', '?')!r} has its own frame rate and no "
                "tick positions, so its audio cannot be placed exactly")
    media_in, media_out = _source_span_ticks(clipitem, tb)
    if media_out <= media_in:
        return None
    return Clip(path, frame_to_ticks(int(child_text(clipitem, "start", "0")), tb),
                media_in, media_out, enabled)


def from_fcp7_xml(source_xml: str) -> Sequence:
    """An exported FCP7 sequence's audio. Each Premiere track is the first of its exploded
    channel tracks (the channels of one stereo track carry the same clips)."""
    sequence = ET.fromstring(source_xml).find("sequence")
    if sequence is None:
        raise XmlRecutRefusal("no <sequence> element found in source XML")
    tb = sequence_timebase(sequence)
    ticks_per_frame = Fraction(PPRO_TICKS_PER_SECOND * tb.fps_den, tb.fps_num)
    if ticks_per_frame.denominator != 1:
        raise XmlRecutRefusal("Unsupported sequence frame rate")
    tpf = int(ticks_per_frame)
    xml_tracks = sequence.findall("media/audio/track")
    tracks = tuple(
        Track(number, child_text(xml_tracks[first], "enabled", "TRUE") != "TRUE",
              tuple(clip for clip in (_xml_clip(sequence, item, tb)
                                      for item in xml_tracks[first].findall("clipitem")) if clip))
        for number, first in enumerate(audio_track_groups(xml_tracks)))
    return Sequence(tpf, int(child_text(sequence, "duration", "0")) * tpf, tracks)


def load(path: str | Path) -> Sequence:
    """A job's sequence file: the panel's JSON read, or an FCP7 XML (MCP jobs, older prepared jobs)."""
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    return from_panel_json(json.loads(text)) if path.suffix.lower() == ".json" else from_fcp7_xml(text)


def _has_audio_stream(path: Path) -> bool | None:
    """True/False from ffprobe, or None when ffprobe cannot answer (missing, unreadable)."""
    if shutil.which("ffprobe") is None:
        return None
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-of", "json", "-show_entries", "stream=codec_type", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        return None
    try:
        streams = json.loads(result.stdout).get("streams", [])
    except ValueError:
        return None
    return any(stream.get("codec_type") == "audio" for stream in streams)


def check_reference_audio(sequence: Sequence, audio_track_index: int | None = None) -> dict:
    """Refuse, before any audio is extracted or transcribed, what ``extract_mixdown`` would fail
    on or silently get wrong. Returns what will be analyzed.

    Checks: the reference track selection itself; every enabled clip's source file exists and has
    an audio stream. A source frame rate that differs from the sequence is fine: extraction works
    in seconds."""
    track = sequence.reference_track(audio_track_index)
    clips = [clip for clip in track.clips if clip.enabled]
    if not clips:
        raise XmlRecutRefusal("the reference audio track has no enabled clips")
    files: list[Path] = []
    for clip in clips:
        if Path(clip.media_path) not in files:
            files.append(Path(clip.media_path))
    for path in files:
        if not path.is_file():
            raise XmlRecutRefusal(f"source media is missing or offline: {path}")
        if _has_audio_stream(path) is False:
            raise XmlRecutRefusal(f"source media has no audio stream: {path}")
    return {"track": track.index, "clip_count": len(clips), "files": [str(path) for path in files]}
