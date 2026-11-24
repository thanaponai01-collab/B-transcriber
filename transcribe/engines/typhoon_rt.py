from __future__ import annotations

import logging

from transcribe.contracts import EngineInput, EngineResult, RecognizedToken, detect_script
from transcribe.engines.base import Engine
from transcribe.engines.registry import register

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "scb10x/typhoon-asr-realtime"


@register("typhoon_rt")
class TyphoonRTEngine(Engine):
    prefers_whole_file = True

    def __init__(self, model_id: str = _DEFAULT_MODEL, device: str = "cuda", **kwargs):
        self._model_id = model_id
        self._device = device
        self._model = None

    def load(self) -> None:
        from nemo.collections.asr.models import ASRModel

        logger.info("Loading Typhoon RT (NeMo): %s", self._model_id)
        self._model = ASRModel.from_pretrained(model_name=self._model_id)
        self._model = self._model.to(self._device).eval()
        logger.info("Typhoon RT loaded on %s", self._device)

    def transcribe(self, inp: EngineInput) -> EngineResult:
        assert self._model is not None, "load() must be called first"
        audio = self._load_array(inp)
        audio_ms = int(len(audio) * 1000 / 16000)

        hyps = self._model.transcribe([audio], timestamps=True)
        hyp = hyps[0] if isinstance(hyps, (list, tuple)) and hyps else hyps
        tokens = _hyp_to_tokens(hyp, audio_ms)

        return EngineResult(
            tokens=tokens,
            engine_name="typhoon_rt",
            timestamps_final=True,
            raw={},
        )

    def _release(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
        logger.info("Typhoon RT unloaded, VRAM freed")


def _word_entries(hyp) -> list[dict]:
    ts = getattr(hyp, "timestamp", None)
    if isinstance(hyp, dict):
        ts = hyp.get("timestamp", ts)
    if isinstance(ts, dict):
        for key in ("word", "words", "segment"):
            if ts.get(key):
                return ts[key]
    return []


def _hyp_text(hyp) -> str:
    if isinstance(hyp, str):
        return hyp
    if isinstance(hyp, dict):
        return hyp.get("text", "")
    return getattr(hyp, "text", "") or ""


def _hyp_to_tokens(hyp, audio_ms: int) -> list[RecognizedToken]:
    entries = _word_entries(hyp)
    tokens: list[RecognizedToken] = []
    if entries:
        for e in entries:
            text = (e.get("word") or e.get("text") or "").strip()
            if not text:
                continue
            start_ms = int(float(e.get("start", 0.0)) * 1000)
            end_ms = int(float(e.get("end", e.get("start", 0.0))) * 1000)
            if end_ms <= start_ms:
                end_ms = start_ms + 1
            tokens.append(RecognizedToken(
                text=text, start_ms=start_ms, end_ms=end_ms,
                confidence=None, script=detect_script(text),
            ))
        return tokens

    words = _hyp_text(hyp).split()
    if not words:
        return []
    step = max(1, audio_ms // len(words))
    for i, w in enumerate(words):
        tokens.append(RecognizedToken(
            text=w, start_ms=i * step, end_ms=(i + 1) * step,
            confidence=None, script=detect_script(w),
        ))
    return tokens
