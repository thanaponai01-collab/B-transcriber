"""Phase 3 acceptance — cutdeck.xml_recut CLI + duration guard
(docs/HANDOFF_CUTDECK_XML_RECUT.md).
"""

import logging
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from cutdeck import xml_recut  # noqa: E402
from transcribe.pipeline import ingest as ingest_mod  # noqa: E402

SR = 16000


def _synthetic_multi_silence_wav():
    """speech[0-1.5s] silence[1.5-3.0s] speech[3.0-4.0s] silence[4.0-5.5s] speech[5.5-6.5s]."""
    import soundfile as sf

    def loud(seconds):
        t = np.linspace(0, seconds, int(SR * seconds), endpoint=False)
        return (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)

    def quiet(seconds):
        return np.zeros(int(SR * seconds), dtype=np.float32)

    audio = np.concatenate([loud(1.5), quiet(1.5), loud(1.0), quiet(1.5), loud(1.0)])
    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    f.close()
    sf.write(f.name, audio, SR)
    return f.name, audio


def _stub_speech_timestamps(audio: np.ndarray):
    def fn(tensor, model, **kwargs):
        bounds_s = [(0.0, 1.5), (3.0, 4.0), (5.5, 6.5)]
        return [{"start": int(s * SR), "end": int(e * SR)} for s, e in bounds_s]
    return fn


@pytest.fixture
def mixdown_path(monkeypatch):
    path, audio = _synthetic_multi_silence_wav()
    monkeypatch.setattr(
        ingest_mod, "_load_silero",
        lambda: (object(), _stub_speech_timestamps(audio)),
    )
    yield path


def _sequence_xml(duration_frames: int, name: str = "My Sequence") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="4">
    <sequence id="sequence-1">
        <duration>{duration_frames}</duration>
        <rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate>
        <name>{name}</name>
        <media>
            <video>
                <track>
                    <clipitem id="v1">
                        <name>v1</name>
                        <duration>{duration_frames}</duration>
                        <start>0</start><end>{duration_frames}</end>
                        <in>0</in><out>{duration_frames}</out>
                        <file id="file-1" />
                    </clipitem>
                    <enabled>TRUE</enabled>
                    <locked>FALSE</locked>
                </track>
            </video>
            <audio>
                <track>
                    <clipitem id="a1">
                        <name>a1</name>
                        <duration>{duration_frames}</duration>
                        <start>0</start><end>{duration_frames}</end>
                        <in>0</in><out>{duration_frames}</out>
                        <file id="file-1" />
                    </clipitem>
                    <enabled>TRUE</enabled>
                    <locked>FALSE</locked>
                </track>
            </audio>
        </media>
    </sequence>
</xmeml>
"""


@pytest.fixture
def sequence_xml_path(tmp_path):
    # 6500ms at 30fps == 195 frames — matches the synthetic mixdown's duration.
    p = tmp_path / "seq.xml"
    p.write_text(_sequence_xml(195), encoding="utf-8")
    return p


def test_dry_run_writes_no_file_and_prints_summary(mixdown_path, sequence_xml_path, capsys, tmp_path):
    rc = xml_recut.main([str(sequence_xml_path), mixdown_path, "--dry-run", "--job-id", "1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cut spans" in out
    assert not (tmp_path / "seq_cut.xml").exists()


def test_mixdown_shorter_than_sequence_refuses_with_both_durations(mixdown_path, tmp_path):
    # Sequence claims far more frames than the mixdown actually spans.
    seq_path = tmp_path / "seq.xml"
    seq_path.write_text(_sequence_xml(30_000), encoding="utf-8")  # 1000s vs ~6.5s mixdown
    with pytest.raises(xml_recut.DurationMismatch) as exc:
        xml_recut.main([str(seq_path), mixdown_path, "--dry-run", "--job-id", "1"])
    msg = str(exc.value)
    assert "1000000" in msg or "1,000,000" in msg or "6500" in msg  # some duration figure present
    assert "mixdown duration" in msg


def test_no_asr_engine_imported_from_cli(mixdown_path, sequence_xml_path):
    before = {m for m in sys.modules if m.startswith("engines")}
    xml_recut.main([str(sequence_xml_path), mixdown_path, "--dry-run", "--job-id", "1"])
    after = {m for m in sys.modules if m.startswith("engines")}
    assert after == before


def test_writes_output_beside_input_with_cut_suffix(mixdown_path, sequence_xml_path, tmp_path):
    db_path = tmp_path / "test.db"
    from transcribe.db import store
    store.init_db(db_path)
    conn = store.connect(db_path)
    media_id = store.create_media(conn, mixdown_path)
    job_id = store.create_job(conn, media_id, "mock", "", "test")
    conn.close()

    rc = xml_recut.main([str(sequence_xml_path), mixdown_path, "--job-id", str(job_id),
                          "--db", str(db_path)])
    assert rc == 0
    out_path = tmp_path / "seq_cut.xml"
    assert out_path.exists()
    root = ET.fromstring(out_path.read_text(encoding="utf-8"))
    assert root.find("sequence/name").text == "My Sequence — CutDeck"
