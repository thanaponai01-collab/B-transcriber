"""Shared OOM-safe batching helper for HF ASR pipeline engines.

VAD chunks vary widely in length, and the HF pipeline pads every item in a
batch to the longest one in that batch, so memory cost is unpredictable from
batch_size alone. On a CUDA OOM, halve batch_size and retry rather than
losing the whole job.
"""

from __future__ import annotations

import logging

import torch

logger = logging.getLogger(__name__)


def run_batched_with_oom_backoff(
    pipe,
    batch: list[dict],
    generate_kwargs: dict,
    batch_size: int,
) -> list[dict]:
    """Run `pipe` over all of `batch`, retrying with a smaller batch_size on
    CUDA OOM instead of failing the whole job."""
    bs = max(1, min(batch_size, len(batch)))
    while True:
        try:
            # The HF ASR pipeline pops keys ("raw"/"sampling_rate") off each input
            # dict during preprocess. On an OOM-triggered retry the originals would
            # be missing those keys, so hand every attempt fresh dict wrappers
            # (the audio array is shared read-only).
            return pipe(
                [dict(item) for item in batch],
                generate_kwargs=generate_kwargs,
                return_timestamps="word",
                chunk_length_s=30,
                batch_size=bs,
            )
        except torch.OutOfMemoryError:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if bs == 1:
                raise
            next_bs = max(1, bs // 2)
            logger.warning("CUDA OOM at batch_size=%d, retrying at %d", bs, next_bs)
            bs = next_bs
