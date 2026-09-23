"""Issue #28 — extraction through recut on a representative stacked-track export.

The fixture is shaped like a real Premiere FCP7 export: one video track and two
stereo audio tracks, each exploded into two XML channel tracks
(``totalExplodedTrackCount``/``currentExplodedTrackIndex``), ``pproTicksIn``/``Out`` on
every clip, the full ``<file>`` listing only on a file's first use, and XML the
transform has no model for. A1 is switched-off music that never goes quiet; A2 is
dialogue with one long pause. The VAD reads the real extracted audio, so *which*
track was analyzed decides whether anything is cut.

Real ffmpeg, real extraction, real ``xml_recut.main``; only Silero is replaced by an
energy detector so no model download or GPU is needed.
"""
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET

import numpy as np
import pytest

from cutdeck import xml_recut
from cutdeck.xml_bridge import reference_audio_track
from cutdeck.xml_sequence import check_reference_audio, frame_to_ticks
from cutdeck.contracts import Timebase
from transcribe.pipeline import ingest as ingest_mod

FPS = 30
TB = Timebase(FPS, 1)
FRAMES = 600                    # 20 s sequence
PAUSE_S = (5.0, 11.0)           # dialogue silence, frames 150-330
RANGE = (120, 480)              # In/Out marks around the pause
SR = 48000


def _pathurl(path: Path) -> str:
    return "file://localhost/" + quote(str(path.resolve()).replace("\\", "/"), safe="/:")


def _wav(path: Path, silent: tuple[float, float] | None) -> Path:
    import soundfile as sf
    t = np.arange(int(FRAMES / FPS * SR)) / SR
    audio = (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    if silent:
        audio[int(silent[0] * SR):int(silent[1] * SR)] = 0.0
    sf.write(str(path), audio, SR)
    return path


def _clip(cid, fid, path, start, end, first_use, extra=""):
    """One clipitem; like Premiere, only a file's first use carries its full listing."""
    listing = (f'<file id="{fid}"><name>{path.name}</name><pathurl>{_pathurl(path)}</pathurl>'
               f'<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>'
               '<media><audio><channelcount>1</channelcount></audio></media></file>'
               if first_use else f'<file id="{fid}"/>')
    return (f'<clipitem id="{cid}"><name>{path.stem}</name><enabled>TRUE</enabled>'
            f'<start>{start}</start><end>{end}</end><in>{start}</in><out>{end}</out>'
            f'<pproTicksIn>{frame_to_ticks(start, TB)}</pproTicksIn>'
            f'<pproTicksOut>{frame_to_ticks(end, TB)}</pproTicksOut>'
            f'{extra}{listing}</clipitem>')


def _stereo_track(channel, clips, enabled):
    return (f'<track TL.SQTrackShy="0" totalExplodedTrackCount="2" '
            f'currentExplodedTrackIndex="{channel}">{clips}'
            f'<enabled>{"TRUE" if enabled else "FALSE"}</enabled><locked>FALSE</locked></track>')


def _sequence(video: Path, music: Path, dialogue: Path) -> str:
    unknown = '<logginginfo><description>take 3</description></logginginfo><labels><label2>Iris</label2></labels>'
    v1 = f'<track>{_clip("v1", "fv", video, 0, FRAMES, True, unknown)}<enabled>TRUE</enabled></track>'
    a1 = [_stereo_track(ch, _clip(f"a1c{ch}", "fm", music, 0, FRAMES, ch == 0), enabled=False)
          for ch in (0, 1)]
    a2 = [_stereo_track(ch, _clip(f"a2c{ch}a", "fd", dialogue, 0, 300, ch == 0)
                        + _clip(f"a2c{ch}b", "fd", dialogue, 300, FRAMES, False), enabled=True)
          for ch in (0, 1)]
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">'
            f'<sequence id="sequence-1"><uuid>abc</uuid><duration>{FRAMES}</duration>'
            f'<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate><name>Stacked</name>'
            f'<media><video>{v1}<format><samplecharacteristics><width>1920</width>'
            '</samplecharacteristics></format></video>'
            f'<audio><numOutputChannels>2</numOutputChannels>{"".join(a1 + a2)}</audio></media>'
            '<timecode><string>00:00:00:00</string></timecode></sequence></xmeml>')


@pytest.fixture
def export(tmp_path, monkeypatch):
    def energy_vad(tensor, model, **kw):
        loud = (np.abs(np.asarray(tensor)) > 0.1).astype(np.int8)
        edges = np.flatnonzero(np.diff(np.concatenate([[0], loud, [0]])))
        return [{"start": int(a), "end": int(b)} for a, b in zip(edges[::2], edges[1::2])]
    monkeypatch.setattr(ingest_mod, "_load_silero", lambda: (object(), energy_vad))

    media = tmp_path / "media"
    media.mkdir()
    xml = _sequence(_wav(media / "picture.wav", None), _wav(media / "music.wav", None),
                    _wav(media / "dialogue.wav", PAUSE_S))
    path = tmp_path / "source.xml"
    path.write_text(xml, encoding="utf-8")
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text("denoise: false\nrms_gate_enabled: false\n", encoding="utf-8")
    return path, overlay


def _recut(tmp_path, export, *extra):
    source, overlay = export
    out, report = tmp_path / "out.xml", tmp_path / "report.json"
    assert xml_recut.main([str(source), "--overlay", str(overlay), "--out", str(out),
                           "--report", str(report), "--no-save-plan",
                           "--range-start-frame", str(RANGE[0]),
                           "--range-end-frame", str(RANGE[1]), *extra]) == 0
    import json
    return ET.parse(out).getroot().find("sequence"), json.loads(report.read_text(encoding="utf-8"))


def _tracks(sequence):
    return sequence.findall("media/video/track") + sequence.findall("media/audio/track")


def test_default_reference_is_the_switched_on_dialogue_track(export):
    source, _ = export
    checked = check_reference_audio(source.read_text(encoding="utf-8"))
    assert checked["xml_track"] == 2  # A2's left channel, not the switched-off A1
    assert [Path(f).name for f in checked["files"]] == ["dialogue.wav"]
    assert checked["clip_count"] == 2


def test_default_run_cuts_the_dialogue_pause_on_every_track_in_sync(tmp_path, export):
    sequence, report = _recut(tmp_path, export)
    removed = report["removed_frames"]
    assert report["cuts_applied"] >= 1 and removed > 0
    assert int(sequence.findtext("duration")) == FRAMES - removed

    for track in _tracks(sequence):
        clips = track.findall("clipitem")
        # Every clip started aligned (start == in). After the cut, a piece is either
        # untouched (offset 0) or shifted by exactly the removed duration — on every
        # track, so picture, music and both dialogue channels stay in sync.
        offsets = {int(c.findtext("in")) - int(c.findtext("start")) for c in clips}
        assert offsets == {0, removed}, (track.get("currentExplodedTrackIndex"), offsets)
        for c in clips:
            # The audio engine reads ticks; stale ticks play the wrong audio silently.
            assert int(c.findtext("pproTicksIn")) == frame_to_ticks(int(c.findtext("in")), TB)
            assert int(c.findtext("pproTicksOut")) == frame_to_ticks(int(c.findtext("out")), TB)
            # The removed span lies inside the pause and inside In/Out.
            if int(c.findtext("in")) - int(c.findtext("start")) == removed:
                cut_end = int(c.findtext("in"))
                cut_start = cut_end - removed
                assert RANGE[0] <= cut_start and cut_end <= RANGE[1]
                assert PAUSE_S[0] * FPS <= cut_start and cut_end <= PAUSE_S[1] * FPS


def test_default_run_preserves_unknown_xml_and_file_listings(tmp_path, export):
    sequence, _ = _recut(tmp_path, export)
    # Content the transform has no model for round-trips.
    assert sequence.findtext("timecode/string") == "00:00:00:00"
    assert sequence.findtext("media/video/format/samplecharacteristics/width") == "1920"
    assert sequence.findtext("media/audio/numOutputChannels") == "2"
    assert {c.findtext("logginginfo/description") for c in sequence.iter("clipitem")
            if c.find("logginginfo") is not None} == {"take 3"}
    # Channel grouping and track switches survive, so Premiere re-imports the same tracks.
    audio = sequence.findall("media/audio/track")
    assert [(t.get("totalExplodedTrackCount"), t.get("currentExplodedTrackIndex"),
             t.findtext("enabled")) for t in audio] == [
        ("2", "0", "FALSE"), ("2", "1", "FALSE"), ("2", "0", "TRUE"), ("2", "1", "TRUE")]
    # Each file still has exactly one full listing, so no clip goes offline on import.
    listed = [f.get("id") for f in sequence.iter("file") if f.find("pathurl") is not None]
    assert sorted(listed) == ["fd", "fm", "fv"]


def test_explicit_premiere_track_maps_through_channel_groups(tmp_path, export):
    """The panel sends Premiere's logical track; the helper maps it to XML channel
    tracks. Picking A1 (the switched-off music) is honored — and music never pauses,
    so nothing is cut. Picking A2 gives the same result as the default."""
    source, _ = export
    xml = source.read_text(encoding="utf-8")
    a1 = reference_audio_track(xml, {"audio_track": 0, "audio_track_count": 2})
    a2 = reference_audio_track(xml, {"audio_track": 1, "audio_track_count": 2})
    assert (a1, a2) == (0, 2)

    _, report = _recut(tmp_path, export, "--audio-track", str(a1))
    assert report["cuts_applied"] == 0 and report["removed_frames"] == 0

    default_seq, _ = _recut(tmp_path, export)
    default_xml = ET.tostring(default_seq, encoding="unicode")
    explicit_seq, _ = _recut(tmp_path, export, "--audio-track", str(a2))
    assert ET.tostring(explicit_seq, encoding="unicode") == default_xml
