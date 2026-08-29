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
