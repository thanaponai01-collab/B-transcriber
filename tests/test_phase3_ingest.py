"""Phase 3 acceptance — ingest cleanup (single decode, overlap chunks).

Run: python -m pytest tests/test_phase3_ingest.py -v
"""

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.pipeline import ingest


def _synthetic_wav(seconds=3.0, sr=16000):
    import soundfile as sf
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    sig = (0.2 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)
    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    f.close()
    sf.write(f.name, sig, sr)
    return f.name


# ── 3.2 ingest emits overlapping chunks (GAP-4) ───────────────────────────────

def test_materialize_chunks_produce_overlap():
    sr = 16000
    audio = np.zeros(sr * 3, dtype=np.float32)
    # Two speech segments with a 200 ms gap between them.
    segments = [(0, sr), (int(1.2 * sr), 2 * sr)]  # [0–1000ms], [1200–2000ms]
    chunks = ingest._materialize_chunks(audio, sr, segments, overlap_ms=750)
    assert len(chunks) == 2
    # 750 ms overlap on each side closes the 200 ms gap → the two chunks overlap.
    assert chunks[0].end_ms > chunks[1].start_ms, "adjacent chunks must overlap for stitch"


def test_zero_overlap_keeps_chunks_disjoint():
    sr = 16000
    audio = np.zeros(sr * 3, dtype=np.float32)
    segments = [(0, sr), (int(1.2 * sr), 2 * sr)]
    chunks = ingest._materialize_chunks(audio, sr, segments, overlap_ms=0)
    assert chunks[0].end_ms <= chunks[1].start_ms


def test_ingest_returns_the_array_it_used(monkeypatch):
    # With denoise off, ingest must return the exact decoded array (so run.py can
    # feed the engine the same samples the VAD saw).
    monkeypatch.setattr(ingest, "_load_silero",
                        lambda: (object(), lambda a, m, **k: [{"start": 0, "end": len(a)}]))
    path = _synthetic_wav()
    audio, sr = ingest.load_audio(path)
    res = ingest.ingest(path, denoise=False, audio=audio, sr=sr, materialize_chunks=False)
    assert res.audio is audio
    assert res.chunks == []          # whole-file mode skips chunk materialization
    assert len(res.spans) >= 1       # timeline still built


# ── 3.2 pipeline decodes the audio exactly once per job ───────────────────────

def test_pipeline_decodes_audio_once(monkeypatch):
    """load_audio must be called exactly once per run_file (was up to 3×)."""
    import transcribe.engines.mock  # noqa: F401
    from transcribe.pipeline import run as pipeline_run
    from transcribe.db import store

    calls = {"n": 0}
    real_load = ingest.load_audio

    def spy(path):
        calls["n"] += 1
        return real_load(path)

    monkeypatch.setattr(ingest, "load_audio", spy)
    # Deterministic single-segment VAD, no real Silero/denoise.
    monkeypatch.setattr(ingest, "_load_silero",
                        lambda: (object(), lambda a, m, **k: [{"start": 0, "end": len(a)}]))

    path = _synthetic_wav()
    db = Path(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    store.init_db(db)

    # mock engine sets timestamps_final=True → no forced-align reload path.
    cfg = {"engine_a": "mock", "engine_b": "passthrough", "denoise": True,
           "drop_tokens_over_silence": False}
    pipeline_run.run_file(path, cfg, db)

    assert calls["n"] == 1, f"expected 1 decode, got {calls['n']}"
