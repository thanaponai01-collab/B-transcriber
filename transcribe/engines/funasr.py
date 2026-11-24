from __future__ import annotations

import logging

from transcribe.contracts import EngineInput, EngineResult, RecognizedToken, detect_script
from transcribe.engines.base import Engine
from transcribe.engines.registry import register

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "FunAudioLLM/SenseVoiceSmall"


@register("funasr")
class FunASREngine(Engine):
    def __init__(self, model_id: str = _DEFAULT_MODEL, device: str = "cuda"):
        self._model_id = model_id
        self._device = device
        self._model = None

    def load(self) -> None:
        from funasr import AutoModel

        logger.info("Loading FunASR: %s", self._model_id)
        self._model = AutoModel(
            model=self._model_id,
            hub="hf",
            trust_remote_code=True,
            vad_model="fsmn-vad",
            vad_kwargs={"max_single_segment_time": 30000},
            device=self._device,
        )
        logger.info("FunASR loaded on %s", self._device)

    def transcribe(self, inp: EngineInput) -> EngineResult:
        assert self._model is not None, "load() must be called first"

        audio_path = inp.audio_path
        tmp_path = None
        if audio_path is None and inp.audio is not None:
            import tempfile, soundfile as sf
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name
            sf.write(tmp_path, inp.audio, 16000)
            audio_path = tmp_path

        try:
            result = self._model.generate(
                input=audio_path,
                cache={},
                language="auto",
                use_itn=True,
                batch_size_s=60,
                output_timestamp=True,
                hotword=" ".join(inp.bias_terms) if inp.bias_terms else None,
            )
        finally:
            if tmp_path is not None:
                import os
                os.unlink(tmp_path)

        tokens: list[RecognizedToken] = []
        raw_list = result if isinstance(result, list) else [result]
        for item in raw_list:
            sentence_info = item.get("sentence_info", [])
            words = item.get("words", [])
            word_timestamps = item.get("timestamp", [])
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
                        script=detect_script(text),
                    ))
            elif words and word_timestamps and len(words) == len(word_timestamps):
                for word, (start_ms, end_ms) in zip(words, word_timestamps):
                    word = word.strip()
                    if not word:
                        continue
                    tokens.append(RecognizedToken(
                        text=word,
                        start_ms=int(start_ms),
                        end_ms=int(end_ms),
                        confidence=None,
                        script=detect_script(word),
                    ))
            else:
                text = item.get("text", "").strip()
                if text:
                    end_ms = int(word_timestamps[-1][1]) if word_timestamps else 5000
                    tokens.append(RecognizedToken(
                        text=text, start_ms=0, end_ms=end_ms,
                        confidence=None, script=detect_script(text),
                    ))

        return EngineResult(tokens=tokens, engine_name="funasr", raw={"result": raw_list})

    def _release(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
        logger.info("FunASR unloaded, VRAM freed")
