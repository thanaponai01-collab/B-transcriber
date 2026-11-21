"""Is the broadcaster's TV clock on screen? A per-frame pixel test, no OCR.

The โหนกระแส footage carries the station clock `HH:MM:SS` top-left: white digits with a dark
outline and no box. Scaled to 1280x720 it sits at the same pixels on every episode, 1280x720
and 1920x1080 sources alike (projects/hks/build-plan.md step 0.2). The digits change every second
but the two colons never move, so the test looks only at the four colon dots: each dot's core
must be bright AND the 1 px outline ring two pixels out must be dark. A white wall or a bright
graphic lights the core but not the ring, so it fails.

The dot boxes were read off the 25th/75th-percentile luminance of 77 clock-on frames of the
20261120 footage (30-800 s every 10 s).

    python -m cutdeck.hks_clock <video> [--step 60]
"""

import argparse
import subprocess

import numpy as np

# The crop clock_in_frame takes: x, y, width, height in the frame scaled to 1280x720.
CROP_X, CROP_Y, CROP_W, CROP_H = 80, 20, 200, 60

# Colon dot cores in crop coordinates, inclusive (y0, y1, x0, x1): top and bottom dot of each colon.
DOTS = ((28, 30, 62, 64), (37, 40, 62, 64), (28, 30, 107, 109), (37, 40, 107, 109))
RING_GAP = 2  # the outline ring is the box this many px outside the core

MIN_CORE = 150      # mean luma of the dimmest dot core
MIN_CONTRAST = 40   # core minus ring mean luma, on the weakest dot


def _dot_scores(crop: np.ndarray) -> tuple[float, float]:
    """(dimmest core mean luma, weakest core-minus-ring contrast) over the four dots."""
    luma = crop.astype(np.float32).mean(axis=2)
    cores, contrasts = [], []
    for y0, y1, x0, x1 in DOTS:
        core = luma[y0:y1 + 1, x0:x1 + 1].mean()
        box = luma[y0 - RING_GAP:y1 + RING_GAP + 1, x0 - RING_GAP:x1 + RING_GAP + 1]
        ring = np.concatenate([box[0], box[-1], box[1:-1, 0], box[1:-1, -1]]).mean()
        cores.append(core)
        contrasts.append(core - ring)
    return min(cores), min(contrasts)


def clock_in_frame(crop: np.ndarray) -> bool:
    """True when the clock is on screen. `crop` is the CROP_* region (HxWx3 RGB, 60x200) of the
    frame scaled to 1280x720."""
    if crop.shape != (CROP_H, CROP_W, 3):
        raise ValueError(f"expected a {CROP_H}x{CROP_W}x3 crop, got {crop.shape}")
    core, contrast = _dot_scores(crop)
    return bool(core >= MIN_CORE and contrast >= MIN_CONTRAST)


def _duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, check=True, text=True).stdout
    return float(out)


def grab_crop(path: str, t: float) -> np.ndarray | None:
    """The clock crop of the frame at `t` seconds, or None when ffmpeg returns no frame (past
    the last frame)."""
    vf = f"scale=1280:720,crop={CROP_W}:{CROP_H}:{CROP_X}:{CROP_Y}"
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
         "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True).stdout
    if len(out) != CROP_W * CROP_H * 3:
        return None
    return np.frombuffer(out, np.uint8).reshape(CROP_H, CROP_W, 3)


def clock_samples(path: str, step_s: float = 60.0) -> list[tuple[float, bool]]:
    """(time, clock on) every `step_s` seconds from 0 to the end of the file."""
    samples = []
    for t in np.arange(0.0, _duration(path), step_s):
        crop = grab_crop(path, float(t))
        if crop is not None:
            samples.append((float(t), clock_in_frame(crop)))
    return samples


def clock_fraction(path: str, step_s: float = 60.0) -> float:
    """Share of the samples with the clock on screen (0.0 when there are none)."""
    samples = clock_samples(path, step_s)
    return sum(on for _, on in samples) / len(samples) if samples else 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("video")
    ap.add_argument("--step", type=float, default=60.0, help="seconds between samples")
    args = ap.parse_args()
    samples = clock_samples(args.video, args.step)
    for t, on in samples:
        print(f"{t:9.2f}  {'clock' if on else '-'}")
    share = sum(on for _, on in samples) / len(samples) if samples else 0.0
    print(f"fraction {share:.3f} of {len(samples)} samples")


if __name__ == "__main__":
    main()
