from __future__ import annotations

from transcribe.engines._hf_whisper import HFWhisperEngine
from transcribe.engines.registry import register

_DEFAULT_MODEL = "openai/whisper-large-v3"


@register("whisper_multi")
class WhisperMultiEngine(HFWhisperEngine):
    _engine_name = "whisper_multi"
    _language = None
    _log_label = "WhisperMulti"

    def __init__(self, model_id: str = _DEFAULT_MODEL, device: str = "cuda"):
        super().__init__(model_id, device)
