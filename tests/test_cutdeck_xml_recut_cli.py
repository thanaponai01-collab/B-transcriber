"""Phase 3 acceptance — cutdeck.xml_recut CLI + duration guard
(docs/HANDOFF_CUTDECK_XML_RECUT.md).
"""

import json
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


def test_scoped_cli_report_and_no_database_write(mixdown_path, sequence_xml_path, tmp_path):
    import json
    report = tmp_path / "report.json"
    db = tmp_path / "unused.db"
    xml_recut.main([str(sequence_xml_path), mixdown_path, "--range-start-frame", "55",
                    "--range-end-frame", "80", "--no-save-plan", "--db", str(db),
                    "--report", str(report)])
    result = json.loads(report.read_text())
    assert result["range_frames"] == [55, 80]
    assert 0 < result["removed_frames"] <= 25
    assert not db.exists()
    root = ET.parse(sequence_xml_path.with_name("seq_cut.xml"))
    for clip in root.findall(".//clipitem"):
        start, end = int(clip.findtext("in")), int(clip.findtext("out"))
        assert end <= 55 or start >= 80


def _count_ingest_calls(monkeypatch):
    calls = []
    real = ingest_mod.ingest

    def counting(*a, **kw):
        calls.append(a)
        return real(*a, **kw)

    monkeypatch.setattr(ingest_mod, "ingest", counting)
    return calls


def test_rough_cut_ingests_mixdown_once(mixdown_path, sequence_xml_path, monkeypatch):
    calls = _count_ingest_calls(monkeypatch)
    rc = xml_recut.main([str(sequence_xml_path), mixdown_path, "--dry-run", "--job-id", "1"])
    assert rc == 0
    assert len(calls) == 1


def test_asr_rough_cut_shares_one_raw_ingest_with_run_file(
        mixdown_path, sequence_xml_path, monkeypatch, tmp_path):
    from transcribe.db import store
    from transcribe.pipeline import run as run_mod

    calls = _count_ingest_calls(monkeypatch)
    seen = {}

    def fake_run_file(path, config, db_path, ingest_result=None):
        seen["result"] = ingest_result
        return []

    monkeypatch.setattr(run_mod, "run_file", fake_run_file)
    db = tmp_path / "t.db"
    store.init_db(db)
    rc = xml_recut.main([str(sequence_xml_path), mixdown_path, "--dry-run",
                         "--job-id", "1", "--asr", "--db", str(db)])
    assert rc == 0
    assert len(calls) == 1
    assert seen["result"] is not None


def _asr_run(monkeypatch, tmp_path, mixdown_path, sequence_xml_path, *, extracted,
             raw_words=None):
    """Run --asr with a run_file stub that persists rows like the real one.
    Returns (db path, job id the stub created)."""
    import shutil

    from cutdeck import xml_audio_extract
    from transcribe.db import store
    from transcribe.pipeline import run as run_mod

    db = tmp_path / "t.db"
    store.init_db(db)
    made = {}

    def fake_run_file(path, config, db_path, ingest_result=None):
        conn = store.connect(db_path)
        media_id = store.create_media(conn, path)
        job_id = store.create_job(conn, media_id, "a", "passthrough", "1.0.0")
        store.bulk_create_tokens(conn, [dict(
            job_id=job_id, idx=0, text="x", start_ms=0, end_ms=100, script="latin",
            confidence=None, source_engine="a", speaker_id=None)])
        store.bulk_create_speech_spans(
            conn, job_id, [dict(idx=0, start_ms=0, end_ms=100, kind="speech")])
        if raw_words is not None:
            store.save_engine_result(conn, job_id, "a", "a", "[]", True,
                                     raw_words_json=json.dumps(raw_words))
        conn.close()
        made["job"] = job_id
        return [dict(text="x", start_ms=0, end_ms=100)]

    monkeypatch.setattr(run_mod, "run_file", fake_run_file)
    argv = [str(sequence_xml_path), "--dry-run", "--job-id", "1", "--asr", "--db", str(db)]
    if extracted:
        def fake_extract(xml, out, track, **kw):
            shutil.copy(mixdown_path, out)
            return out
        monkeypatch.setattr(xml_audio_extract, "extract_mixdown", fake_extract)
    else:
        argv.insert(1, mixdown_path)
    assert xml_recut.main(argv) == 0
    return db, made["job"]


def _row_counts(db, job_id):
    from transcribe.db import store
    conn = store.connect(db)
    try:
        def n(table):
            return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {'id' if table == 'job' else 'job_id'}=?",
                                (job_id,)).fetchone()[0]
        return {"job": n("job"), "token": n("token"), "span": n("speech_span")}
    finally:
        conn.close()


def test_asr_temp_mixdown_keeps_its_transcript_for_reuse(
        mixdown_path, sequence_xml_path, monkeypatch, tmp_path):
    db, job = _asr_run(monkeypatch, tmp_path, mixdown_path, sequence_xml_path, extracted=True)
    assert _row_counts(db, job) == {"job": 1, "token": 1, "span": 1}


def test_asr_rerun_on_same_mixdown_makes_no_asr_pass_and_same_cuts(
        mixdown_path, sequence_xml_path, monkeypatch, tmp_path):
    """Issue #61: the second run reuses the finished job's transcript."""
    import shutil

    from cutdeck import xml_audio_extract
    from transcribe.db import store
    from transcribe.pipeline import run as run_mod
    from transcribe.pipeline.plan import canonical_engine_names

    db = tmp_path / "t.db"
    store.init_db(db)
    calls = []

    def fake_run_file(path, config, db_path, ingest_result=None):
        calls.append(path)
        conn = store.connect(db_path)
        media_id = store.create_media(conn, path)
        a, b = canonical_engine_names(config)
        job_id = store.create_job(conn, media_id, a, b, run_mod.PIPELINE_VERSION)
        store.bulk_create_tokens(conn, [dict(
            job_id=job_id, idx=0, text="x", start_ms=0, end_ms=100, script="latin",
            confidence=None, source_engine="a", speaker_id=None)])
        store.update_job_phase(conn, job_id, "written")
        store.update_job_status(conn, job_id, "done")
        conn.close()
        return [dict(text="x", start_ms=0, end_ms=100)]

    def fake_extract(xml, out, track, **kw):
        shutil.copy(mixdown_path, out)
        return out

    monkeypatch.setattr(run_mod, "run_file", fake_run_file)
    monkeypatch.setattr(xml_audio_extract, "extract_mixdown", fake_extract)
    outs = []
    for n in (1, 2):
        out = tmp_path / f"cuts{n}.json"
        assert xml_recut.main([str(sequence_xml_path), "--asr", "--job-id", "1",
                               "--db", str(db), "--cuts-json", str(out)]) == 0
        outs.append(out.read_bytes())
    assert len(calls) == 1
    assert outs[0] == outs[1]


def test_find_finished_job_ignores_purged_and_mismatched_jobs(tmp_path):
    from transcribe.db import store

    db = tmp_path / "t.db"
    store.init_db(db)
    conn = store.connect(db)
    wav = tmp_path / "m.wav"
    wav.write_bytes(b"abc")
    media = store.create_media(conn, str(wav))
    job = store.create_job(conn, media, "a", "b", "1")
    store.bulk_create_tokens(conn, [dict(
        job_id=job, idx=0, text="x", start_ms=0, end_ms=1, script="latin",
        confidence=None, source_engine="a", speaker_id=None)])
    assert store.find_finished_job(conn, media, "a", "b", "1") is None  # still running
    store.update_job_phase(conn, job, "written")
    store.update_job_status(conn, job, "done")
    assert store.find_finished_job(conn, media, "a", "b", "1").id == job
    assert store.find_finished_job(conn, media, "a", "c", "1") is None
    assert store.find_finished_job(conn, media, "a", "b", "2") is None
    store.purge_job_transcript_data(conn, job)
    assert store.find_finished_job(conn, media, "a", "b", "1") is None
    conn.close()


def test_asr_caller_supplied_mixdown_keeps_rows(
        mixdown_path, sequence_xml_path, monkeypatch, tmp_path):
    db, job = _asr_run(monkeypatch, tmp_path, mixdown_path, sequence_xml_path, extracted=False)
    assert _row_counts(db, job) == {"job": 1, "token": 1, "span": 1}


@pytest.mark.parametrize("extracted", [True, False])
def test_asr_forwards_word_timeline_to_the_plan(
        mixdown_path, sequence_xml_path, monkeypatch, tmp_path, extracted):
    """words_for_job must be read before the temp-mixdown purge drops raw_words_json."""
    from cutdeck import sequence_mixdown

    seen = {}
    real = sequence_mixdown.plan_from_mixdown

    def spy(*a, **kw):
        seen["words"] = kw.get("words")
        return real(*a, **kw)

    monkeypatch.setattr(sequence_mixdown, "plan_from_mixdown", spy)
    raw = [dict(text="เอ่อ", start_ms=700, end_ms=1000, confidence=None)]
    _asr_run(monkeypatch, tmp_path, mixdown_path, sequence_xml_path,
             extracted=extracted, raw_words=raw)
    assert [(w.text, w.start_ms, w.end_ms) for w in seen["words"]] == [("เอ่อ", 700, 1000)]


def test_cli_emits_progress_lines_the_bridge_can_parse(mixdown_path, sequence_xml_path, capsys, tmp_path):
    from cutdeck.xml_bridge import parse_progress

    db_path = tmp_path / "test.db"
    from transcribe.db import store
    store.init_db(db_path)
    conn = store.connect(db_path)
    job_id = store.create_job(conn, store.create_media(conn, mixdown_path), "mock", "", "test")
    conn.close()

    rc = xml_recut.main([str(sequence_xml_path), mixdown_path, "--job-id", str(job_id),
                         "--db", str(db_path)])
    assert rc == 0
    lines = capsys.readouterr().out.splitlines()
    progress = [parse_progress(line) for line in lines if line.startswith("PROGRESS:")]
    assert all(progress), "an emitted PROGRESS line the bridge cannot parse"
    pcts = [p["pct"] for p in progress]
    assert pcts == sorted(set(pcts)), "progress must only move forward"
    assert [p["stage"] for p in progress][-2:] == ["Calculating cut spans", "Rewriting sequence XML"]
    assert pcts[-1] == 95


def test_transition_refused_before_any_audio_work(tmp_path, monkeypatch):
    """recut() refuses transitions whatever the plan; the CLI must not transcribe first."""
    xml = _sequence_xml(195).replace(
        "<enabled>TRUE</enabled>",
        "<transitionitem><start>90</start><end>100</end></transitionitem><enabled>TRUE</enabled>", 1)
    seq_path = tmp_path / "seq.xml"
    seq_path.write_text(xml, encoding="utf-8")

    def no_ingest(*args, **kwargs):
        raise AssertionError("ingest ran before the structural refusal")
    monkeypatch.setattr(ingest_mod, "ingest", no_ingest)
    with pytest.raises(xml_recut.XmlRecutRefusal, match="transitionitem"):
        xml_recut.main([str(seq_path), "--asr", "--job-id", "1"])


def test_cuts_json_equals_scoped_cuts_and_writes_no_xml(mixdown_path, sequence_xml_path, tmp_path):
    """Native rough cut (HANDOFF_CUTDECK_NATIVE_ROUGH_CUT 3.1): the cut list the panel
    applies is exactly the scoped_cuts the XML route would have applied."""
    import json
    out = tmp_path / "cuts.json"
    xml_argv = [str(sequence_xml_path), mixdown_path, "--no-save-plan",
                "--range-start-frame", "30", "--range-end-frame", "180"]
    assert xml_recut.main(xml_argv + ["--cuts-json", str(out)]) == 0
    assert not sequence_xml_path.with_name("seq_cut.xml").exists()
    data = json.loads(out.read_text())

    report = tmp_path / "report.json"
    xml_recut.main(xml_argv + ["--report", str(report)])
    xml_report = json.loads(report.read_text())

    cuts = data["cuts_frames"]
    assert cuts and all(30 <= a < b <= 180 for a, b in cuts)
    assert all(b1 <= a2 for (_, b1), (a2, _) in zip(cuts, cuts[1:]))
    assert data["report"]["cuts_applied"] == xml_report["cuts_applied"] == len(cuts)
    assert data["report"]["removed_frames"] == xml_report["removed_frames"]
    assert data["ticks_per_frame"] == str(254016000000 // 30)
    assert data["sequence_duration_frames"] == 195


def test_ticks_per_frame_is_exact_or_refused():
    from cutdeck.contracts import Timebase
    from cutdeck.xml_sequence import XmlRecutRefusal
    assert xml_recut.ticks_per_frame(Timebase(fps_num=30000, fps_den=1001)) == 8475667200
    with pytest.raises(XmlRecutRefusal):
        xml_recut.ticks_per_frame(Timebase(fps_num=254016000001, fps_den=1))
