"""Phase 4 acceptance — Typhoon RT adapter contract + dual-engine reconcile.

Run: python -m pytest tests/test_phase4_typhoon.py -v

NeMo is never imported here — the model is faked, so these run on any machine.
"""

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

import transcribe.engines.typhoon_rt  # noqa: F401  (registers "typhoon_rt")
from transcribe.contracts import EngineInput


class _Hyp:
    def __init__(self, text, timestamp=None):
        self.text = text
        self.timestamp = timestamp


class _FakeNeMo:
    def __init__(self, hyp):
        self._hyp = hyp
    def transcribe(self, audios, timestamps=True):
        return [self._hyp]


def _engine_with(hyp):
    from transcribe.engines.typhoon_rt import TyphoonRTEngine
    eng = TyphoonRTEngine(device="cpu")
    eng._model = _FakeNeMo(hyp)  # bypass load()/NeMo
    return eng


def test_registered():
    from transcribe.engines.registry import get_engine
    eng = get_engine("typhoon_rt", device="cpu")
    assert eng.prefers_whole_file is True


def test_word_timestamps_mapped_verbatim_confidence_none():
    hyp = _Hyp("สวัสดี ครับ", timestamp={"word": [
        {"word": "สวัสดี", "start": 0.0, "end": 0.5},
        {"word": "ครับ", "start": 0.5, "end": 0.9},
    ]})
    res = _engine_with(hyp).transcribe(EngineInput(audio=np.zeros(16000, dtype=np.float32)))
    assert [t.text for t in res.tokens] == ["สวัสดี", "ครับ"]
    assert res.tokens[0].start_ms == 0 and res.tokens[0].end_ms == 500
    assert all(t.confidence is None for t in res.tokens)   # never faked
    assert res.tokens[0].script == "thai"
    assert res.timestamps_final is True


def test_no_timestamps_falls_back_to_even_split():
    hyp = _Hyp("hello world test", timestamp=None)
    audio = np.zeros(16000 * 3, dtype=np.float32)  # 3s
    res = _engine_with(hyp).transcribe(EngineInput(audio=audio))
    assert [t.text for t in res.tokens] == ["hello", "world", "test"]
    assert res.tokens[0].start_ms == 0
    assert res.tokens[-1].end_ms <= 3000 + 1000     # within clip (± one step)
    assert all(t.confidence is None for t in res.tokens)


def test_empty_hypothesis_yields_no_tokens():
    res = _engine_with(_Hyp("", None)).transcribe(EngineInput(audio=np.zeros(16000, dtype=np.float32)))
    assert res.tokens == []


# ── dual-engine reconcile: source_engine ∈ {a, b, both} ───────────────────────

def test_dual_engine_reconcile_source_engines(monkeypatch):
    from transcribe.pipeline import ingest, run as pipeline_run
    from transcribe.db import store

    monkeypatch.setattr(ingest, "_load_silero",
                        lambda: (object(), lambda a, m, **k: [{"start": 0, "end": len(a)}]))

    import soundfile as sf
    t = np.linspace(0, 2.0, 32000, endpoint=False)
    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False); f.close()
    sf.write(f.name, (0.2 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), 16000)

    db = Path(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    store.init_db(db)

    # Two mock engines → a real dual-engine reconcile path.
    cfg = {"engine_a": "mock", "engine_b": "mock", "denoise": False,
           "drop_tokens_over_silence": False}
    tokens = pipeline_run.run_file(f.name, cfg, db)

    assert tokens, "dual-engine run produced no tokens"
    assert all(t["source_engine"] in {"a", "b", "both"} for t in tokens)
