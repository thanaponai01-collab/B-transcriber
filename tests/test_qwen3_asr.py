"""Qwen3-ASR adapter contract tests (HANDOFF_CEILING_BREAK.md §6/4.1).

Run: python -m pytest tests/test_qwen3_asr.py -v

qwen_asr is never imported here — the model is faked, so these run on any
machine without the (not-yet-installed) qwen-asr package.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

import transcribe.engines.qwen3_asr  # noqa: F401  (registers "qwen3_asr")
from transcribe.contracts import EngineInput


class _Result:
    def __init__(self, text, language=None):
        self.text = text
        self.language = language


class _FakeQwen3ASRModel:
    def __init__(self, results):
        self._results = results
        self.calls = []

    def transcribe(self, audio, context="", language=None):
        self.calls.append({"audio": audio, "context": context, "language": language})
        n = len(audio) if isinstance(audio, list) else 1
        return self._results[:n] if isinstance(audio, list) else [self._results[0]]


def _engine_with(results):
    from transcribe.engines.qwen3_asr import Qwen3ASREngine
    eng = Qwen3ASREngine(device="cpu")
    eng._model = _FakeQwen3ASRModel(results)  # bypass load()
    return eng


def test_registered():
    from transcribe.engines.registry import get_engine
    eng = get_engine("qwen3_asr", device="cpu")
    assert eng.prefers_whole_file is True


def test_transcribe_maps_text_confidence_none_timestamps_not_final():
    res = _engine_with([_Result("สวัสดีครับ ผมอยากจะ share screen ให้ดู", language="Thai")]) \
        .transcribe(EngineInput(audio=np.zeros(16000, dtype=np.float32)))
    assert len(res.tokens) == 1
    assert res.tokens[0].text == "สวัสดีครับ ผมอยากจะ share screen ให้ดู"
    assert res.tokens[0].confidence is None          # never faked
    assert res.tokens[0].script == "mixed"
    assert res.timestamps_final is False             # forced-align path assigns real ms
    assert res.engine_name == "qwen3_asr"
    assert res.raw["language"] == "Thai"


def test_empty_text_yields_no_tokens():
    res = _engine_with([_Result("", language=None)]) \
        .transcribe(EngineInput(audio=np.zeros(16000, dtype=np.float32)))
    assert res.tokens == []


def test_language_hint_maps_iso_code_to_full_name():
    eng = _engine_with([_Result("hello")])
    assert eng._language_arg("th") == "Thai"
    assert eng._language_arg("en") == "English"
    assert eng._language_arg(None) is None
    assert eng._language_arg("fr") == "fr"  # unmapped code passed through verbatim


def test_transcribe_batch_maps_each_input_in_order():
    eng = _engine_with([_Result("อันแรก"), _Result("อันที่สอง")])
    inputs = [
        EngineInput(audio=np.zeros(16000, dtype=np.float32)),
        EngineInput(audio=np.zeros(16000, dtype=np.float32)),
    ]
    results = eng.transcribe_batch(inputs)
    assert [r.tokens[0].text for r in results] == ["อันแรก", "อันที่สอง"]
    assert all(r.timestamps_final is False for r in results)
    assert all(r.tokens[0].confidence is None for r in results)


def test_transcribe_batch_empty_input_yields_empty_output():
    eng = _engine_with([])
    assert eng.transcribe_batch([]) == []


def test_audio_passed_as_array_sample_rate_tuple_when_no_path():
    eng = _engine_with([_Result("hi")])
    audio = np.zeros(16000, dtype=np.float32)
    eng.transcribe(EngineInput(audio=audio))
    call = eng._model.calls[0]
    assert isinstance(call["audio"], tuple)
    assert call["audio"][0] is audio
    assert call["audio"][1] == 16000


def test_audio_path_reused_verbatim_when_given():
    eng = _engine_with([_Result("hi")])
    eng.transcribe(EngineInput(audio_path="clip.wav"))
    assert eng._model.calls[0]["audio"] == "clip.wav"


def test_bias_terms_packed_into_context_slot():
    eng = _engine_with([_Result("hi")])
    eng.transcribe(EngineInput(audio=np.zeros(16000, dtype=np.float32), bias_terms=["ชิบเป๋ง", "คบซ้อน"]))
    assert eng._model.calls[0]["context"] == "ชิบเป๋ง คบซ้อน"


def test_no_bias_terms_yields_empty_context():
    eng = _engine_with([_Result("hi")])
    eng.transcribe(EngineInput(audio=np.zeros(16000, dtype=np.float32)))
    assert eng._model.calls[0]["context"] == ""


def test_unload_clears_model_without_error():
    eng = _engine_with([_Result("x")])
    eng.unload()
    assert eng._model is None
