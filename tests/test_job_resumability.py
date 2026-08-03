"""Phase 4.1 — job resumability (GAP-8): a crash after an engine completes must
not force re-running it. run_file() persists each engine's tokens to
engine_result and tracks job_phase; a resumed 'failed' job for the same media +
engine pair + pipeline version reuses whatever phases already finished.

Mirrors tests/test_phase3_ingest.py's pattern (deterministic single-segment VAD,
no real Silero/denoise) so this stays a fast unit test.
"""

import tempfile
from pathlib import Path

import numpy as np

from transcribe.pipeline import ingest


def _synthetic_wav(seconds=3.0, sr=16000):
    import soundfile as sf
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    sig = (0.2 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)
    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    f.close()
    sf.write(f.name, sig, sr)
    return f.name


def _tmp_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return Path(f.name)


_CFG = {"engine_a": "mock", "engine_b": "passthrough", "denoise": True,
        "drop_tokens_over_silence": False}


def _run(monkeypatch, path, db):
    import transcribe.engines.mock  # noqa: F401 — trigger registration
    from transcribe.pipeline import run as pipeline_run

    monkeypatch.setattr(ingest, "_load_silero",
                        lambda: (object(), lambda a, m, **k: [{"start": 0, "end": len(a)}]))
    from transcribe.db import store
    store.init_db(db)
    return pipeline_run.run_file(path, _CFG, db)


def test_fresh_run_persists_engine_result_and_written_phase(monkeypatch):
    from transcribe.db import store

    path = _synthetic_wav()
    db = _tmp_db()
    tokens = _run(monkeypatch, path, db)
    assert len(tokens) > 0

    conn = store.connect(db)
    jobs = store.list_jobs(conn)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.status == "done"
    assert job.job_phase == "written"

    cached_a = store.get_engine_result(conn, job.id, "a")
    assert cached_a is not None
    assert cached_a.engine_name == "mock"
    import json
    assert len(json.loads(cached_a.tokens_json)) > 0
    conn.close()


def test_resume_skips_completed_engine_a(monkeypatch):
    from transcribe.db import store
    import transcribe.engines.mock as mock_mod

    path = _synthetic_wav()
    db = _tmp_db()
    _run(monkeypatch, path, db)

    conn = store.connect(db)
    job = store.list_jobs(conn)[0]
    assert job.job_phase == "written"

    # Simulate a crash that happened right after engine A finished: only its
    # phase/engine_result survive, and status flips to 'failed' as run_file's
    # except-block would on a real crash.
    store.update_job_phase(conn, job.id, "engine_a_done")
    store.update_job_status(conn, job.id, "failed")
    conn.close()

    calls = []
    orig_transcribe = mock_mod.MockEngine.transcribe

    def spy_transcribe(self, inp):
        calls.append(True)
        return orig_transcribe(self, inp)

    monkeypatch.setattr(mock_mod.MockEngine, "transcribe", spy_transcribe)

    tokens = _run(monkeypatch, path, db)
    assert len(tokens) > 0
    assert not calls, "engine A must not re-run when its phase is already cached"

    conn = store.connect(db)
    jobs = store.list_jobs(conn)
    assert len(jobs) == 1, "resume must reuse the failed job, not create a new one"
    assert jobs[0].id == job.id
    assert jobs[0].status == "done"
    assert jobs[0].job_phase == "written"
    conn.close()


def test_whole_file_engine_raw_words_are_persisted(monkeypatch):
    """4.2: EngineResult.raw["words"] must survive to engine_result.raw_words_json
    instead of being discarded after _transcribe_with, so CutDeck Phase 5 filler
    excision can re-derive word granularity without re-running the engine."""
    import json

    from transcribe.contracts import EngineInput, EngineResult, RecognizedToken
    from transcribe.engines.base import Engine
    from transcribe.engines.registry import register
    from transcribe.db import store

    @register("wf_test_engine")
    class _WholeFileTestEngine(Engine):
        prefers_whole_file = True

        def __init__(self, **kwargs):
            pass

        def load(self):
            pass

        def transcribe(self, inp: EngineInput) -> EngineResult:
            return EngineResult(
                tokens=[RecognizedToken("hello world", 0, 500, 0.9, "latin")],
                engine_name="wf_test_engine",
                timestamps_final=True,
                raw={"words": [{"text": "hello", "start_ms": 0, "end_ms": 200},
                                {"text": "world", "start_ms": 200, "end_ms": 500}]},
            )

        def unload(self):
            pass

    path = _synthetic_wav()
    db = _tmp_db()
    cfg = {"engine_a": "wf_test_engine", "engine_b": "passthrough",
           "denoise": False, "drop_tokens_over_silence": False}

    monkeypatch.setattr(ingest, "_load_silero",
                        lambda: (object(), lambda a, m, **k: [{"start": 0, "end": len(a)}]))
    store.init_db(db)
    from transcribe.pipeline import run as pipeline_run
    pipeline_run.run_file(path, cfg, db)

    conn = store.connect(db)
    job = store.list_jobs(conn)[0]
    cached_a = store.get_engine_result(conn, job.id, "a")
    assert cached_a.raw_words_json is not None
    words = json.loads(cached_a.raw_words_json)
    assert words == [{"text": "hello", "start_ms": 0, "end_ms": 200},
                      {"text": "world", "start_ms": 200, "end_ms": 500}]
    conn.close()


def test_different_engine_pair_is_not_resumable(monkeypatch):
    """A failed job for a different engine pair must not be treated as resumable
    — its cached engine_result rows belong to a model that's no longer active."""
    from transcribe.db import store

    path = _synthetic_wav()
    db = _tmp_db()
    _run(monkeypatch, path, db)

    conn = store.connect(db)
    job = store.list_jobs(conn)[0]
    media_id = job.media_id
    store.update_job_status(conn, job.id, "failed")

    resumable = store.find_resumable_job(conn, media_id, "some_other_engine", "passthrough", "1.0.0")
    assert resumable is None
    conn.close()
