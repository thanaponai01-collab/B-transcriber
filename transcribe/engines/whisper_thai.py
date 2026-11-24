from __future__ import annotations

from transcribe.engines._hf_whisper import HFWhisperEngine
from transcribe.engines.registry import register

_DEFAULT_MODEL = "biodatlab/whisper-th-medium-combined"


@register("whisper_thai")
class WhisperThaiEngine(HFWhisperEngine):
    _engine_name = "whisper_thai"
    _language = "th"
    _log_label = "WhisperThai"

    def __init__(self, model_id: str = _DEFAULT_MODEL, device: str = "cuda"):
        super().__init__(model_id, device)
