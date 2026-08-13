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
    """Consumes results off a queue (n per call, n=1 for a single-item call) so
    it works correctly whether the adapter makes one batched call across many
    spans/inputs or several independent single-item calls in sequence."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    def transcribe(self, audio, context="", language=None):
        self.calls.append({"audio": audio, "context": context, "language": language})
        n = len(audio) if isinstance(audio, list) else 1
        out, self._results = self._results[:n], self._results[n:]
        return out


def _engine_with(results, **kwargs):
    from transcribe.engines.qwen3_asr import Qwen3ASREngine
    eng = Qwen3ASREngine(device="cpu", **kwargs)
    eng._model = _FakeQwen3ASRModel(results)  # bypass load()
    return eng


def test_registered():
    from transcribe.engines.registry import get_engine
    eng = get_engine("qwen3_asr", device="cpu")
    assert eng.prefers_whole_file is True


def test_transcribe_maps_text_confidence_none_real_timestamps():
    # 1s of silence: VAD finds no speech, falls back to one whole-clip span
    # (0, 1000ms) — a real, derived timestamp, not the old (0, 0) placeholder.
    res = _engine_with([_Result("สวัสดีครับ ผมอยากจะ share screen ให้ดู", language="Thai")]) \
        .transcribe(EngineInput(audio=np.zeros(16000, dtype=np.float32)))
    assert len(res.tokens) == 1
    assert res.tokens[0].text == "สวัสดีครับ ผมอยากจะ share screen ให้ดู"
    assert res.tokens[0].confidence is None          # never faked
    assert res.tokens[0].script == "mixed"
    assert res.tokens[0].start_ms == 0
    assert res.tokens[0].end_ms == 1000
    assert res.timestamps_final is True              # span-derived, no forced-align needed
    assert res.engine_name == "qwen3_asr"
    assert res.raw["language"] == "Thai"


def test_transcribe_multi_span_gets_real_per_span_timestamps(monkeypatch):
    """When VAD finds multiple speech spans, each gets its own token with a
    real span-derived timestamp, via one batched underlying model call."""
    import transcribe.audio.windows as windows

    monkeypatch.setattr(windows, "_vad_speech_spans",
                        lambda audio, th, ms: [(0.0, 1.0), (2.0, 3.5)])
    eng = _engine_with([_Result("อันแรก"), _Result("อันที่สอง")])
    res = eng.transcribe(EngineInput(audio=np.zeros(4 * 16000, dtype=np.float32)))

    assert [t.text for t in res.tokens] == ["อันแรก", "อันที่สอง"]
    assert (res.tokens[0].start_ms, res.tokens[0].end_ms) == (0, 1000)
    assert (res.tokens[1].start_ms, res.tokens[1].end_ms) == (2000, 3500)
    assert res.timestamps_final is True
    # One batched call across both spans, not two separate calls.
    assert len(eng._model.calls) == 1
    assert isinstance(eng._model.calls[0]["audio"], list) and len(eng._model.calls[0]["audio"]) == 2


def test_long_span_is_capped_at_max_span_s(monkeypatch):
    """A single long VAD span must be chopped at max_span_s (default 8.0, NOT
    faster_whisper's 25s _LONG_SPAN_SAFE_S) so this engine's candidates stay
    comparable in scale to Engine A's ~2-5s phrase cues — see TODO_LEDGER.md
    "Qwen3-ASR span-granularity fix". A 20s span must become 3 windows for
    max_span_s=8.0 (0-8, 8-16, 16-20), not stay as one 20s blob."""
    import transcribe.audio.windows as windows

    monkeypatch.setattr(windows, "_vad_speech_spans", lambda audio, th, ms: [(0.0, 20.0)])
    eng = _engine_with([_Result("หนึ่ง"), _Result("สอง"), _Result("สาม")])
    res = eng.transcribe(EngineInput(audio=np.zeros(20 * 16000, dtype=np.float32)))

    assert [(t.start_ms, t.end_ms) for t in res.tokens] == [(0, 8000), (8000, 16000), (16000, 20000)]


def test_max_span_s_is_configurable(monkeypatch):
    import transcribe.audio.windows as windows

    monkeypatch.setattr(windows, "_vad_speech_spans", lambda audio, th, ms: [(0.0, 20.0)])
    eng = _engine_with([_Result("หนึ่ง")], max_span_s=20.0)  # >= span length -> no split
    res = eng.transcribe(EngineInput(audio=np.zeros(20 * 16000, dtype=np.float32)))
    assert len(res.tokens) == 1
    assert (res.tokens[0].start_ms, res.tokens[0].end_ms) == (0, 20000)


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
    assert all(r.timestamps_final is True for r in results)  # each delegates to transcribe()
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
