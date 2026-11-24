from __future__ import annotations

import logging
from typing import Optional

import torch

from transcribe.contracts import EngineInput, EngineResult, RecognizedToken, detect_script
from transcribe.engines._batch import run_batched_with_oom_backoff
from transcribe.engines.base import Engine
from transcribe.flywheel.inject import build_prompt_ids

logger = logging.getLogger(__name__)


class HFWhisperEngine(Engine):
    """Base class for HF-`transformers`-backed Whisper adapters.

    Subclasses supply `_engine_name` (the registry name, stamped onto every
    `EngineResult`), `_language` (`None` leaves the `language` key out of
    `generate_kwargs`, so Whisper auto-detects per segment) and `_log_label`.
    """
    _engine_name: str = ""
    _language: Optional[str] = None
    _log_label: str = "HFWhisper"

    def __init__(self, model_id: str, device: str = "cuda"):
        self._model_id = model_id
        self._device = device
        self._model = None
        self._processor = None
        self._pipe = None

    def load(self) -> None:
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline as hf_pipeline

        logger.info("Loading %s: %s", self._log_label, self._model_id)
        self._processor = AutoProcessor.from_pretrained(self._model_id)
        dtype = torch.float16 if self._device != "cpu" else torch.float32
        self._model = AutoModelForSpeechSeq2Seq.from_pretrained(
            self._model_id,
            dtype=dtype,
            low_cpu_mem_usage=True,
        ).to(self._device)
        self._model.eval()
        self._pipe = hf_pipeline(
            "automatic-speech-recognition",
            model=self._model,
            tokenizer=self._processor.tokenizer,
            feature_extractor=self._processor.feature_extractor,
            device=self._device,
        )
        logger.info("%s loaded on %s", self._log_label, self._device)

    def _result_to_tokens(self, result: dict) -> tuple[list[RecognizedToken], list[dict]]:
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
                confidence=None, script=detect_script(text),
            ))

        if not tokens:
            full_text = (result.get("text") or "").strip()
            if full_text:
                tokens.append(RecognizedToken(
                    text=full_text, start_ms=0, end_ms=0,
                    confidence=None, script=detect_script(full_text),
                ))
        return tokens, raw_chunks

    def _generate_kwargs(self, bias_terms: list[str]) -> dict:
        kwargs: dict = {"task": "transcribe", "no_repeat_ngram_size": 3}
        if self._language is not None:
            kwargs["language"] = self._language
        prompt_ids = build_prompt_ids(self._processor, self._device, bias_terms)
        if prompt_ids is not None:
            kwargs["prompt_ids"] = prompt_ids
        return kwargs

    def transcribe(self, inp: EngineInput) -> EngineResult:
        assert self._pipe is not None, "load() must be called first"
        if self._language is not None and inp.language_hint not in (None, self._language):
            raise ValueError(f"{self._engine_name} decodes only {self._language!r}; "
                             f"language {inp.language_hint!r} needs faster_whisper")
        audio = self._load_array(inp)
        generate_kwargs = self._generate_kwargs(inp.bias_terms)

        result = self._pipe(
            {"raw": audio, "sampling_rate": 16000},
            generate_kwargs=generate_kwargs,
            return_timestamps="word",
            chunk_length_s=30,
        )

        tokens, raw_chunks = self._result_to_tokens(result)
        return EngineResult(
            tokens=tokens,
            engine_name=self._engine_name,
            timestamps_final=bool(raw_chunks),
            raw={"chunks": raw_chunks},
        )

    def transcribe_batch(self, inputs: list[EngineInput], batch_size: int = 8) -> list[EngineResult]:
        assert self._pipe is not None, "load() must be called first"
        if not inputs:
            return []

        generate_kwargs = self._generate_kwargs(inputs[0].bias_terms)

        batch = [{"raw": self._load_array(inp), "sampling_rate": 16000} for inp in inputs]
        raw_results = run_batched_with_oom_backoff(
            self._pipe, batch, generate_kwargs, batch_size,
        )

        out: list[EngineResult] = []
        for result in raw_results:
            tokens, raw_chunks = self._result_to_tokens(result)
            out.append(EngineResult(
                tokens=tokens,
                engine_name=self._engine_name,
                timestamps_final=bool(raw_chunks),
                raw={"chunks": raw_chunks},
            ))
        return out

    def _release(self) -> None:
        if self._pipe is not None:
            del self._pipe
            self._pipe = None
        if self._model is not None:
            del self._model
            self._model = None
        if self._processor is not None:
            del self._processor
            self._processor = None
        logger.info("%s unloaded, VRAM freed", self._log_label)
