"""Engine A — Thai-specialist Whisper adapter.

Uses a Thai-fine-tuned Whisper model (Thonburian lineage).
Recommended checkpoint: biodatlab/whisper-th-medium-combined (fits 8GB VRAM).
Model is loaded and unloaded explicitly; never assume it shares VRAM with Engine B.
"""

from __future__ import annotations

import logging

import torch

from transcribe.contracts import EngineInput, EngineResult, RecognizedToken
from transcribe.engines.base import Engine
from transcribe.engines.registry import register

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "biodatlab/whisper-th-medium-combined"


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


@register("whisper_thai")
class WhisperThaiEngine(Engine):
    """Wraps a Thai-fine-tuned Whisper model via HuggingFace transformers."""

    def __init__(self, model_id: str = _DEFAULT_MODEL, device: str = "cuda"):
        self._model_id = model_id
        self._device = device
        self._model = None
        self._processor = None
        self._pipe = None

    def load(self) -> None:
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline as hf_pipeline

        logger.info("Loading WhisperThai: %s", self._model_id)
        self._processor = AutoProcessor.from_pretrained(self._model_id)
        dtype = torch.float16 if self._device != "cpu" else torch.float32
        self._model = AutoModelForSpeechSeq2Seq.from_pretrained(
            self._model_id,
            dtype=dtype,
            low_cpu_mem_usage=True,
        ).to(self._device)
        self._model.eval()
        # Build ASR pipeline for word-timestamp support
        self._pipe = hf_pipeline(
            "automatic-speech-recognition",
            model=self._model,
            tokenizer=self._processor.tokenizer,
            feature_extractor=self._processor.feature_extractor,
            device=self._device,
        )
        logger.info("WhisperThai loaded on %s", self._device)

    def transcribe(self, inp: EngineInput) -> EngineResult:
        assert self._pipe is not None, "load() must be called first"
        import librosa

        audio, _ = librosa.load(inp.audio_path, sr=16000, mono=True)

        # return_timestamps="word" gives per-word chunks when supported;
        # falls back to segment-level chunks on older checkpoints.
        result = self._pipe(
            {"array": audio, "sampling_rate": 16000},
            generate_kwargs={"language": "th", "task": "transcribe"},
            return_timestamps="word",
            chunk_length_s=30,
        )

        tokens: list[RecognizedToken] = []
        raw_chunks = result.get("chunks", [])

        for chunk in raw_chunks:
            text = chunk.get("text", "").strip()
            if not text:
                continue
            ts = chunk.get("timestamp", (None, None)) or (None, None)
            start_ms = int(ts[0] * 1000) if ts[0] is not None else 0
            end_ms = int(ts[1] * 1000) if ts[1] is not None else start_ms + 500
            tokens.append(RecognizedToken(
                text=text, start_ms=start_ms, end_ms=end_ms,
                confidence=None, script=_detect_script(text),
            ))

        if not tokens:
            # Last-resort fallback: whole transcript as one token
            full_text = (result.get("text") or "").strip()
            if full_text:
                tokens.append(RecognizedToken(
                    text=full_text, start_ms=0, end_ms=0,
                    confidence=None, script=_detect_script(full_text),
                ))

        return EngineResult(tokens=tokens, engine_name="whisper_thai", raw={"chunks": raw_chunks})

    def unload(self) -> None:
        if self._pipe is not None:
            del self._pipe
            self._pipe = None
        if self._model is not None:
            del self._model
            self._model = None
        if self._processor is not None:
            del self._processor
            self._processor = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("WhisperThai unloaded, VRAM freed")
