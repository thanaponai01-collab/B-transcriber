"""Engine A — Thai-specialist Whisper adapter.

Uses a Thai-fine-tuned Whisper model (Thonburian lineage).
Recommended checkpoint: biodatlab/whisper-th-medium-combined (fits 8GB VRAM).
Model is loaded and unloaded explicitly; never assume it shares VRAM with Engine B.
"""

from __future__ import annotations

import logging

import torch

from transcribe.contracts import EngineInput, EngineResult, RecognizedToken, detect_script
from transcribe.engines._batch import run_batched_with_oom_backoff
from transcribe.engines.base import Engine
from transcribe.engines.registry import register
from transcribe.flywheel.inject import build_prompt_ids

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "biodatlab/whisper-th-medium-combined"


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

    def _load_array(self, inp: EngineInput):
        """Use the pre-decoded array when given one (skips a disk round-trip)."""
        if inp.audio is not None:
            return inp.audio
        import librosa
        audio, _ = librosa.load(inp.audio_path, sr=16000, mono=True)
        return audio

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

    def transcribe(self, inp: EngineInput) -> EngineResult:
        assert self._pipe is not None, "load() must be called first"
        audio = self._load_array(inp)

        # no_repeat_ngram_size kills Whisper's repetition loops on non-speech
        # (music/silence/breaths). ponytail: 3-gram block is the standard chunked-
        # path loop guard; compression_ratio_threshold only works on the long-form
        # (non-chunked) algorithm, which we don't use.
        generate_kwargs = {"language": "th", "task": "transcribe", "no_repeat_ngram_size": 3}
        # GAP-5: pack flywheel bias terms into the prompt under a token budget,
        # using THIS engine's tokenizer so the count is real. Non-fatal — a
        # prompt failure must never block transcription.
        prompt_ids = build_prompt_ids(self._processor, self._device, inp.bias_terms)
        if prompt_ids is not None:
            generate_kwargs["prompt_ids"] = prompt_ids

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
            engine_name="whisper_thai",
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

        # no_repeat_ngram_size kills Whisper's repetition loops on non-speech
        # (music/silence/breaths). ponytail: 3-gram block is the standard chunked-
        # path loop guard; compression_ratio_threshold only works on the long-form
        # (non-chunked) algorithm, which we don't use.
        generate_kwargs = {"language": "th", "task": "transcribe", "no_repeat_ngram_size": 3}
        prompt_ids = build_prompt_ids(self._processor, self._device, inputs[0].bias_terms)
        if prompt_ids is not None:
            generate_kwargs["prompt_ids"] = prompt_ids

        batch = [{"raw": self._load_array(inp), "sampling_rate": 16000} for inp in inputs]
        raw_results = run_batched_with_oom_backoff(
            self._pipe, batch, generate_kwargs, batch_size,
        )

        out: list[EngineResult] = []
        for result in raw_results:
            tokens, raw_chunks = self._result_to_tokens(result)
            out.append(EngineResult(
                tokens=tokens,
                engine_name="whisper_thai",
                timestamps_final=bool(raw_chunks),
                raw={"chunks": raw_chunks},
            ))
        return out

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
