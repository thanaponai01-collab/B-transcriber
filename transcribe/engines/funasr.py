"""Engine B — Code-switch ASR adapter using FunASR (SeAcoParaformer or SenseVoice).

FunASR's SenseVoiceSmall handles Thai-English code-switching and fits 8GB VRAM.
Model is loaded and unloaded explicitly; never assume it shares VRAM with Engine A.
"""

from __future__ import annotations

import logging

import torch

from transcribe.contracts import EngineInput, EngineResult, RecognizedToken
from transcribe.engines.base import Engine
from transcribe.engines.registry import register

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "FunAudioLLM/SenseVoiceSmall"


def _detect_script(text: str) -> str:
    thai = sum(1 for c in text if "฀" <= c <= "๿")
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    if thai and not latin:
        return "thai"
    if latin and not thai:
        return "latin"
    if thai and latin:
        return "mixed"
    return "other"


@register("funasr")
class FunASREngine(Engine):
    """Wraps FunASR's SenseVoiceSmall for multilingual + code-switch transcription."""

    def __init__(self, model_id: str = _DEFAULT_MODEL, device: str = "cuda"):
        self._model_id = model_id
        self._device = device
        self._model = None

    def load(self) -> None:
        from funasr import AutoModel

        logger.info("Loading FunASR: %s", self._model_id)
        self._model = AutoModel(
            model=self._model_id,
            trust_remote_code=True,
            vad_model="fsmn-vad",
            vad_kwargs={"max_single_segment_time": 30000},
            device=self._device,
        )
        logger.info("FunASR loaded on %s", self._device)

    def transcribe(self, inp: EngineInput) -> EngineResult:
        assert self._model is not None, "load() must be called first"

        result = self._model.generate(
            input=inp.audio_path,
            cache={},
            language="auto",
            use_itn=True,
            batch_size_s=60,
            hotword=" ".join(inp.bias_terms) if inp.bias_terms else None,
        )

        tokens: list[RecognizedToken] = []
        raw_list = result if isinstance(result, list) else [result]
        for item in raw_list:
            sentence_info = item.get("sentence_info", [])
            if sentence_info:
                for seg in sentence_info:
                    text = seg.get("text", "").strip()
                    if not text:
                        continue
                    start_ms = int(seg.get("start", 0))
                    end_ms = int(seg.get("end", start_ms + 500))
                    tokens.append(RecognizedToken(
                        text=text,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        confidence=seg.get("confidence"),
                        script=_detect_script(text),
                    ))
            else:
                # Fallback: treat whole result as one token
                text = item.get("text", "").strip()
                if text:
                    tokens.append(RecognizedToken(
                        text=text, start_ms=0, end_ms=5000,
                        confidence=None, script=_detect_script(text),
                    ))

        return EngineResult(tokens=tokens, engine_name="funasr", raw={"result": raw_list})

    def unload(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("FunASR unloaded, VRAM freed")
