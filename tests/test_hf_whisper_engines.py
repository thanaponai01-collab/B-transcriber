"""HF-Whisper adapter contract tests (issue #10).

Covers both `whisper_thai` and `whisper_multi` through the Engine Contract.
`transformers`/`torch` model classes are never touched — the HF pipeline is
faked and assigned directly to `_pipe`, bypassing `load()`, so these run on
any machine without the checkpoints downloaded. Written against the current
(pre-refactor) two-file implementation to pin behaviour before it is lifted
into a shared `_hf_whisper.py`; must stay green, unmodified, after that move.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import transcribe.engines.whisper_thai  # noqa: F401  (registers "whisper_thai")
import transcribe.engines.whisper_multi  # noqa: F401  (registers "whisper_multi")
from transcribe.contracts import EngineInput
from transcribe.engines.whisper_thai import WhisperThaiEngine
from transcribe.engines.whisper_multi import WhisperMultiEngine

# (engine class, registry name, expected pinned language or None for auto-detect)
_ENGINES = [
    (WhisperThaiEngine, "whisper_thai", "th"),
    (WhisperMultiEngine, "whisper_multi", None),
]


class _FakePipe:
    """Consumes results off a queue; results are queued in call order and each
    call consumes as many as the input batch size (1 for a single dict input,
    len(inputs) for a list — matching how transcribe()/transcribe_batch() call
    the real HF pipeline)."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    def __call__(self, inputs, generate_kwargs=None, return_timestamps=None,
                 chunk_length_s=None, batch_size=None):
        self.calls.append({
            "inputs": inputs, "generate_kwargs": generate_kwargs,
            "return_timestamps": return_timestamps, "chunk_length_s": chunk_length_s,
            "batch_size": batch_size,
        })
        n = len(inputs) if isinstance(inputs, list) else 1
        out, self._results = self._results[:n], self._results[n:]
        return out if isinstance(inputs, list) else out[0]


def _engine_with(cls, results, device="cpu"):
    eng = cls(device=device)
    eng._pipe = _FakePipe(results)  # bypass load()
    eng._processor = object()  # never touched unless bias_terms is non-empty
    return eng


def _chunks_result(*word_ts, text=None):
    """Build a fake HF pipeline result with word-level chunks.
    Each entry in word_ts is (text, start_s, end_s)."""
    chunks = [{"text": t, "timestamp": (s, e)} for t, s, e in word_ts]
    return {"text": text or " ".join(t for t, _, _ in word_ts), "chunks": chunks}


@pytest.mark.parametrize("cls,name,_lang", _ENGINES)
def test_registered(cls, name, _lang):
    from transcribe.engines.registry import get_engine
    eng = get_engine(name, device="cpu")
    assert isinstance(eng, cls)


@pytest.mark.parametrize("cls,name,_lang", _ENGINES)
def test_engine_name_matches_registry_name(cls, name, _lang):
    eng = _engine_with(cls, [_chunks_result(("hi", 0.0, 0.5))])
    res = eng.transcribe(EngineInput(audio=np.zeros(16000, dtype=np.float32)))
    assert res.engine_name == name


@pytest.mark.parametrize("cls,name,_lang", _ENGINES)
def test_word_chunks_map_to_tokens_with_ms_bounds_and_script(cls, name, _lang):
    eng = _engine_with(cls, [_chunks_result(("สวัสดี", 0.0, 0.5), ("ครับ", 0.5, 0.9))])
    res = eng.transcribe(EngineInput(audio=np.zeros(16000, dtype=np.float32)))
    assert [t.text for t in res.tokens] == ["สวัสดี", "ครับ"]
    assert (res.tokens[0].start_ms, res.tokens[0].end_ms) == (0, 500)
    assert (res.tokens[1].start_ms, res.tokens[1].end_ms) == (500, 900)
    assert all(t.confidence is None for t in res.tokens)  # never faked
    assert res.tokens[0].script == "thai"
    assert res.timestamps_final is True
    assert res.raw["chunks"]


@pytest.mark.parametrize("cls,name,_lang", _ENGINES)
def test_empty_text_chunks_are_dropped(cls, name, _lang):
    result = {"text": "hi", "chunks": [
        {"text": "", "timestamp": (0.0, 0.1)},
        {"text": "hi", "timestamp": (0.1, 0.4)},
    ]}
    eng = _engine_with(cls, [result])
    res = eng.transcribe(EngineInput(audio=np.zeros(16000, dtype=np.float32)))
    assert [t.text for t in res.tokens] == ["hi"]


@pytest.mark.parametrize("cls,name,_lang", _ENGINES)
def test_no_chunks_falls_back_to_whole_transcript_token(cls, name, _lang):
    result = {"text": "  whole clip text  ", "chunks": []}
    eng = _engine_with(cls, [result])
    res = eng.transcribe(EngineInput(audio=np.zeros(16000, dtype=np.float32)))
    assert len(res.tokens) == 1
    assert res.tokens[0].text == "whole clip text"
    assert (res.tokens[0].start_ms, res.tokens[0].end_ms) == (0, 0)
    assert res.timestamps_final is False


@pytest.mark.parametrize("cls,name,_lang", _ENGINES)
def test_timestamps_final_true_when_chunks_present(cls, name, _lang):
    eng = _engine_with(cls, [_chunks_result(("hi", 0.0, 0.5))])
    res = eng.transcribe(EngineInput(audio=np.zeros(16000, dtype=np.float32)))
    assert res.timestamps_final is True


def test_whisper_thai_pins_language_th():
    eng = _engine_with(WhisperThaiEngine, [_chunks_result(("hi", 0.0, 0.5))])
    eng.transcribe(EngineInput(audio=np.zeros(16000, dtype=np.float32)))
    kwargs = eng._pipe.calls[0]["generate_kwargs"]
    assert kwargs["language"] == "th"


def test_whisper_multi_omits_language_key_entirely():
    eng = _engine_with(WhisperMultiEngine, [_chunks_result(("hi", 0.0, 0.5))])
    eng.transcribe(EngineInput(audio=np.zeros(16000, dtype=np.float32)))
    kwargs = eng._pipe.calls[0]["generate_kwargs"]
    assert "language" not in kwargs  # must be a real absence, not language=None


@pytest.mark.parametrize("cls,name,_lang", _ENGINES)
def test_predecoded_array_used_directly_without_disk_read(cls, name, _lang, monkeypatch):
    import librosa

    def _boom(*a, **k):
        raise AssertionError("librosa.load must not be called when EngineInput.audio is set")
    monkeypatch.setattr(librosa, "load", _boom)

    audio = np.zeros(16000, dtype=np.float32)
    eng = _engine_with(cls, [_chunks_result(("hi", 0.0, 0.5))])
    eng.transcribe(EngineInput(audio=audio))
    call = eng._pipe.calls[0]["inputs"]
    assert call["raw"] is audio
    assert call["sampling_rate"] == 16000


@pytest.mark.parametrize("cls,name,_lang", _ENGINES)
def test_transcribe_batch_returns_results_in_input_order(cls, name, _lang):
    results = [_chunks_result(("อันแรก", 0.0, 0.5)), _chunks_result(("อันที่สอง", 0.0, 0.5))]
    eng = _engine_with(cls, results)
    inputs = [
        EngineInput(audio=np.zeros(16000, dtype=np.float32)),
        EngineInput(audio=np.zeros(16000, dtype=np.float32)),
    ]
    out = eng.transcribe_batch(inputs)
    assert [r.tokens[0].text for r in out] == ["อันแรก", "อันที่สอง"]
    assert all(r.engine_name == name for r in out)


@pytest.mark.parametrize("cls,name,_lang", _ENGINES)
def test_transcribe_batch_empty_input_yields_empty_output(cls, name, _lang):
    eng = _engine_with(cls, [])
    assert eng.transcribe_batch([]) == []


@pytest.mark.parametrize("cls,name,_lang", _ENGINES)
def test_unload_clears_model_without_error(cls, name, _lang):
    eng = _engine_with(cls, [])
    eng._model = object()
    eng.unload()
    assert eng._pipe is None
    assert eng._model is None
    assert eng._processor is None
