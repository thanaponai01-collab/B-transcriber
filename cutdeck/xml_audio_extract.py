"""xml_audio_extract.py — build a sequence-timeline mixdown WAV directly from
an exported FCP7 XML's own clipitems and source media, no Premiere render.

``sequence_mixdown.py``'s ingest path needs a waveform that represents what
the editor actually hears across the sequence's timeline, to run VAD/silence
detection against. Normally that means the editor exports one by hand
(``File > Export > Media``). This module builds the same kind of waveform
without that step: the XML already names every source file and its exact
in/out/start/end on the timeline, so each audio clip's segment can be pulled
straight from its original source file (via ffmpeg) and pasted into a silence
buffer at its timeline position — the same pattern ``cutdeck/live_clip.py``
uses for the mark-and-apply mode (reads original media directly rather than
waiting on a render).

**What this trades away, on purpose:** a real Premiere export bakes in
whatever the sequence's mix actually does — gain automation, EQ, panning,
crossfades. This module reads only what the XML states (``<in>``/``<out>``,
or ``<pproTicksIn>``/``<pproTicksOut>`` when present for sub-frame accuracy)
and does none of that. For a plain stacked-clip sequence with no effects
(this project's real sequences, per ``docs/HANDOFF_CUTDECK_XML_RECUT.md``'s
Phase 0 note) that gap is negligible; for a heavily mixed sequence it would
not be — pick the manual export path there instead.

**Track selection:** one audio track is picked as the "reference" dialogue
track for VAD (default: the first enabled track with any clips). A sequence
with several isolated mic tracks needs the editor to say which one carries
the dialogue that should drive silence detection — this module does not
guess by loudness or any other heuristic.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

from cutdeck.contracts import Timebase
from cutdeck.xml_recut import XmlRecutRefusal, _PPRO_TICKS_PER_SECOND, _sequence_timebase, _text

_WORKING_SAMPLE_RATE = 48000  # arbitrary but consistent; ingest() resamples to 16k anyway


def _pathurl_to_path(pathurl: str) -> Path:
    """Inverse of ``xml_export._pathurl`` — ``file://localhost/C%3A/...`` -> ``C:/...``."""
    parsed = urlparse(pathurl)
    raw = unquote(parsed.path)
    if len(raw) >= 3 and raw[0] == "/" and raw[2] == ":":
        raw = raw[1:]  # strip the leading '/' before a Windows drive letter
    return Path(raw)


def _resolve_file_path(sequence: ET.Element, file_id: str) -> Path:
    """The real source path for a file id — found on whichever <file> element
    carries the full listing (the one with a <pathurl> child)."""
    for file_el in sequence.iter("file"):
        if file_el.get("id") == file_id:
            pathurl_el = file_el.find("pathurl")
            if pathurl_el is not None and pathurl_el.text:
                return _pathurl_to_path(pathurl_el.text)
    raise XmlRecutRefusal(f"no <pathurl> found anywhere for file id {file_id!r} — "
                           f"source media path unknown")


def _clip_source_span_seconds(clipitem: ET.Element, tb: Timebase) -> tuple[float, float]:
    """(in_seconds, out_seconds) in the SOURCE file's own timeline. Prefers
    pproTicksIn/pproTicksOut (sub-frame precision) when present, falls back
    to the frame-based <in>/<out> otherwise."""
    ticks_in = clipitem.find("pproTicksIn")
    ticks_out = clipitem.find("pproTicksOut")
    if ticks_in is not None and ticks_in.text and ticks_out is not None and ticks_out.text:
        return (int(ticks_in.text) / _PPRO_TICKS_PER_SECOND,
                int(ticks_out.text) / _PPRO_TICKS_PER_SECOND)
    in_frame = int(_text(clipitem, "in", "0"))
    out_frame = int(_text(clipitem, "out", "0"))
    return (float(Fraction(in_frame * tb.fps_den, tb.fps_num)),
            float(Fraction(out_frame * tb.fps_den, tb.fps_num)))


def _select_audio_track(sequence: ET.Element, audio_track_index: int | None) -> ET.Element:
    audio = sequence.find("media/audio")
    tracks = audio.findall("track") if audio is not None else []
    if not tracks:
        raise XmlRecutRefusal("sequence has no audio tracks to extract from")
    if audio_track_index is not None:
        if audio_track_index >= len(tracks):
            raise XmlRecutRefusal(
                f"sequence has {len(tracks)} audio track(s), requested index "
                f"{audio_track_index} (0-based)"
            )
        return tracks[audio_track_index]
    for track in tracks:
        if track.findall("clipitem"):
            return track
    raise XmlRecutRefusal("no audio track has any clips")


def extract_mixdown(source_xml: str, out_wav: str, audio_track_index: int | None = None) -> str:
    """Build a sequence-timeline mono WAV from the XML's own clipitems +
    source media, writing it to ``out_wav``. Returns ``out_wav``.

    ``audio_track_index`` (0-based): which ``<track>`` under ``<media><audio>``
    to use as the reference dialogue track. Defaults to the first track that
    has any clips. Disabled clips (``<enabled>FALSE</enabled>``) are skipped
    — silence, same as they'd be muted in a real Premiere render.
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH — required to extract audio segments")

    root = ET.fromstring(source_xml)
    sequence = root.find("sequence")
    if sequence is None:
        raise XmlRecutRefusal("no <sequence> element found in source XML")

    tb = _sequence_timebase(sequence)
    seq_frames = int(_text(sequence, "duration", "0"))
    seq_seconds = float(Fraction(seq_frames * tb.fps_den, tb.fps_num))
    total_samples = int(round(seq_seconds * _WORKING_SAMPLE_RATE))

    track = _select_audio_track(sequence, audio_track_index)

    import numpy as np
    import soundfile as sf

    buffer = np.zeros(total_samples, dtype=np.float32)
    tmp_dir = Path(tempfile.mkdtemp(prefix="cutdeck_extract_"))
    try:
        for i, clipitem in enumerate(track.findall("clipitem")):
            if _text(clipitem, "enabled", "TRUE") != "TRUE":
                continue
            file_el = clipitem.find("file")
            if file_el is None or file_el.get("id") is None:
                continue
            src_path = _resolve_file_path(sequence, file_el.get("id"))

            in_s, out_s = _clip_source_span_seconds(clipitem, tb)
            if out_s <= in_s:
                continue

            seg_path = tmp_dir / f"seg{i}.wav"
            cmd = ["ffmpeg", "-y", "-i", str(src_path),
                   "-ss", f"{in_s:.9f}", "-to", f"{out_s:.9f}",
                   "-vn", "-ac", "1", "-ar", str(_WORKING_SAMPLE_RATE), str(seg_path)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg failed extracting {src_path} [{in_s:.3f}s-{out_s:.3f}s]: "
                    f"{result.stderr[-500:]}"
                )

            seg_audio, _sr = sf.read(str(seg_path), dtype="float32")
            start_frame = int(_text(clipitem, "start", "0"))
            start_s = float(Fraction(start_frame * tb.fps_den, tb.fps_num))
            offset = int(round(start_s * _WORKING_SAMPLE_RATE))
            end = min(offset + len(seg_audio), total_samples)
            if end > offset:
                buffer[offset:end] = seg_audio[: end - offset]
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    sf.write(out_wav, buffer, _WORKING_SAMPLE_RATE)
    return out_wav
