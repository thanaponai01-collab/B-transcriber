"""Item 2 of docs/arch-design-transcription-engine.md: every tool transcribes through
transcribe.service against one shared store."""

import tempfile
from pathlib import Path

import numpy as np

from transcribe.pipeline import ingest

_CFG = {"engine_a": "mock", "engine_b": "passthrough", "denoise": True,
        "drop_tokens_over_silence": False}


def _wav(seconds=3.0, sr=16000):
    import soundfile as sf
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    f.close()
    sf.write(f.name, (0.2 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), sr)
    return f.name


def _patch_vad(monkeypatch):
    import transcribe.engines.mock  # noqa: F401
    monkeypatch.setattr(ingest, "_load_silero",
                        lambda: (object(), lambda a, m, **k: [{"start": 0, "end": len(a)}]))


def _db(tmp_path):
    return tmp_path / "shared.db"


def test_transcribe_returns_job_id_and_reuses_cache(monkeypatch, tmp_path):
    from transcribe import service
    from transcribe.db import store
    _patch_vad(monkeypatch)
    wav, db = _wav(), _db(tmp_path)

    first = service.transcribe(wav, config=_CFG, db_path=db)
    assert not first.cached and first.cues and first.engine_name == "mock"

    second = service.transcribe(wav, config=_CFG, db_path=db)
    assert second.cached and second.job_id == first.job_id
    assert [c["text"] for c in second.cues] == [c["text"] for c in first.cues]

    conn = store.connect(db)
    assert len(store.list_jobs(conn)) == 1  # the second call ran no ASR pass
    conn.close()


def test_default_store_comes_from_config(tmp_path):
    from transcribe.db import store
    target = tmp_path / "x.db"
    assert store.resolve_db_path({"store": {"path": str(target)}}) == target


def test_callers_share_one_db_and_one_bias_index(monkeypatch, tmp_path):
    """A bias term saved once is seen by the helper worker and by a second caller."""
    import json
    import yaml
    from cutdeck import ai_worker
    from transcribe import service
    from transcribe.db import store
    import transcribe.pipeline.run as run_mod
    _patch_vad(monkeypatch)
    db = _db(tmp_path)
    wav = _wav()

    seen = []
    real = run_mod.engine_run.run_engines

    def spy(conn, job_id, job_plan, inputs, device, config):
        seen.append(list(inputs.bias_terms))
        return real(conn, job_id, job_plan, inputs, device, config)

    monkeypatch.setattr(run_mod.engine_run, "run_engines", spy)
    cfg = dict(_CFG, store={"path": str(db)})

    store.init_db(db)
    conn = store.connect(db)
    store.upsert_bias_term(conn, "CutDeck", "brand", "latin", "manual")
    conn.close()

    # caller 1: the service directly
    service.transcribe(wav, config=cfg)
    # caller 2: the helper's subprocess adapter, with its config swapped for ours
    folder = tmp_path / "job"
    folder.mkdir()
    (folder / "job.json").write_text(json.dumps(
        {"kind": "transcribe", "arguments": {"media_path": _wav(2.0)}}), encoding="utf-8")
    monkeypatch.setattr(yaml, "safe_load", lambda *_a, **_k: cfg)
    ai_worker.run(folder)

    conn = store.connect(db)
    assert len(store.list_jobs(conn)) == 2  # both callers wrote the same DB
    conn.close()
    assert not (folder / "transcribe.db").exists()
    assert len(seen) == 2 and seen[0] == seen[1] == ["CutDeck"]
