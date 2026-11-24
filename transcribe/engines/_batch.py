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
