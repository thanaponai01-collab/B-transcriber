"""Cue segmentation — where one subtitle cue ends and the next begins.

Public surface is deliberately two names: `split_cues` (word pieces + policy in,
cues out) and `CuePolicy` (the whole tuning surface). The greedy/DP strategies
behind them are an internal seam, not a caller's concern.

Importable without the GPU stack: nothing here pulls in torch, CTranslate2 or any
engine adapter, so a cue unit test runs on CPU in milliseconds.
"""

from transcribe.cues.policy import (
    CUE_GAP_MS,
    CUE_SPACE_MIN_CHARS,
    CUE_SPACE_MIN_MS,
    CUE_SPLIT_ALGORITHM,
    CUE_TARGET_CHARS,
    CUE_TARGET_MS,
    CuePolicy,
)
from transcribe.cues.split import split_cues

__all__ = [
    "CuePolicy",
    "split_cues",
    "CUE_GAP_MS",
    "CUE_TARGET_MS",
    "CUE_TARGET_CHARS",
    "CUE_SPACE_MIN_CHARS",
    "CUE_SPACE_MIN_MS",
    "CUE_SPLIT_ALGORITHM",
]
