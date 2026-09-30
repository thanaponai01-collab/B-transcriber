"""topic_speakers.py — who is talking: the host, or someone else (docs/DESIGN_TOPIC_CUT.md).

The user marks a stretch where only the host speaks; that stretch becomes the host's voice
profile (ECAPA speaker embeddings, SpeechBrain ``speechbrain/spkrec-ecapa-voxceleb``). Every
1.5 s window of speech is then scored against the profile and smoothed over its neighbours.
This separates the host from the guests; it does not tell the guests apart from each other
and it does not detect two people talking at once.

Loads the model, runs, then frees the GPU (one model at a time, per CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

SR = 16000
WINDOW_S = 1.5
HOP_S = 0.75
SMOOTH_WINDOWS = 4  # neighbours each side whose scores are median-combined
HOST_THRESHOLD = 0.46  # cosine to the host profile
MODEL_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"
MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "spkrec-ecapa-voxceleb"


@dataclass(frozen=True)
class Turn:
    start_s: float
    end_s: float
    is_host: bool


def speech_window_starts(audio: np.ndarray) -> list[float]:
    """Start times (s) of every WINDOW_S window that lies fully inside detected speech."""
    import torch  # noqa: F401  must load before onnxruntime (the VAD) or the process dies on a cuDNN clash
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    spans = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=300, speech_pad_ms=100))
    starts: list[float] = []
    for span in spans:
        s = span["start"] / SR
        end = span["end"] / SR
        while s + WINDOW_S <= end:
            starts.append(s)
            s += HOP_S
    return starts


def embed_windows(audio: np.ndarray, starts: list[float], device: str = "cuda:0") -> np.ndarray:
    """Unit-length speaker embeddings, one row per window start."""
    import gc

    import torch
    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy  # COPY: Windows can't symlink

    model = EncoderClassifier.from_hparams(
        source=MODEL_SOURCE, savedir=str(MODEL_DIR), run_opts={"device": device},
        local_strategy=LocalStrategy.COPY,
    )
    size = int(WINDOW_S * SR)
    rows = []
    with torch.no_grad():
        for i in range(0, len(starts), 64):
            batch = np.stack([audio[int(s * SR):int(s * SR) + size] for s in starts[i:i + 64]])
            rows.append(model.encode_batch(torch.tensor(batch).to(device)).squeeze(1).cpu().numpy())
    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    emb = np.concatenate(rows) if rows else np.zeros((0, 192), np.float32)
    return emb / np.maximum(np.linalg.norm(emb, axis=1, keepdims=True), 1e-9)


def host_scores(starts: np.ndarray, emb: np.ndarray, host_span: tuple[float, float]) -> np.ndarray:
    """Cosine of each window to the host profile, built from windows inside ``host_span``."""
    inside = (starts >= host_span[0]) & (starts + WINDOW_S <= host_span[1])
    if not inside.any():
        raise ValueError(f"no speech windows inside the host sample {host_span}")
    profile = emb[inside].mean(0)
    return emb @ (profile / np.linalg.norm(profile))


def smooth(starts: np.ndarray, scores: np.ndarray, windows: int = SMOOTH_WINDOWS) -> np.ndarray:
    """Median of each score with the scores within ``windows`` hops of it."""
    reach = windows * HOP_S + 1e-6
    return np.array([np.median(scores[np.abs(starts - t) <= reach]) for t in starts])


def turns_from_scores(starts: np.ndarray, scores: np.ndarray,
                      threshold: float = HOST_THRESHOLD) -> list[Turn]:
    """Merge consecutive windows with the same host/other call into turns.

    A change of speaker inside overlapping windows is put at the midpoint of the overlap.
    """
    turns: list[Turn] = []
    for t, score in zip(starts, scores):
        host = bool(score > threshold)
        end = float(t) + WINDOW_S
        if turns and turns[-1].is_host == host and t <= turns[-1].end_s:
            turns[-1] = Turn(turns[-1].start_s, end, host)
        elif turns and t < turns[-1].end_s:  # the call flips inside the overlap
            cut = (float(t) + turns[-1].end_s) / 2
            turns[-1] = Turn(turns[-1].start_s, cut, turns[-1].is_host)
            turns.append(Turn(cut, end, host))
        else:
            turns.append(Turn(float(t), end, host))
    return turns


def host_turns(audio: np.ndarray, host_span: tuple[float, float]) -> list[Turn]:
    """Host / other turns for 16 kHz mono float32 ``audio``, given a host-only stretch (s)."""
    starts = np.array(speech_window_starts(audio))
    scores = host_scores(starts, embed_windows(audio, list(starts)), host_span)
    return turns_from_scores(starts, smooth(starts, scores))
