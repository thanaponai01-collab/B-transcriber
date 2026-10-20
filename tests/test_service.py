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


def test_transcribe_skips_cache_when_bias_term_added_or_config_changed(monkeypatch, tmp_path):
    from transcribe import service
    from transcribe.db import store
    _patch_vad(monkeypatch)
    wav, db = _wav(), _db(tmp_path)

    first = service.transcribe(wav, config=_CFG, db_path=db)
    assert not first.cached
    initial_job_id = first.job_id

    # Same config and bias -> cache hit
    hit = service.transcribe(wav, config=_CFG, db_path=db)
    assert hit.cached and hit.job_id == initial_job_id

    # Promoting a bias term causes cache miss and runs a new job
    conn = store.connect(db)
    store.upsert_bias_term(conn, "ใหม่", "brand", "thai", "flywheel", weight=1.5)
    conn.close()

    after_bias = service.transcribe(wav, config=_CFG, db_path=db)
    assert not after_bias.cached
    assert after_bias.job_id != initial_job_id

    # Changing config (e.g. engine setting) causes cache miss and runs a new job
    cfg_modified = dict(_CFG, engines={"faster_whisper": {"model_id": "different"}})
    after_cfg = service.transcribe(wav, config=cfg_modified, db_path=db)
    assert not after_cfg.cached
    assert after_cfg.job_id not in (initial_job_id, after_bias.job_id)


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


def test_glossary_reaches_the_engine_and_skips_cache(monkeypatch, tmp_path):
    from transcribe import service
    import transcribe.pipeline.run as run_mod
    _patch_vad(monkeypatch)
    wav, db = _wav(), _db(tmp_path)
    seen = []
    real = run_mod.engine_run.run_engines

    def spy(conn, job_id, job_plan, inputs, device, config):
        seen.append((list(inputs.bias_terms), dict(inputs.bias_weights)))
        return real(conn, job_id, job_plan, inputs, device, config)

    monkeypatch.setattr(run_mod.engine_run, "run_engines", spy)
    service.transcribe(wav, config=_CFG, db_path=db)
    again = service.transcribe(wav, config=_CFG, db_path=db, glossary=["โหนกระแส", " "])
    assert not again.cached
    assert seen[0][0] == [] and seen[1][0] == ["โหนกระแส"] and seen[1][1]["โหนกระแส"] >= 1.0


def test_review_flags_rank_by_reasons_and_use_decode_stats():
    from transcribe.service import review_flags
    cues = [{"text": "สวัสดีครับ", "start_ms": 0, "end_ms": 2000, "confidence": 0.95},
            {"text": "สวัสดีครับ", "start_ms": 2000, "end_ms": 4000, "confidence": 0.95},
            {"text": "สวัสดีครับ", "start_ms": 4000, "end_ms": 6000, "confidence": 0.5}]
    segs = [{"start_ms": 2000, "end_ms": 4000, "avg_logprob": -1.2,
             "no_speech_prob": 0.1, "compression_ratio": 1.0},
            {"start_ms": 4000, "end_ms": 6000, "avg_logprob": -1.2,
             "no_speech_prob": 0.5, "compression_ratio": 1.0}]
    flags = review_flags(cues, segs)
    assert [f["cue_index"] for f in flags] == [2, 1]  # cue 0 clean, not flagged
    assert "low decode log-probability" in flags[1]["reasons"]


def test_transcript_reports_uncovered_speech(monkeypatch, tmp_path):
    from transcribe import service
    _patch_vad(monkeypatch)
    t = service.transcribe(_wav(6.0), config=_CFG, db_path=_db(tmp_path))
    # mock cues end at 2 s; VAD says speech runs 0-6 s -> the tail is reported, never filled
    assert any(g["start_ms"] >= 1900 and g["end_ms"] >= 5900 for g in t.coverage_gaps)


def test_hotwords_channel_ranks_by_weight_and_rejects_bad_value():
    import pytest
    import transcribe.engines.faster_whisper as fw
    from transcribe.contracts import EngineInput
    inp = EngineInput(bias_terms=["a", "b", "c"], bias_weights={"b": 3.0, "c": 2.0})
    assert fw.FasterWhisperEngine._build_hotwords(inp) == "b c a"
    with pytest.raises(ValueError):
        fw.FasterWhisperEngine(bias_channel="nope")
