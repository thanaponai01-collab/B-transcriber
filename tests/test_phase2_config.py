"""Phase 2 acceptance — dead config reconnected.

Run: python -m pytest tests/test_phase2_config.py -v
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── 2.1 VAD config values must reach get_speech_timestamps ────────────────────

def test_vad_config_reaches_silero(monkeypatch):
    from transcribe.pipeline import ingest

    captured = {}

    def fake_get_speech_ts(audio, model, **kwargs):
        captured.update(kwargs)
        return [{"start": 0, "end": 100}]

    # Mock the model + fn so no real Silero (or network) is touched.
    monkeypatch.setattr(ingest, "_load_silero", lambda: (object(), fake_get_speech_ts))

    audio = np.zeros(16000, dtype=np.float32)
    ingest._vad_chunks(audio, 16000, threshold=0.35, min_speech_ms=250, min_silence_ms=500)

    assert captured["threshold"] == 0.35
    assert captured["min_speech_duration_ms"] == 250
    assert captured["min_silence_duration_ms"] == 500


# ── 2.2 Flywheel constants threaded through signatures ────────────────────────

def test_build_prompt_ids_accepts_budget():
    import inspect
    from transcribe.flywheel.inject import build_prompt_ids
    assert "budget_tokens" in inspect.signature(build_prompt_ids).parameters


def test_update_bias_index_reads_config_thresholds():
    import inspect
    from transcribe.flywheel.biasindex import update_bias_index
    params = inspect.signature(update_bias_index).parameters
    assert "min_occurrences" in params
    assert "stale_engine_weight" in params


def test_build_prompt_respects_budget():
    from transcribe.flywheel.inject import build_prompt, BiasTerm
    terms = [BiasTerm("alpha", 5.0), BiasTerm("beta", 1.0), BiasTerm("gamma", 0.1)]
    # budget 1 token → only the highest-weight term fits (each ~1 token here).
    out = build_prompt(terms, budget_tokens=1)
    assert out == "alpha"


# ── 2.3 Per-engine config → kwargs, engine swap is YAML-only ──────────────────

def test_mock_engine_tolerates_config_kwargs():
    import transcribe.engines.mock  # noqa: F401  (lazy register)
    from transcribe.engines.registry import get_engine
    # Arbitrary per-engine config keys must not break construction.
    eng = get_engine("mock", device="cuda", compute_type="int8_float16", beam_size=9)
    eng.load()
    assert eng is not None


def test_faster_whisper_construct_from_config_without_gpu():
    # Constructing (no load()) must accept the full config block — proves a
    # compute_type / model / beam swap is a pure YAML edit.
    import transcribe.engines.faster_whisper  # noqa: F401
    from transcribe.engines.registry import get_engine
    eng = get_engine(
        "faster_whisper",
        device="cpu",
        model_id="models/some-other-ct2",
        compute_type="int8_float16",
        beam_size=3,
        cue_gap_ms=500,
        cue_max_ms=6000,
        bias_prompt_budget=120,
    )
    assert eng._model_id == "models/some-other-ct2"
    assert eng._compute_type == "int8_float16"
    assert eng._beam_size == 3
    assert eng._cue_gap_ms == 500
    assert eng._bias_prompt_budget == 120
