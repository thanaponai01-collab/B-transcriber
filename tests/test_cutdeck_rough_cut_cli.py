"""Phase 3 acceptance — cutdeck.rough_cut CLI + duration guard
(docs/HANDOFF_CUTDECK_XML_RECUT.md).
"""

import json
import logging
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from cutdeck import rough_cut  # noqa: E402
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


def _sequence_json(duration_frames, name="My Sequence"):
    return json.dumps({"ticks_per_frame": "8467200000", "end_ticks": str(duration_frames * 8467200000),
                      "audio_tracks": [{"enabled": True, "clips": [{
                          "path": "C:/media/fixture.wav", "enabled": True, "start_ticks": "0",
                          "in_ticks": "0", "out_ticks": str(duration_frames * 8467200000)}]}]})


@pytest.fixture
def sequence_json_path(tmp_path):
    # 6500ms at 30fps == 195 frames — matches the synthetic mixdown's duration.
    p = tmp_path / "seq.json"
    p.write_text(_sequence_json(195), encoding="utf-8")
    return p


def test_dry_run_writes_no_file_and_prints_summary(mixdown_path, sequence_json_path, capsys, tmp_path):
    rc = rough_cut.main([str(sequence_json_path), mixdown_path, "--dry-run", "--job-id", "1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cut spans" in out
    assert not (tmp_path / "seq_cut.xml").exists()


def test_mixdown_shorter_than_sequence_refuses_with_both_durations(mixdown_path, tmp_path):
    # Sequence claims far more frames than the mixdown actually spans.
    seq_path = tmp_path / "seq.json"
    seq_path.write_text(_sequence_json(30_000), encoding="utf-8")  # 1000s vs ~6.5s mixdown
    with pytest.raises(rough_cut.DurationMismatch) as exc:
        rough_cut.main([str(seq_path), mixdown_path, "--dry-run", "--job-id", "1"])
    msg = str(exc.value)
    assert "1000000" in msg or "1,000,000" in msg or "6500" in msg  # some duration figure present
    assert "mixdown duration" in msg


def test_no_asr_engine_imported_from_cli(mixdown_path, sequence_json_path):
    before = {m for m in sys.modules if m.startswith("engines")}
    rough_cut.main([str(sequence_json_path), mixdown_path, "--dry-run", "--job-id", "1"])
    after = {m for m in sys.modules if m.startswith("engines")}
    assert after == before


def test_scoped_cli_report_and_no_database_write(mixdown_path, sequence_json_path, tmp_path):
    out = tmp_path / "cuts.json"
    db = tmp_path / "unused.db"
    assert rough_cut.main([str(sequence_json_path), mixdown_path, "--range-start-frame", "55",
                           "--range-end-frame", "80", "--db", str(db), "--cuts-json", str(out)]) == 0
    result = json.loads(out.read_text())
    assert 0 < result["report"]["removed_frames"] <= 25
    assert all(55 <= a < b <= 80 for a, b in result["cuts_frames"])
    assert not db.exists()


def _count_ingest_calls(monkeypatch):
    calls = []
    real = ingest_mod.ingest

    def counting(*a, **kw):
        calls.append(a)
        return real(*a, **kw)

    monkeypatch.setattr(ingest_mod, "ingest", counting)
    return calls


def test_rough_cut_ingests_mixdown_once(mixdown_path, sequence_json_path, monkeypatch):
    calls = _count_ingest_calls(monkeypatch)
    rc = rough_cut.main([str(sequence_json_path), mixdown_path, "--dry-run", "--job-id", "1"])
    assert rc == 0
    assert len(calls) == 1


def test_asr_rough_cut_shares_one_raw_ingest_with_run_file(
        mixdown_path, sequence_json_path, monkeypatch, tmp_path):
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
    rc = rough_cut.main([str(sequence_json_path), mixdown_path, "--dry-run",
                         "--job-id", "1", "--asr", "--db", str(db)])
    assert rc == 0
    assert len(calls) == 1
    assert seen["result"] is not None


def _asr_run(monkeypatch, tmp_path, mixdown_path, sequence_json_path, *, extracted,
             raw_words=None):
    """Run --asr with a run_file stub that persists rows like the real one.
    Returns (db path, job id the stub created)."""
    import shutil

    from cutdeck import audio_extract
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
    argv = [str(sequence_json_path), "--dry-run", "--job-id", "1", "--asr", "--db", str(db)]
    if extracted:
        def fake_extract(xml, out, track, **kw):
            shutil.copy(mixdown_path, out)
            return out
        monkeypatch.setattr(audio_extract, "extract_mixdown", fake_extract)
    else:
        argv.insert(1, mixdown_path)
    assert rough_cut.main(argv) == 0
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
        mixdown_path, sequence_json_path, monkeypatch, tmp_path):
    db, job = _asr_run(monkeypatch, tmp_path, mixdown_path, sequence_json_path, extracted=True)
    assert _row_counts(db, job) == {"job": 1, "token": 1, "span": 1}


def test_asr_rerun_on_same_mixdown_makes_no_asr_pass_and_same_cuts(
        mixdown_path, sequence_json_path, monkeypatch, tmp_path):
    """Issue #61: the second run reuses the finished job's transcript."""
    import shutil

    from cutdeck import audio_extract
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
    monkeypatch.setattr(audio_extract, "extract_mixdown", fake_extract)
    outs = []
    for n in (1, 2):
        out = tmp_path / f"cuts{n}.json"
        assert rough_cut.main([str(sequence_json_path), "--asr", "--job-id", "1",
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
        mixdown_path, sequence_json_path, monkeypatch, tmp_path):
    db, job = _asr_run(monkeypatch, tmp_path, mixdown_path, sequence_json_path, extracted=False)
    assert _row_counts(db, job) == {"job": 1, "token": 1, "span": 1}


@pytest.mark.parametrize("extracted", [True, False])
def test_asr_forwards_word_timeline_to_the_plan(
        mixdown_path, sequence_json_path, monkeypatch, tmp_path, extracted):
    """words_for_job must be read before the temp-mixdown purge drops raw_words_json."""
    from cutdeck import sequence_mixdown

    seen = {}
    real = sequence_mixdown.plan_from_mixdown

    def spy(*a, **kw):
        seen["words"] = kw.get("words")
        return real(*a, **kw)

    monkeypatch.setattr(sequence_mixdown, "plan_from_mixdown", spy)
    raw = [dict(text="เอ่อ", start_ms=700, end_ms=1000, confidence=None)]
    _asr_run(monkeypatch, tmp_path, mixdown_path, sequence_json_path,
             extracted=extracted, raw_words=raw)
    assert [(w.text, w.start_ms, w.end_ms) for w in seen["words"]] == [("เอ่อ", 700, 1000)]


def test_cli_emits_progress_lines_the_bridge_can_parse(mixdown_path, sequence_json_path, capsys, tmp_path):
    from cutdeck.helper import parse_progress

    db_path = tmp_path / "test.db"
    from transcribe.db import store
    store.init_db(db_path)
    conn = store.connect(db_path)
    job_id = store.create_job(conn, store.create_media(conn, mixdown_path), "mock", "", "test")
    conn.close()

    rc = rough_cut.main([str(sequence_json_path), mixdown_path, "--job-id", str(job_id),
                         "--db", str(db_path), "--cuts-json", str(tmp_path / "cuts.json")])
    assert rc == 0
    lines = capsys.readouterr().out.splitlines()
    progress = [parse_progress(line) for line in lines if line.startswith("PROGRESS:")]
    assert all(progress), "an emitted PROGRESS line the bridge cannot parse"
    pcts = [p["pct"] for p in progress]
    assert pcts == sorted(set(pcts)), "progress must only move forward"
    assert progress[-1]["stage"] == "Calculating cut spans"
    assert pcts[-1] == 85


def test_cuts_json_is_scoped_and_carries_the_exact_source_snapshot(mixdown_path, sequence_json_path, tmp_path):
    out = tmp_path / "cuts.json"
    assert rough_cut.main([str(sequence_json_path), mixdown_path,
                           "--range-start-frame", "30", "--range-end-frame", "180",
                           "--cuts-json", str(out)]) == 0
    data = json.loads(out.read_text())
    cuts = data["cuts_frames"]
    assert cuts and all(30 <= a < b <= 180 for a, b in cuts)
    assert all(b1 <= a2 for (_, b1), (a2, _) in zip(cuts, cuts[1:]))
    assert data["report"]["cuts_applied"] == len(cuts)
    assert data["report"]["removed_frames"] == sum(b - a for a, b in cuts)
    assert data["ticks_per_frame"] == "8467200000"
    assert data["sequence_duration_frames"] == 195
    assert data["source_sequence"] == json.loads(sequence_json_path.read_text())
    assert not list(tmp_path.glob("*.xml"))


def test_ticks_per_frame_is_exact_or_refused():
    from cutdeck.contracts import Timebase
    from cutdeck.sequence_timing import SequenceRefusal
    assert rough_cut.ticks_per_frame(Timebase(fps_num=30000, fps_den=1001)) == 8475667200
    with pytest.raises(SequenceRefusal):
        rough_cut.ticks_per_frame(Timebase(fps_num=254016000001, fps_den=1))
