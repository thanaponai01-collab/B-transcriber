"""Acceptance — cutdeck.xml_audio_extract: build a mixdown WAV straight from
an XML's own clipitems + source media, no Premiere export step.

Runs against real ffmpeg on PATH (not mocked), same discipline as
tests/test_cutdeck_preview.py.
"""

import sys
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from cutdeck.xml_audio_extract import XmlRecutRefusal, extract_mixdown  # noqa: E402

SR = 48000


def _tone_wav(path: Path, seconds: float, freq: float, amp: float = 0.8):
    import soundfile as sf
    t = np.linspace(0, seconds, int(SR * seconds), endpoint=False)
    audio = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(str(path), audio, SR)
    return audio


def _pathurl(p: Path) -> str:
    posix = str(p.resolve()).replace("\\", "/")
    return "file://localhost/" + quote(posix, safe="/:")


def _sequence_xml(source_path: Path, clip_specs, duration_frames: int, fps: int = 30) -> str:
    """clip_specs: list of (start_frame, end_frame, in_frame, out_frame, enabled)."""
    clips_xml = ""
    for i, (start, end, in_, out, enabled) in enumerate(clip_specs):
        clips_xml += f"""
                    <clipitem id="a{i}">
                        <name>seg{i}</name>
                        <enabled>{'TRUE' if enabled else 'FALSE'}</enabled>
                        <duration>{duration_frames}</duration>
                        <start>{start}</start><end>{end}</end>
                        <in>{in_}</in><out>{out}</out>
                        <file id="file-1">
                            <pathurl>{_pathurl(source_path)}</pathurl>
                        </file>
                    </clipitem>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="4">
    <sequence id="sequence-1">
        <duration>{duration_frames}</duration>
        <rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>
        <name>Test</name>
        <media>
            <video></video>
            <audio>
                <track>{clips_xml}
                    <enabled>TRUE</enabled>
                    <locked>FALSE</locked>
                </track>
            </audio>
        </media>
    </sequence>
</xmeml>
"""


def test_extracted_audio_matches_source_segment(tmp_path):
    # 10s source tone; sequence uses seconds [2,5) of it, placed at timeline [0, 3s).
    src = tmp_path / "source.wav"
    audio = _tone_wav(src, 10.0, 440.0)
    fps = 30
    dur_frames = 300  # 10s @ 30fps
    in_frame, out_frame = 2 * fps, 5 * fps
    xml = _sequence_xml(src, [(0, out_frame - in_frame, in_frame, out_frame, True)], dur_frames, fps)

    out_wav = tmp_path / "mixdown.wav"
    extract_mixdown(xml, str(out_wav))

    import soundfile as sf
    result, sr = sf.read(str(out_wav), dtype="float32")
    assert sr == 48000
    # Total duration matches the SEQUENCE's declared duration (10s), not the clip's.
    assert abs(len(result) / sr - 10.0) < 0.05

    # The first 3 seconds should contain the extracted tone (non-silent).
    early = result[: int(2.5 * sr)]
    assert np.abs(early).mean() > 0.05
    # After the clip ends (past 3s), the buffer should be silence.
    late = result[int(4 * sr):]
    assert np.abs(late).mean() < 0.01


def test_disabled_clip_produces_silence(tmp_path):
    src = tmp_path / "source.wav"
    _tone_wav(src, 5.0, 440.0)
    fps = 30
    dur_frames = 150  # 5s
    xml = _sequence_xml(src, [(0, 150, 0, 150, False)], dur_frames, fps)

    out_wav = tmp_path / "mixdown.wav"
    extract_mixdown(xml, str(out_wav))

    import soundfile as sf
    result, sr = sf.read(str(out_wav), dtype="float32")
    assert np.abs(result).mean() < 0.001


def test_no_audio_tracks_refuses(tmp_path):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="4">
    <sequence id="sequence-1">
        <duration>150</duration>
        <rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate>
        <name>Test</name>
        <media><video></video><audio></audio></media>
    </sequence>
</xmeml>
"""
    with pytest.raises(XmlRecutRefusal, match="no audio tracks"):
        extract_mixdown(xml, str(tmp_path / "out.wav"))


def test_out_of_range_audio_track_index_refuses(tmp_path):
    src = tmp_path / "source.wav"
    _tone_wav(src, 2.0, 440.0)
    xml = _sequence_xml(src, [(0, 60, 0, 60, True)], 60, 30)
    with pytest.raises(XmlRecutRefusal, match="audio track"):
        extract_mixdown(xml, str(tmp_path / "out.wav"), audio_track_index=5)


def test_range_extracts_only_range_plus_pad(tmp_path):
    # One clip spans the whole 20s timeline; range is [10s, 12s) with a 2s pad,
    # so the WAV covers only [8s, 14s) — the clip must be trimmed, not skipped.
    src = tmp_path / "source.wav"
    _tone_wav(src, 20.0, 440.0)
    fps = 30
    xml = _sequence_xml(src, [(0, 600, 0, 600, True)], 600, fps)

    out_wav = tmp_path / "mixdown.wav"
    extract_mixdown(xml, str(out_wav), range_start_frame=300, range_end_frame=360, pad_seconds=2.0)

    import soundfile as sf
    result, sr = sf.read(str(out_wav), dtype="float32")
    assert abs(len(result) / sr - 6.0) < 0.05  # only the window: [8s, 14s)
    assert np.abs(result[int(0.2 * sr):int(5.8 * sr)]).mean() > 0.05


def test_range_skips_clips_outside_window(tmp_path, monkeypatch):
    import subprocess
    src = tmp_path / "source.wav"
    _tone_wav(src, 20.0, 440.0)
    # three 5s clips back to back; range [6s, 8s) pad 0 touches only the second.
    xml = _sequence_xml(src, [(0, 150, 0, 150, True), (150, 300, 150, 300, True),
                              (300, 450, 300, 450, True)], 600, 30)
    calls = []
    real_run = subprocess.run
    monkeypatch.setattr(subprocess, "run", lambda cmd, *a, **k: (calls.append(cmd), real_run(cmd, *a, **k))[1])

    extract_mixdown(xml, str(tmp_path / "out.wav"), range_start_frame=180, range_end_frame=240, pad_seconds=0)
    assert len(calls) == 1


def test_recut_range_matches_full_mixdown_and_guard_rejects_wrong_length(tmp_path, monkeypatch):
    """The trimmed-WAV path must yield the same recut as a full-length mixdown
    over the same range, and the duration guard must catch a wrong-length WAV."""
    import soundfile as sf
    from cutdeck import xml_recut
    from transcribe.pipeline import ingest as ingest_mod

    sr = 48000
    t = np.arange(int(20 * sr)) / sr
    audio = (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    audio[int(4 * sr):int(10 * sr)] = 0.0   # silence 4-10s
    audio[int(14 * sr):] = 0.0              # silence 14-20s
    src = tmp_path / "source.wav"
    sf.write(str(src), audio, sr)
    xml = _sequence_xml(src, [(0, 600, 0, 600, True)], 600, 30)
    xml_path = tmp_path / "seq.xml"
    xml_path.write_text(xml, encoding="utf-8")

    def energy_vad(tensor, model, **kw):
        loud = (np.abs(np.asarray(tensor)) > 0.1).astype(np.int8)
        edges = np.flatnonzero(np.diff(np.concatenate([[0], loud, [0]])))
        return [{"start": int(a), "end": int(b)} for a, b in zip(edges[::2], edges[1::2])]

    monkeypatch.setattr(ingest_mod, "_load_silero", lambda: (object(), energy_vad))
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text("denoise: false\nrms_gate_enabled: false\n", encoding="utf-8")
    rng = ["--range-start-frame", "180", "--range-end-frame", "360"]

    def run(out_name, *extra):
        out = tmp_path / out_name
        rc = xml_recut.main([str(xml_path), *extra, *rng, "--overlay", str(overlay),
                             "--out", str(out), "--no-save-plan"])
        assert rc == 0
        return out.read_text(encoding="utf-8")

    scoped = run("scoped.xml")  # CLI trims the mixdown itself
    full_wav = tmp_path / "full.wav"
    extract_mixdown(xml, str(full_wav))
    assert run("full.xml", str(full_wav)) == scoped

    # 6s-10s of a 20s sequence is not the whole sequence and not the window.
    wrong = tmp_path / "wrong.wav"
    sf.write(str(wrong), audio[: 8 * sr], sr)
    with pytest.raises(xml_recut.DurationMismatch):
        run("wrong.xml", str(wrong))
