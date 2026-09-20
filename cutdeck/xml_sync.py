"""xml_sync.py — Multi-camera XML alignment and vertical track stacking for CutDeck.

Parses an exported FCP7 XML sequence containing camera angles (either stacked or
placed sequentially on the timeline), computes frame-exact offsets using audio
cross-correlation against a single reference clip, and rebuilds the sequence as a
true synchronized vertical track stack:
  - Each camera angle gets its own Video Track (V1, V2, V3, ...).
  - Every original audio channel is 100% preserved on its own Audio Track (A1, A2, ...),
    supporting 1, 2, 4, or 8+ audio channels per angle without dropping any track.
  - Negative start frames are shifted so all angles start at >= 0.
  - Unsynced / silent clips are placed after the synced content with a buffer gap.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from fractions import Fraction
import logging
from pathlib import Path
from typing import Callable, Optional
import uuid
from xml.etree import ElementTree as ET

from cutdeck.contracts import Timebase
from cutdeck.sync import (
    DEFAULT_MIN_PSR,
    DEFAULT_SAMPLE_RATE,
    SyncResult,
    extract_mono_audio,
    sync_clip_to_reference,
)
from cutdeck.xml_audio_extract import (
    _clip_source_span_seconds,
    _resolve_file_path,
    _select_audio_track,
)
from cutdeck.xml_recut import (
    XmlRecutRefusal,
    _PPRO_TICKS_PER_SECOND,
    _frame_to_ticks,
    _sequence_timebase,
    _text,
)

logger = logging.getLogger(__name__)


@dataclass
class ClipItemRef:
    """Reference to a clipitem in the XML tree."""
    element: ET.Element
    track_type: str  # 'video' | 'audio'
    track_index: int
    clip_id: str
    file_id: str
    file_path: Path
    in_frame: int
    out_frame: int
    start_frame: int
    end_frame: int
    in_s: float
    out_s: float


@dataclass
class AngleGroup:
    """A camera angle grouping linked video and audio clipitems."""
    group_id: str
    file_id: str
    file_path: Path
    in_frame: int
    video_clips: list[ClipItemRef] = field(default_factory=list)
    audio_clips: list[ClipItemRef] = field(default_factory=list)
    is_reference: bool = False
    is_synced: bool = False
    offset_frames: int = 0
    confidence: float = 0.0
    sync_reason: str = "pending"
    new_start_frame: int = 0
    new_end_frame: int = 0

    @property
    def duration_frames(self) -> int:
        if self.video_clips:
            return self.video_clips[0].out_frame - self.video_clips[0].in_frame
        if self.audio_clips:
            return self.audio_clips[0].out_frame - self.audio_clips[0].in_frame
        return 0


@dataclass
class SyncSequenceReport:
    """Summary of multi-camera synchronization."""
    sequence_name: str
    total_groups: int
    synced_groups: int
    unsynced_groups: int
    min_start_frame: int
    max_end_frame: int
    unsynced_reasons: dict[str, str] = field(default_factory=dict)


def _build_reference_audio(
    sequence: ET.Element,
    tb: Timebase,
    ref_track_idx: int,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    audio_extractor: Callable[..., any] = extract_mono_audio,
) -> tuple[any, tuple[str, int]]:
    """Construct sequence-timeline reference audio array from the selected track.

    Returns:
        (ref_audio_array, (ref_file_id, ref_in_frame))
    """
    import numpy as np

    track = _select_audio_track(sequence, ref_track_idx)
    clipitems = [c for c in track.findall("clipitem") if _text(c, "enabled", "TRUE") == "TRUE"]
    if not clipitems:
        raise XmlRecutRefusal(f"Reference audio track (index {ref_track_idx}) has no enabled clips.")

    # The first enabled clip on the chosen reference track defines the reference angle
    ref_first = clipitems[0]
    ref_file_el = ref_first.find("file")
    if ref_file_el is None or ref_file_el.get("id") is None:
        raise XmlRecutRefusal("First clip on reference audio track has no file element.")
    ref_file_id = ref_file_el.get("id")
    ref_in_frame = int(_text(ref_first, "in", "0"))
    ref_group_key = (ref_file_id, ref_in_frame)

    # Reference audio is extracted from the primary reference clip's media file
    ref_file_path = _resolve_file_path(sequence, ref_file_id)
    in_s, out_s = _clip_source_span_seconds(ref_first, tb)
    dur_s = max(0.0, out_s - in_s)

    # Extract reference audio
    ref_clip_audio = audio_extractor(ref_file_path, start_s=in_s, duration_s=dur_s, sample_rate=sample_rate)

    # Place in a sequence-timeline buffer starting at this clip's timeline start
    start_frame = int(_text(ref_first, "start", "0"))
    start_s = float(Fraction(start_frame * tb.fps_den, tb.fps_num))
    offset_samples = int(round(start_s * sample_rate))
    total_samples = offset_samples + len(ref_clip_audio) + sample_rate

    ref_audio = np.zeros(total_samples, dtype=np.float32)
    ref_audio[offset_samples : offset_samples + len(ref_clip_audio)] = ref_clip_audio

    return ref_audio, ref_group_key


def sync_sequence_xml(
    source_xml: str,
    *,
    ref_track_idx: int = 0,
    min_psr: float = DEFAULT_MIN_PSR,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    gap_frames_between_unsynced: int = 60,
    audio_extractor: Callable[..., any] = extract_mono_audio,
) -> tuple[str, SyncSequenceReport]:
    """Align all camera angles in an FCP7 XML sequence into a clean vertical stack.

    Every camera angle gets its own video track (V1, V2, V3...) and all of its
    original audio channels are preserved across dedicated audio tracks.
    """
    root = ET.fromstring(source_xml)
    seq = root.find("sequence")
    if seq is None:
        raise XmlRecutRefusal("No <sequence> element found in source XML.")

    tb = _sequence_timebase(seq)
    orig_name = _text(seq, "name", "Sequence")

    # 1. Build reference audio timeline and identify the reference group
    ref_audio, ref_group_key = _build_reference_audio(
        seq, tb, ref_track_idx, sample_rate=sample_rate, audio_extractor=audio_extractor
    )

    # 2. Gather clipitems from video and audio tracks
    video_tracks = seq.findall("media/video/track")
    audio_tracks = seq.findall("media/audio/track")

    clips_by_file: dict[str, list[ClipItemRef]] = {}

    for t_idx, track in enumerate(video_tracks):
        for clip in track.findall("clipitem"):
            file_el = clip.find("file")
            if file_el is None or file_el.get("id") is None:
                continue
            f_id = file_el.get("id")
            f_path = _resolve_file_path(seq, f_id)
            in_s, out_s = _clip_source_span_seconds(clip, tb)
            ref = ClipItemRef(
                element=clip,
                track_type="video",
                track_index=t_idx,
                clip_id=clip.get("id", ""),
                file_id=f_id,
                file_path=f_path,
                in_frame=int(_text(clip, "in", "0")),
                out_frame=int(_text(clip, "out", "0")),
                start_frame=int(_text(clip, "start", "0")),
                end_frame=int(_text(clip, "end", "0")),
                in_s=in_s,
                out_s=out_s,
            )
            clips_by_file.setdefault(f_id, []).append(ref)

    for t_idx, track in enumerate(audio_tracks):
        for clip in track.findall("clipitem"):
            file_el = clip.find("file")
            if file_el is None or file_el.get("id") is None:
                continue
            f_id = file_el.get("id")
            f_path = _resolve_file_path(seq, f_id)
            in_s, out_s = _clip_source_span_seconds(clip, tb)
            ref = ClipItemRef(
                element=clip,
                track_type="audio",
                track_index=t_idx,
                clip_id=clip.get("id", ""),
                file_id=f_id,
                file_path=f_path,
                in_frame=int(_text(clip, "in", "0")),
                out_frame=int(_text(clip, "out", "0")),
                start_frame=int(_text(clip, "start", "0")),
                end_frame=int(_text(clip, "end", "0")),
                in_s=in_s,
                out_s=out_s,
            )
            clips_by_file.setdefault(f_id, []).append(ref)

    # 3. Create AngleGroups
    groups_dict: dict[tuple[str, int], AngleGroup] = {}
    for f_id, clip_list in clips_by_file.items():
        for clip in clip_list:
            key = (f_id, clip.in_frame)
            if key not in groups_dict:
                groups_dict[key] = AngleGroup(
                    group_id=f"{f_id}_{clip.in_frame}",
                    file_id=f_id,
                    file_path=clip.file_path,
                    in_frame=clip.in_frame,
                )
            if clip.track_type == "video":
                groups_dict[key].video_clips.append(clip)
            else:
                groups_dict[key].audio_clips.append(clip)

    groups = list(groups_dict.values())

    # 4. Align each AngleGroup against the reference track
    synced_groups: list[AngleGroup] = []
    unsynced_groups: list[AngleGroup] = []

    for key, g in groups_dict.items():
        # Only the designated reference clip is the reference
        if key == ref_group_key:
            g.is_reference = True
            g.is_synced = True
            first_clip = (g.video_clips or g.audio_clips)[0]
            g.offset_frames = first_clip.start_frame
            g.new_start_frame = first_clip.start_frame
            g.new_end_frame = first_clip.end_frame
            g.confidence = 999.0
            g.sync_reason = "reference"
            synced_groups.append(g)
            continue

        # Extract audio for this clip
        in_s = g.video_clips[0].in_s if g.video_clips else g.audio_clips[0].in_s
        out_s = g.video_clips[0].out_s if g.video_clips else g.audio_clips[0].out_s
        dur_s = out_s - in_s

        if dur_s <= 0:
            g.is_synced = False
            g.sync_reason = "too_short"
            unsynced_groups.append(g)
            continue

        try:
            clip_audio = audio_extractor(
                g.file_path, start_s=in_s, duration_s=dur_s, sample_rate=sample_rate
            )
            res: SyncResult = sync_clip_to_reference(
                ref_audio, clip_audio, tb, sample_rate=sample_rate, min_psr=min_psr
            )
            g.is_synced = res.is_synced
            g.offset_frames = res.offset_frames
            g.confidence = res.confidence
            g.sync_reason = res.reason

            if res.is_synced:
                g.new_start_frame = res.offset_frames
                g.new_end_frame = g.new_start_frame + g.duration_frames
                synced_groups.append(g)
            else:
                unsynced_groups.append(g)
        except Exception as exc:
            logger.warning(f"Failed to sync {g.file_path.name}: {exc}")
            g.is_synced = False
            g.sync_reason = f"error: {exc}"
            unsynced_groups.append(g)

    # 5. Handle negative start frames (clip starts before reference)
    if synced_groups:
        min_start = min(g.new_start_frame for g in synced_groups)
        if min_start < 0:
            shift = -min_start
            for g in synced_groups:
                g.new_start_frame += shift
                g.new_end_frame += shift
                g.offset_frames += shift

    # 6. Place unsynced clips at the end of the timeline
    max_synced_end = max((g.new_end_frame for g in synced_groups), default=0)
    cursor = max_synced_end + gap_frames_between_unsynced

    for g in unsynced_groups:
        g.new_start_frame = cursor
        g.new_end_frame = cursor + g.duration_frames
        cursor = g.new_end_frame + gap_frames_between_unsynced

    # 7. Update start/end frames on all clipitem elements
    for g in groups:
        for clip in g.video_clips + g.audio_clips:
            el = clip.element
            start_el = el.find("start")
            if start_el is not None:
                start_el.text = str(g.new_start_frame)
            end_el = el.find("end")
            if end_el is not None:
                end_el.text = str(g.new_end_frame)

            ticks_in = el.find("pproTicksIn")
            if ticks_in is not None:
                ticks_in.text = str(_frame_to_ticks(clip.in_frame, tb))
            ticks_out = el.find("pproTicksOut")
            if ticks_out is not None:
                ticks_out.text = str(_frame_to_ticks(clip.out_frame, tb))

    # 8. Rebuild Tracks: Vertical Stacking for Video & Complete Preservation of Audio
    # Video: Each angle group gets its own Video Track (V1, V2, V3...)
    video_parent = seq.find("media/video")
    if video_parent is not None:
        # Save sample track template for creating new tracks
        v_templates = video_parent.findall("track")
        v_template = v_templates[0] if v_templates else ET.Element("track")
        # Remove existing video tracks
        for t in list(video_parent.findall("track")):
            video_parent.remove(t)

        for v_idx, g in enumerate(groups):
            if not g.video_clips:
                continue
            new_v_track = copy.deepcopy(v_template)
            # Remove any existing clipitems in template
            for ci in list(new_v_track.findall("clipitem")):
                new_v_track.remove(ci)
            for clip in g.video_clips:
                new_v_track.append(clip.element)
            video_parent.append(new_v_track)

    # Audio: Preserve ALL original audio channels per angle!
    # For stereo tracks, maintain proper exploded track pairs (currentExplodedTrackIndex 0 & 1,
    # outputchannelindex 1 & 2) so Premiere Pro collapses them back into single stereo timeline tracks
    # instead of exploding each channel into a separate mono timeline track.
    audio_parent = seq.find("media/audio")
    if audio_parent is not None:
        a_templates = audio_parent.findall("track")
        tpl_exp0 = next(
            (t for t in a_templates if t.attrib.get("currentExplodedTrackIndex") == "0"),
            copy.deepcopy(a_templates[0]) if a_templates else ET.Element("track"),
        )
        tpl_exp1 = next(
            (t for t in a_templates if t.attrib.get("currentExplodedTrackIndex") == "1"),
            None,
        )
        if tpl_exp1 is None:
            tpl_exp1 = copy.deepcopy(tpl_exp0)
            tpl_exp1.attrib["currentExplodedTrackIndex"] = "1"
            tpl_exp1.attrib["totalExplodedTrackCount"] = "2"
            tpl_exp1.attrib["premiereTrackType"] = "Stereo"
            out_el = tpl_exp1.find("outputchannelindex")
            if out_el is not None:
                out_el.text = "2"
            else:
                ET.SubElement(tpl_exp1, "outputchannelindex").text = "2"

        # The reference angle's audio keeps its original tracks, and tracks that were empty
        # in the source stay empty in place. Tracks held only by other angles are dropped;
        # those angles' audio goes on new tracks after them.
        reference = next((g for g in groups if g.is_reference and g.audio_clips), None)
        original = list(audio_parent.findall("track"))
        for t in original:
            audio_parent.remove(t)
        if reference is not None:
            reference_tracks = {clip.track_index for clip in reference.audio_clips}
            for idx, t in enumerate(original):
                if idx not in reference_tracks and t.findall("clipitem"):
                    continue
                slot = copy.deepcopy(t)
                for ci in list(slot.findall("clipitem")):
                    slot.remove(ci)
                for clip in reference.audio_clips:
                    if clip.track_index == idx:
                        slot.append(clip.element)
                audio_parent.append(slot)

        for g in groups:
            if not g.audio_clips or g is reference:
                continue
            # Group audio clips by their original track_index so each channel/track of this angle
            # gets its own dedicated audio track in the final sequence.
            channels: dict[int, list[ClipItemRef]] = {}
            for clip in g.audio_clips:
                channels.setdefault(clip.track_index, []).append(clip)

            sorted_orig_tracks = sorted(channels.keys())
            num_ch = len(sorted_orig_tracks)

            # Determine if this angle's audio is stereo or mono
            is_stereo = False
            for clip in g.audio_clips:
                if clip.element.get("premiereChannelType") == "stereo":
                    is_stereo = True
                    break
                orig_t = a_templates[clip.track_index] if clip.track_index < len(a_templates) else None
                if orig_t is not None and (
                    orig_t.attrib.get("premiereTrackType") == "Stereo"
                    or orig_t.attrib.get("totalExplodedTrackCount") == "2"
                ):
                    is_stereo = True
                    break

            if is_stereo and num_ch >= 2 and num_ch % 2 == 0:
                for ch_idx, orig_t_idx in enumerate(sorted_orig_tracks):
                    pair_sub_idx = ch_idx % 2  # 0 for Left, 1 for Right
                    if pair_sub_idx == 0:
                        new_a_track = copy.deepcopy(tpl_exp0)
                        new_a_track.attrib["currentExplodedTrackIndex"] = "0"
                        new_a_track.attrib["totalExplodedTrackCount"] = "2"
                        new_a_track.attrib["premiereTrackType"] = "Stereo"
                        out_el = new_a_track.find("outputchannelindex")
                        if out_el is not None:
                            out_el.text = "1"
                        else:
                            ET.SubElement(new_a_track, "outputchannelindex").text = "1"
                    else:
                        new_a_track = copy.deepcopy(tpl_exp1)
                        new_a_track.attrib["currentExplodedTrackIndex"] = "1"
                        new_a_track.attrib["totalExplodedTrackCount"] = "2"
                        new_a_track.attrib["premiereTrackType"] = "Stereo"
                        out_el = new_a_track.find("outputchannelindex")
                        if out_el is not None:
                            out_el.text = "2"
                        else:
                            ET.SubElement(new_a_track, "outputchannelindex").text = "2"

                    for ci in list(new_a_track.findall("clipitem")):
                        new_a_track.remove(ci)
                    for clip in channels[orig_t_idx]:
                        new_a_track.append(clip.element)
                    audio_parent.append(new_a_track)
            else:
                for orig_t_idx in sorted_orig_tracks:
                    new_a_track = copy.deepcopy(tpl_exp0)
                    new_a_track.attrib["premiereTrackType"] = "Mono"
                    new_a_track.attrib["totalExplodedTrackCount"] = "1"
                    new_a_track.attrib["currentExplodedTrackIndex"] = "0"
                    out_el = new_a_track.find("outputchannelindex")
                    if out_el is not None:
                        out_el.text = "1"
                    for ci in list(new_a_track.findall("clipitem")):
                        new_a_track.remove(ci)
                    for clip in channels[orig_t_idx]:
                        new_a_track.append(clip.element)
                    audio_parent.append(new_a_track)

    # 9. Update <link> references to point to new track and clip positions
    clip_new_location: dict[str, tuple[str, int, int]] = {}
    if video_parent is not None:
        for v_idx, t in enumerate(video_parent.findall("track"), start=1):
            for c_idx, c in enumerate(t.findall("clipitem"), start=1):
                cid = c.get("id")
                if cid:
                    clip_new_location[cid] = ("video", v_idx, c_idx)
    if audio_parent is not None:
        for a_idx, t in enumerate(audio_parent.findall("track"), start=1):
            for c_idx, c in enumerate(t.findall("clipitem"), start=1):
                cid = c.get("id")
                if cid:
                    clip_new_location[cid] = ("audio", a_idx, c_idx)

    all_clipitems = []
    if video_parent is not None:
        all_clipitems.extend(video_parent.findall("track/clipitem"))
    if audio_parent is not None:
        all_clipitems.extend(audio_parent.findall("track/clipitem"))

    for c in all_clipitems:
        for link in c.findall("link"):
            ref_id = link.findtext("linkclipref")
            if ref_id in clip_new_location:
                new_type, new_t_idx, new_c_idx = clip_new_location[ref_id]
                m_el = link.find("mediatype")
                if m_el is not None:
                    m_el.text = new_type
                t_el = link.find("trackindex")
                if t_el is not None:
                    t_el.text = str(new_t_idx)
                c_el = link.find("clipindex")
                if c_el is not None:
                    c_el.text = str(new_c_idx)

    # 10. Update sequence metadata
    total_seq_duration = max((g.new_end_frame for g in groups), default=0)
    dur_el = seq.find("duration")
    if dur_el is not None:
        dur_el.text = str(total_seq_duration)

    synced_name = f"{orig_name}_Synced"
    name_el = seq.find("name")
    if name_el is not None:
        name_el.text = synced_name

    uuid_el = seq.find("uuid")
    if uuid_el is not None:
        uuid_el.text = str(uuid.uuid4())

    report = SyncSequenceReport(
        sequence_name=synced_name,
        total_groups=len(groups),
        synced_groups=len(synced_groups),
        unsynced_groups=len(unsynced_groups),
        min_start_frame=min((g.new_start_frame for g in groups), default=0),
        max_end_frame=total_seq_duration,
        unsynced_reasons={g.file_path.name: g.sync_reason for g in unsynced_groups},
    )

    return ET.tostring(root, encoding="utf-8").decode("utf-8"), report
