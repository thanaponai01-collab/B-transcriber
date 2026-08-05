"""HANDOFF_ONE_ENGINE.md §6 (Phase D) — N-best self-ensemble.

Pseudo-Engine-B is a second decode pass through Engine A's own already-loaded
residency, fed through the *existing* align_hyp -> reconcile path as if it
were a real Engine B. Three things must be proven, none of which the
reconciler/align_hyp unit tests already cover:

1. `FasterWhisperEngine.transcribe()` actually threads temperature/beam_size
   overrides into the decode call (and leaves them alone when not given — the
   production default must stay byte-identical). Probing this for real
   (2026-08-05) found temperature ALONE is a no-op through
   BatchedInferencePipeline (beam search is deterministic; CTranslate2's
   sampling_temperature has no effect while beam_size>1) — beam_size=1 is
   what actually produces a decorrelated second hypothesis. See
   faster_whisper.py's _transcribe_batched docstring.
2. `pipeline.run.run_file()` never instantiates a second model when
   self_ensemble.enabled is set — it decodes hypothesis 2 from the same
   Engine A instance, before unload(), and the resulting tokens reach
   align_hyp/reconcile like a genuine A/B pair.
"""

import tempfile
from pathlib import Path

import numpy as np

from transcribe.pipeline import ingest


# ── 1. Temperature threading (no real model — mirrors
#    test_faster_whisper_truncation_recovery.py's eng._decode fake pattern) ──

def test_transcribe_threads_temperature_override_into_decode():
    from transcribe.engines import faster_whisper as fw
    from transcribe.contracts import EngineInput

    eng = fw.FasterWhisperEngine()
    eng._model = object()  # satisfy "load() must be called first"; _decode is faked below

    class _FakeWord:
        def __init__(self, word, start, end, probability=0.9):
            self.word, self.start, self.end, self.probability = word, start, end, probability

    class _FakeSegment:
        def __init__(self, words):
            self.words = words

    captured = []

    def fake_decode(audio_arr, clip_timestamps, vad_filter, common_kwargs, bs):
        captured.append((common_kwargs.get("temperature"), common_kwargs["beam_size"]))
        return [_FakeSegment([_FakeWord(" hello", 0.0, 1.0)])], bs

    eng._decode = fake_decode
    eng._vad_speech_spans = None  # unused; _transcribe_batched calls the module function

    orig_vad = fw._vad_speech_spans
    fw._vad_speech_spans = lambda audio, threshold, min_silence_ms: [(0.0, 1.0)]
    try:
        audio = np.zeros(fw._SR, dtype=np.float32)
        inp = EngineInput(audio=audio)

        eng.transcribe(inp)                                  # no override -> production default
        eng.transcribe(inp, temperature=0.0)                  # beam_size still defaults to self._beam_size (5)
        eng.transcribe(inp, temperature=0.2, beam_size=1)      # self-ensemble hypothesis B (greedy)
    finally:
        fw._vad_speech_spans = orig_vad

    assert captured == [(None, eng._beam_size), (0.0, eng._beam_size), (0.2, 1)], (
        "temperature=None must omit the key (production default preserved); "
        "beam_size=None must fall back to self._beam_size; explicit overrides "
        "must reach the decode call unchanged"
    )


# ── 2. run.py wiring: no second model load, both hypotheses reach reconcile ──

def _synthetic_wav(seconds=1.0, sr=16000):
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


def test_self_ensemble_never_loads_a_second_model_and_reaches_reconcile(monkeypatch):
    from transcribe.contracts import EngineInput, EngineResult, RecognizedToken
    from transcribe.engines.base import Engine
    from transcribe.engines.registry import register
    from transcribe.db import store

    calls = []  # (temperature, beam_size) Engine A's transcribe() was actually called with

    @register("se_test_engine")
    class _SelfEnsembleTestEngine(Engine):
        prefers_whole_file = True

        def __init__(self, **kwargs):
            self._loaded = False

        def load(self):
            self._loaded = True

        def transcribe(self, inp: EngineInput, temperature=None, beam_size=None) -> EngineResult:
            assert self._loaded, "load() must be called before transcribe()"
            calls.append((temperature, beam_size))
            # Disagreeing text per hypothesis so the reconciler has a real
            # disagreement to resolve, not a same-text agreement short-circuit.
            text = "hello" if temperature in (None, 0.0) else "halo"
            return EngineResult(
                tokens=[RecognizedToken(text, 0, 500, 0.9, "latin")],
                engine_name="se_test_engine",
                timestamps_final=True,
                raw={"words": [{"text": text, "start_ms": 0, "end_ms": 500}]},
            )

        def unload(self):
            self._loaded = False

    path = _synthetic_wav()
    db = _tmp_db()
    cfg = {
        "engine_a": "se_test_engine",
        # Deliberately an UNREGISTERED name: if the self-ensemble path ever
        # regressed into calling get_engine(engine_b_name), this would raise
        # KeyError instead of silently loading a real second engine.
        "engine_b": "self_ensemble",
        "denoise": False,
        "drop_tokens_over_silence": False,
        "self_ensemble": {"enabled": True, "temperature_a": 0.0, "temperature_b": 0.2},
    }

    monkeypatch.setattr(ingest, "_load_silero",
                        lambda: (object(), lambda a, m, **k: [{"start": 0, "end": len(a)}]))
    store.init_db(db)
    from transcribe.pipeline import run as pipeline_run
    tokens = pipeline_run.run_file(path, cfg, db)

    assert calls == [(0.0, None), (0.2, 1)], (
        f"expected hypothesis A at (temperature_a, beam_size_a) and hypothesis B "
        f"at (temperature_b, beam_size_b=1 default), got {calls!r}"
    )
    assert len(tokens) > 0

    conn = store.connect(db)
    job = store.list_jobs(conn)[0]
    assert job.status == "done"

    cached_a = store.get_engine_result(conn, job.id, "a")
    cached_b = store.get_engine_result(conn, job.id, "b")
    assert cached_a is not None and cached_b is not None
    assert cached_a.engine_name == "se_test_engine"
    # The pseudo-B result is labelled with config's engine_b string (record-
    # keeping only) but was never a real "self_ensemble" engine instance.
    assert cached_b.engine_name == "self_ensemble"

    import json
    a_texts = [t["text"] for t in json.loads(cached_a.tokens_json)]
    b_texts = [t["text"] for t in json.loads(cached_b.tokens_json)]
    assert a_texts == ["hello"]
    assert b_texts == ["halo"]

    # The reconciler picked one of the two disagreeing candidates (never
    # invented text) — proves both hypotheses actually reached align_hyp/
    # reconcile as an A/B pair, not two independent solo slots.
    assert tokens[0]["text"] in {"hello", "halo"}
    conn.close()


def test_self_ensemble_resume_mid_phase_redecodes_hypothesis_b(monkeypatch):
    """A crash landing exactly between engine_a_done and engine_b_done leaves
    hypothesis A cached but hypothesis B (never separately persisted until the
    "b" phase completes) uncomputed. The resume path must reload Engine A once
    and redecode B — not silently emit result_b_tokens=None. Also proves job
    identity is self-consistent even when config's raw engine_b string doesn't
    say "self_ensemble" (run.py derives it, not the caller)."""
    from transcribe.contracts import EngineInput, EngineResult, RecognizedToken
    from transcribe.engines.base import Engine
    from transcribe.engines.registry import register
    from transcribe.db import store

    calls = []

    @register("se_resume_test_engine")
    class _SelfEnsembleResumeTestEngine(Engine):
        prefers_whole_file = True

        def __init__(self, **kwargs):
            self._loaded = False

        def load(self):
            self._loaded = True

        def transcribe(self, inp: EngineInput, temperature=None, beam_size=None) -> EngineResult:
            assert self._loaded, "load() must be called before transcribe()"
            calls.append((temperature, beam_size))
            text = "hello" if temperature in (None, 0.0) else "halo"
            return EngineResult(
                tokens=[RecognizedToken(text, 0, 500, 0.9, "latin")],
                engine_name="se_resume_test_engine",
                timestamps_final=True,
                raw={"words": [{"text": text, "start_ms": 0, "end_ms": 500}]},
            )

        def unload(self):
            self._loaded = False

    path = _synthetic_wav()
    db = _tmp_db()
    cfg = {
        "engine_a": "se_resume_test_engine",
        # Deliberately mismatched: run.py must derive the "self_ensemble" job
        # identity itself, not trust this string (see TODO_LEDGER.md's Phase D
        # entry — the harness CLI used to be the only thing that set this).
        "engine_b": "passthrough",
        "denoise": False,
        "drop_tokens_over_silence": False,
        "self_ensemble": {"enabled": True, "temperature_a": 0.0, "temperature_b": 0.2, "beam_size_b": 1},
    }
    monkeypatch.setattr(ingest, "_load_silero",
                        lambda: (object(), lambda a, m, **k: [{"start": 0, "end": len(a)}]))
    store.init_db(db)
    from transcribe.pipeline import run as pipeline_run
    pipeline_run.run_file(path, cfg, db)

    conn = store.connect(db)
    job = store.list_jobs(conn)[0]
    assert job.job_phase == "written"
    assert job.engine_b == "self_ensemble", (
        "job identity must reflect self-ensemble regardless of config's raw engine_b string"
    )

    # Simulate a crash landing exactly between engine_a_done and engine_b_done.
    store.update_job_phase(conn, job.id, "engine_a_done")
    store.update_job_status(conn, job.id, "failed")
    conn.close()

    calls.clear()
    tokens = pipeline_run.run_file(path, cfg, db)

    # Hypothesis A must NOT redecode (cached from the first run); hypothesis B
    # (never separately persisted until the "b" phase) MUST redecode exactly once.
    assert calls == [(0.2, 1)], f"expected exactly one redecode call for hypothesis B, got {calls!r}"
    assert len(tokens) > 0

    conn = store.connect(db)
    jobs = store.list_jobs(conn)
    assert len(jobs) == 1, "resume must reuse the failed job, not create a new one"
    assert jobs[0].id == job.id
    assert jobs[0].status == "done"
    assert jobs[0].job_phase == "written"

    import json
    cached_b = store.get_engine_result(conn, jobs[0].id, "b")
    assert cached_b is not None
    assert json.loads(cached_b.tokens_json)[0]["text"] == "halo"
    conn.close()


def test_self_ensemble_rejects_a_chunk_engine_a(monkeypatch):
    """The pseudo-B pass is one whole-file residency decoded twice — a chunk
    engine has no per-chunk restitch path for a second hypothesis, so this
    must fail loudly (not silently ignore self_ensemble.enabled)."""
    import transcribe.engines.mock  # noqa: F401 — registers "mock" (prefers_whole_file=False)
    from transcribe.db import store

    path = _synthetic_wav()
    db = _tmp_db()
    cfg = {
        "engine_a": "mock",
        "engine_b": "self_ensemble",
        "denoise": False,
        "drop_tokens_over_silence": False,
        "self_ensemble": {"enabled": True},
    }
    monkeypatch.setattr(ingest, "_load_silero",
                        lambda: (object(), lambda a, m, **k: [{"start": 0, "end": len(a)}]))
    store.init_db(db)
    from transcribe.pipeline import run as pipeline_run

    import pytest
    with pytest.raises(ValueError, match="self_ensemble.enabled requires a whole-file"):
        pipeline_run.run_file(path, cfg, db)
