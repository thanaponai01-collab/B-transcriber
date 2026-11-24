from __future__ import annotations

import logging

import torch

from transcribe.audio import WindowPolicy, speech_windows
from transcribe.contracts import EngineInput, EngineResult, RecognizedToken, detect_script
from transcribe.engines.base import Engine
from transcribe.engines.registry import register
from transcribe.flywheel.inject import BiasTerm, build_prompt

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "Qwen/Qwen3-ASR-1.7B"
_SAMPLE_RATE = 16000

_LANGUAGE_NAMES = {"th": "Thai", "en": "English"}


@register("qwen3_asr")
class Qwen3ASREngine(Engine):
    prefers_whole_file = True

    def __init__(
        self,
        model_id: str = _DEFAULT_MODEL,
        device: str = "cuda",
        max_inference_batch_size: int = 8,
        max_new_tokens: int = 256,
        vad_threshold: float = 0.35,
        vad_min_silence_ms: int = 500,
        max_span_s: float = 8.0,
    ):
        self._model_id = model_id
        self._device = device
        self._max_inference_batch_size = max_inference_batch_size
        self._max_new_tokens = max_new_tokens
        self._window_policy = WindowPolicy(
            vad_threshold=vad_threshold,
            vad_min_silence_ms=vad_min_silence_ms,
            merge_max_gap_s=None,
            max_span_s=max_span_s,
            overlap_s=0.0,
            whole_clip_on_silence=True,
        )
        self._model = None

    def load(self) -> None:
        from qwen_asr import Qwen3ASRModel

        logger.info("Loading Qwen3-ASR: %s", self._model_id)
        dtype = torch.bfloat16 if self._device != "cpu" else torch.float32
        self._model = Qwen3ASRModel.from_pretrained(
            self._model_id,
            dtype=dtype,
            device_map=self._device,
            max_inference_batch_size=self._max_inference_batch_size,
            max_new_tokens=self._max_new_tokens,
        )
        logger.info("Qwen3-ASR loaded on %s", self._device)

    def _audio_arg(self, inp: EngineInput):
        if inp.audio_path is not None:
            return inp.audio_path
        return (inp.audio, _SAMPLE_RATE)

    def _language_arg(self, language_hint: str | None):
        if not language_hint or language_hint == "auto":
            return None
        return _LANGUAGE_NAMES.get(language_hint, language_hint)

    def _context_arg(self, bias_terms: list[str]) -> str:
        if not bias_terms:
            return ""
        return build_prompt([BiasTerm(t) for t in bias_terms])

    def _result_to_tokens(self, text: str) -> list[RecognizedToken]:
        text = (text or "").strip()
        if not text:
            return []
        return [RecognizedToken(
            text=text, start_ms=0, end_ms=0, confidence=None, script=detect_script(text),
        )]

    def _speech_spans_s(self, audio, speech_spans=()) -> list[tuple[float, float]]:
        if speech_spans:
            wins = speech_windows(audio, self._window_policy, speech_spans=speech_spans)
        else:
            wins = speech_windows(audio, self._window_policy)
        return [(w.start_s, w.end_s) for w in wins]

    def transcribe(self, inp: EngineInput) -> EngineResult:
        assert self._model is not None, "load() must be called first"
        context = self._context_arg(inp.bias_terms)
        language = self._language_arg(inp.language_hint)

        if inp.audio is None:
            results = self._model.transcribe(audio=self._audio_arg(inp), context=context, language=language)
            result = results[0]
            text = getattr(result, "text", "") or ""
            return EngineResult(
                tokens=self._result_to_tokens(text),
                engine_name="qwen3_asr",
                timestamps_final=False,
                raw={"language": getattr(result, "language", None), "text": text},
            )

        spans = self._speech_spans_s(inp.audio, inp.speech_spans)
        whole_clip = len(spans) == 1 and spans[0] == (0.0, len(inp.audio) / _SAMPLE_RATE)
        slices = [inp.audio] if whole_clip else [
            inp.audio[int(s * _SAMPLE_RATE):int(e * _SAMPLE_RATE)] for s, e in spans
        ]

        if len(slices) == 1:
            results = self._model.transcribe(audio=(slices[0], _SAMPLE_RATE), context=context, language=language)
        else:
            results = self._model.transcribe(
                audio=[(a, _SAMPLE_RATE) for a in slices],
                context=[context] * len(slices),
                language=[language] * len(slices),
            )

        tokens: list[RecognizedToken] = []
        texts: list[str] = []
        languages: list[str] = []
        for (start_s, end_s), r in zip(spans, results):
            text = (getattr(r, "text", "") or "").strip()
            texts.append(text)
            languages.append(getattr(r, "language", None))
            if not text:
                continue
            tokens.append(RecognizedToken(
                text=text, start_ms=int(start_s * 1000), end_ms=int(end_s * 1000),
                confidence=None, script=detect_script(text),
            ))
        return EngineResult(
            tokens=tokens,
            engine_name="qwen3_asr",
            timestamps_final=True,
            raw={"language": languages[0] if languages else None, "text": " ".join(t for t in texts if t)},
        )

    def transcribe_batch(self, inputs: list[EngineInput], batch_size: int = 8) -> list[EngineResult]:
        assert self._model is not None, "load() must be called first"
        return [self.transcribe(inp) for inp in inputs]

    def _release(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
        logger.info("Qwen3-ASR unloaded, VRAM freed")
