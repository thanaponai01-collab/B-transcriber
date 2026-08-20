"""Engine B — multilingual Whisper generalist.

The code-switch slot. Where the Thai specialist (Engine A) is strongest on pure-Thai
spans, this generalist is strongest at switch points, because it was trained on many
languages jointly and detects Thai↔English transitions natively rather than via a
language router.

Runs through HuggingFace transformers (same stack as whisper_thai), so it works on
Python 3.13 — unlike FunASR, whose dependency (editdistance) ships no 3.13 wheel.
Language is left on auto-detect; we do NOT force Thai here — forcing the generalist
to Thai would throw away exactly the code-switch capability it is here to provide.

VRAM: large-v3 is ~3 GB in fp16, well under the 8 GB ceiling when loaded ALONE.
Engine A is unloaded before this loads — never assume shared VRAM.

Decode path (model load, pipeline construction, chunk-to-token mapping, batching)
is shared with `whisper_thai.py` via `_hf_whisper.HFWhisperEngine` — this file
supplies only the checkpoint and the auto-detect (unset) language policy.
"""

from __future__ import annotations

from transcribe.engines._hf_whisper import HFWhisperEngine
from transcribe.engines.registry import register

_DEFAULT_MODEL = "openai/whisper-large-v3"


@register("whisper_multi")
class WhisperMultiEngine(HFWhisperEngine):
    """Multilingual Whisper for the generalist / code-switch slot."""

    _engine_name = "whisper_multi"
    _language = None  # auto-detect per segment — the point of this engine
    _log_label = "WhisperMulti"

    def __init__(self, model_id: str = _DEFAULT_MODEL, device: str = "cuda"):
        super().__init__(model_id, device)
