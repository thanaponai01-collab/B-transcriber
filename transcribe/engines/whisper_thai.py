"""Engine A — Thai-specialist Whisper adapter.

Uses a Thai-fine-tuned Whisper model (Thonburian lineage).
Recommended checkpoint: biodatlab/whisper-th-medium-combined (fits 8GB VRAM).
Model is loaded and unloaded explicitly; never assume it shares VRAM with Engine B.

Decode path (model load, pipeline construction, chunk-to-token mapping, batching)
is shared with `whisper_multi.py` via `_hf_whisper.HFWhisperEngine` — this file
supplies only the checkpoint and the `language="th"` pin.
"""

from __future__ import annotations

from transcribe.engines._hf_whisper import HFWhisperEngine
from transcribe.engines.registry import register

_DEFAULT_MODEL = "biodatlab/whisper-th-medium-combined"


@register("whisper_thai")
class WhisperThaiEngine(HFWhisperEngine):
    """Wraps a Thai-fine-tuned Whisper model via HuggingFace transformers."""

    _engine_name = "whisper_thai"
    _language = "th"
    _log_label = "WhisperThai"

    def __init__(self, model_id: str = _DEFAULT_MODEL, device: str = "cuda"):
        super().__init__(model_id, device)
