"""Issue #28 — extraction through recut on a representative stacked-track export.

The fixture is shaped like a real Premiere FCP7 export: one video track and two
stereo audio tracks, each exploded into two XML channel tracks
(``totalExplodedTrackCount``/``currentExplodedTrackIndex``), ``pproTicksIn``/``Out`` on
every clip, the full ``<file>`` listing only on a file's first use, and XML the
transform has no model for. A1 is switched-off music that never goes quiet; A2 is
dialogue with one long pause. The VAD reads the real extracted audio, so *which*
track was analyzed decides whether anything is cut.

Real ffmpeg, real extraction, real ``rough_cut.main``; only Silero is replaced by an
energy detector so no model download or GPU is needed.
"""
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET

import numpy as np
import pytest

from cutdeck import rough_cut, sequence_model
from cutdeck.helper import reference_audio_track
from cutdeck.sequence_model import check_reference_audio
from tests.sequence_fixture import from_fcp7_xml, panel_json_from_xml
import json
from cutdeck.sequence_timing import frame_to_ticks
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
    path = tmp_path / "sequence.json"
    path.write_text(json.dumps(panel_json_from_xml(xml)), encoding="utf-8")
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text("denoise: false\nrms_gate_enabled: false\n", encoding="utf-8")
    return path, overlay


def _analyse(tmp_path, export, *extra):
    source, overlay = export
    out = tmp_path / "cuts.json"
    assert rough_cut.main([str(source), "--overlay", str(overlay), "--cuts-json", str(out),
                           "--range-start-frame", str(RANGE[0]),
                           "--range-end-frame", str(RANGE[1]), *extra]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    return data, data["report"]




def test_default_reference_is_the_switched_on_dialogue_track(export):
    source, _ = export
    checked = check_reference_audio(sequence_model.load(source))
    assert checked["track"] == 1  # A2, not the switched-off A1
    assert [Path(f).name for f in checked["files"]] == ["dialogue.wav"]
    assert checked["clip_count"] == 2


def test_json_analysis_cuts_the_dialogue_pause_in_sequence_frames(tmp_path, export):
    cuts, report = _analyse(tmp_path, export)
    assert report["cuts_applied"] >= 1 and report["removed_frames"] > 0
    for a, b in cuts["cuts_frames"]:
        assert RANGE[0] <= a < b <= RANGE[1]
        assert PAUSE_S[0] * FPS <= a and b <= PAUSE_S[1] * FPS
    assert cuts["source_sequence"] == json.loads(export[0].read_text())


def test_analyze_returns_the_pause_cut_without_a_cli_or_xml(export):
    import yaml
    source, overlay = export
    config = yaml.safe_load((Path(__file__).resolve().parent.parent / "transcribe/config.yaml").read_text(encoding="utf-8"))
    rough_cut._deep_update(config, yaml.safe_load(overlay.read_text(encoding="utf-8")))
    plan, cuts = rough_cut.analyze(sequence_model.load(source), config, frame_range=RANGE)
    assert len(cuts) >= 1
    for a, b in cuts:
        assert RANGE[0] <= a < b <= RANGE[1]
        assert PAUSE_S[0] * FPS <= a and b <= PAUSE_S[1] * FPS




def test_explicit_premiere_track_maps_through_channel_groups(tmp_path, export):
    """The panel sends Premiere's logical track; the helper reads it as that track. Picking A1 (the switched-off music) is honored — and music never pauses,
    so nothing is cut. Picking A2 gives the same result as the default."""
    source, _ = export
    sequence = sequence_model.load(source)
    a1 = reference_audio_track(sequence, {"audio_track": 0, "audio_track_count": 2})
    a2 = reference_audio_track(sequence, {"audio_track": 1, "audio_track_count": 2})
    assert (a1, a2) == (0, 1)

    _, report = _analyse(tmp_path, export, "--audio-track", str(a1))
    assert report["cuts_applied"] == 0 and report["removed_frames"] == 0

    default_seq, _ = _analyse(tmp_path, export)
    default_cuts = default_seq["cuts_frames"]
    explicit_seq, _ = _analyse(tmp_path, export, "--audio-track", str(a2))
    assert explicit_seq["cuts_frames"] == default_cuts
