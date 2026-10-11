"""Read historical XML fixtures for tests; never imported by the product."""
from fractions import Fraction
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET
from cutdeck.contracts import Timebase
from cutdeck.sequence_timing import PPRO_TICKS_PER_SECOND, SequenceRefusal, frame_to_ticks
from cutdeck.sequence_model import Clip, Track, Sequence

def child_text(el, tag, default=None):
    child = el.find(tag)
    return child.text if child is not None and child.text is not None else default


def sequence_timebase(sequence: ET.Element) -> Timebase:
    rate = sequence.find("rate")
    if rate is None:
        raise SequenceRefusal("sequence has no <rate> — cannot recut without a frame grid")
    timebase_el = rate.find("timebase")
    ntsc_el = rate.find("ntsc")
    if timebase_el is None or timebase_el.text is None:
        raise SequenceRefusal("sequence <rate> has no <timebase>")
    timebase_int = int(timebase_el.text)
    is_ntsc = (ntsc_el is not None and (ntsc_el.text or "").strip().upper() == "TRUE")
    fps_num, fps_den = (timebase_int * 1000, 1001) if is_ntsc else (timebase_int, 1)
    return Timebase(fps_num=fps_num, fps_den=fps_den)


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
    """Premiere's ``file://localhost/C%3A/...`` URL -> ``C:/...``."""
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
    raise SequenceRefusal(f"no <pathurl> found anywhere for file id {file_id!r} — "
                           f"source media path unknown")


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
    except SequenceRefusal:
        path = None  # only an analysis that reads this clip's audio needs it (`media_path`)
    if enabled and clipitem.find("pproTicksIn") is None and clipitem.find("rate") is not None:
        clip_tb = sequence_timebase(clipitem)
        if clip_tb.fps_num * tb.fps_den != tb.fps_num * clip_tb.fps_den:
            raise SequenceRefusal(
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
        raise SequenceRefusal("no <sequence> element found in source XML")
    tb = sequence_timebase(sequence)
    ticks_per_frame = Fraction(PPRO_TICKS_PER_SECOND * tb.fps_den, tb.fps_num)
    if ticks_per_frame.denominator != 1:
        raise SequenceRefusal("Unsupported sequence frame rate")
    tpf = int(ticks_per_frame)
    xml_tracks = sequence.findall("media/audio/track")
    tracks = tuple(
        Track(number, child_text(xml_tracks[first], "enabled", "TRUE") != "TRUE",
              tuple(clip for clip in (_xml_clip(sequence, item, tb)
                                      for item in xml_tracks[first].findall("clipitem")) if clip))
        for number, first in enumerate(audio_track_groups(xml_tracks)))
    return Sequence(tpf, int(child_text(sequence, "duration", "0")) * tpf, tracks)


def panel_json_from_xml(xml):
    seq = from_fcp7_xml(xml)
    return {"ticks_per_frame": str(seq.ticks_per_frame), "end_ticks": str(seq.end_ticks),
            "audio_tracks": [{"enabled": not track.muted, "clips": [
                {"path": clip.path or "C:/media/fixture.wav", "enabled": clip.enabled,
                 "start_ticks": str(clip.start_ticks), "in_ticks": str(clip.in_ticks),
                 "out_ticks": str(clip.out_ticks)} for clip in track.clips]} for track in seq.tracks]}
