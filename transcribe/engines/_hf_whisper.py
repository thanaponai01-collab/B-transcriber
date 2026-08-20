"""Shared HuggingFace-Whisper decode path (internal to `engines/`, issue #10).

`whisper_thai.py` (Thai specialist) and `whisper_multi.py` (multilingual
generalist) drive the same stack — `transformers`
`AutoModelForSpeechSeq2Seq` + `AutoProcessor`, an `automatic-speech-
recognition` pipeline with `return_timestamps="word"`, the shared `_batch.py`
OOM-backoff helper — and differ only in checkpoint, `engine_name`, and
whether `language` is pinned in `generate_kwargs`. `HFWhisperEngine` here
holds that shared implementation as a base class; it is never registered as
an engine itself and is reached only through the two adapters that subclass
it (same role `_batch.py` already plays for both).

Not an Engine Contract breach: CLAUDE.md forbids one engine adapter
importing another, not both subclassing a shared internal base.
"""

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

    Subclasses supply the three real differences as class attributes:
    `_engine_name` (the registry name, stamped onto every `EngineResult`),
    `_language` (`None` ⇒ the `language` key is left out of
    `generate_kwargs` entirely so Whisper auto-detects per segment — a
    genuine absence, not `language=None` passed through), and `_log_label`
    (cosmetic, for load/unload log lines). `_DEFAULT_MODEL` stays on each
    adapter module, not here, since a subclass's `__init__` supplies it as
    the `model_id` default.
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
        # Build ASR pipeline for word-timestamp support
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
            # Last-resort fallback: whole transcript as one token
            full_text = (result.get("text") or "").strip()
            if full_text:
                tokens.append(RecognizedToken(
                    text=full_text, start_ms=0, end_ms=0,
                    confidence=None, script=detect_script(full_text),
                ))
        return tokens, raw_chunks

    def _generate_kwargs(self, bias_terms: list[str]) -> dict:
        # no_repeat_ngram_size kills Whisper's repetition loops on non-speech
        # (music/silence/breaths). ponytail: 3-gram block is the standard chunked-
        # path loop guard; compression_ratio_threshold only works on the long-form
        # (non-chunked) algorithm, which we don't use.
        kwargs: dict = {"task": "transcribe", "no_repeat_ngram_size": 3}
        if self._language is not None:
            kwargs["language"] = self._language
        # GAP-5: pack flywheel bias terms into the prompt under a token budget,
        # using THIS engine's tokenizer so the count is real. Non-fatal — a
        # prompt failure must never block transcription.
        prompt_ids = build_prompt_ids(self._processor, self._device, bias_terms)
        if prompt_ids is not None:
            kwargs["prompt_ids"] = prompt_ids
        return kwargs

    def transcribe(self, inp: EngineInput) -> EngineResult:
        assert self._pipe is not None, "load() must be called first"
        audio = self._load_array(inp)
        generate_kwargs = self._generate_kwargs(inp.bias_terms)

        # return_timestamps="word" gives per-word chunks when supported;
        # falls back to segment-level chunks on older checkpoints.
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
        """Batched GPU inference — one or few forward passes instead of len(inputs).

        Bias terms are assumed identical across the batch (true for every caller
        in this pipeline, which reuses the same flywheel bias_terms per job); the
        prompt is built once from the first input rather than per-chunk.
        """
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
