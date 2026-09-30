"""topic_layout.py — is this frame a news-clip layout or a studio shot? (docs/DESIGN_TOPIC_CUT.md)

The Thai live-news feed the live-news cut targets (โหนกระแส) has two picture layouts that
matter for cutting:

  * ``clip``   footage in a window over the show's saturated-blue frame, with the host in a
               small window; camera switches inside that small window are NOT scene changes.
  * ``studio`` a camera shot of the set; a change of shot here is a real cut point.

A clip frame is one whose top edge and both side edges are mostly that blue frame. Judged
on the frame alone, so it can't see a full-screen footage frame (no blue frame): those come
back ``studio``. Bumpers, ads and logo cards are not detected either; both need more than
one frame to tell apart (measured in tests/test_cutdeck_topic_layout.py).
"""

from __future__ import annotations

import numpy as np

CLIP = "clip"
STUDIO = "studio"

BLUE_FRAME_MIN = 0.4  # blue fraction of the top edge; side edges need half of it

# PIL-style HSV thresholds (hue 0-255) the labelled frames were measured with, in RGB terms
_HUE_LO, _HUE_HI = 169.0, 247.0  # degrees
_SAT_MIN, _VAL_MIN = 150 / 255, 120


def _blue_mask(rgb: np.ndarray) -> np.ndarray:
    a = rgb.astype(np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    hi, lo = a.max(-1), a.min(-1)
    d = np.maximum(hi - lo, 1e-6)
    hue = 240.0 + 60.0 * (r - g) / d  # only meaningful where blue is the max channel
    return (b >= hi) & (hi > _VAL_MIN) & ((hi - lo) / np.maximum(hi, 1e-6) > _SAT_MIN) & (
        hue > _HUE_LO
    ) & (hue < _HUE_HI)


def blue_frame_edges(rgb: np.ndarray) -> tuple[float, float, float]:
    """Blue fraction of the top strip, left strip and right strip of an HxWx3 uint8 frame."""
    h, w = rgb.shape[:2]
    m = _blue_mask(rgb)
    top = m[: max(1, round(h * 10 / 180))]
    sides = slice(round(h * 20 / 180), round(h * 150 / 180))
    k = max(1, round(w * 8 / 320))
    return float(top.mean()), float(m[sides, :k].mean()), float(m[sides, -k:].mean())


def classify_frame(rgb: np.ndarray) -> str:
    top, left, right = blue_frame_edges(rgb)
    if top > BLUE_FRAME_MIN and (left + right) / 2 > BLUE_FRAME_MIN / 2:
        return CLIP
    return STUDIO
