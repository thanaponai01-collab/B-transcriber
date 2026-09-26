"""Read back what the Transform panel wrote, from two saved .prproj files (before and after).

For every Motion clip present in both saves it prints the fields that changed, where the anchor
now sits on the visible (cropped) picture, and how far the rendered picture moved. An anchor edit
must move nothing (drift 0 px); a Position or Scale edit must move it by exactly what was asked.
The render model is the panel's (uxp/cutdeck/transform/geometry.js):

    seq point = Position + R(rotation) . (Scale * (source point - Anchor))

Position is in sequence px, Anchor in source px, rotation positive = clockwise on screen.
This checks the panel's written values against that model; whether Premiere draws by the same
model is the Program Monitor's job (nothing may jump when the anchor changes).

    python -m cutdeck.prproj_anchor_check before.prproj after.prproj --sequence "Sequence 04"
"""

from __future__ import annotations

import argparse
import math
import sys

from cutdeck.prproj_reader import read_project

TARGETS = {
    (0, 0): "top-left", (0.5, 0): "top", (1, 0): "top-right",
    (0, 0.5): "left", (0.5, 0.5): "center", (1, 0.5): "right",
    (0, 1): "bottom-left", (0.5, 1): "bottom", (1, 1): "bottom-right",
}


def _value(params: dict, name: str, default=None):
    p = params.get(name)
    return p["value"] if p else default


def motion_model(clip: dict, seq_frame: list[int]) -> dict | None:
    """The clip's Motion in the render model, or None when it has none, is keyframed, or its
    source frame is unknown."""
    fx = next((e for e in clip["effects"] if e["match_name"] == "AE.ADBE Motion"), None)
    src = clip.get("source_frame")
    if not src:
        return None
    # Premiere 26 saves nothing for a Motion at its defaults, so no effect = all defaults.
    p = fx["params"] if fx else {"position": {"value": [0.5, 0.5]}, "anchor": {"value": [0.5, 0.5]}}
    if not fx and any(e["match_name"] == "AE.ADBE Text" for e in clip["effects"]):
        return None
    if any(v.get("keyframes") for v in p.values()):
        return None
    scale = _value(p, "scale", 100.0)
    uniform = _value(p, "uniform", True)
    pos, anchor = _value(p, "position"), _value(p, "anchor")
    if pos is None or anchor is None:
        return None
    crop = {s: (_value(p, f"crop_{s}", 0.0) or 0.0) / 100 for s in ("left", "top", "right", "bottom")}
    return {
        "position": (pos[0] * seq_frame[0], pos[1] * seq_frame[1]),
        "anchor": (anchor[0] * src[0], anchor[1] * src[1]),
        # Uniform Scale off: "scale" is the height, "scale_width" the width.
        "scale": (scale if uniform else _value(p, "scale_width", scale)) / 100, "scale_h": scale / 100,
        "rotation": _value(p, "rotation", 0.0),
        "rect": (crop["left"] * src[0], crop["top"] * src[1], (1 - crop["right"]) * src[0], (1 - crop["bottom"]) * src[1]),
        "raw": {k: v["value"] for k, v in p.items()},
    }


def to_sequence(m: dict, x: float, y: float) -> tuple[float, float]:
    dx, dy = (x - m["anchor"][0]) * m["scale"], (y - m["anchor"][1]) * m["scale_h"]
    r = math.radians(m["rotation"])
    return (m["position"][0] + dx * math.cos(r) - dy * math.sin(r),
            m["position"][1] + dx * math.sin(r) + dy * math.cos(r))


def corners(m: dict) -> list[tuple[float, float]]:
    l, t, r, b = m["rect"]
    return [to_sequence(m, x, y) for x, y in ((l, t), (r, t), (l, b), (r, b))]


def anchor_label(m: dict, tol: float = 0.5) -> str:
    """Which of the nine picker points the anchor is on (within `tol` source px), else 'custom'."""
    l, t, r, b = m["rect"]
    for (fx, fy), name in TARGETS.items():
        if abs(m["anchor"][0] - (l + fx * (r - l))) <= tol and abs(m["anchor"][1] - (t + fy * (b - t))) <= tol:
            return name
    return "custom"


def drift(before: dict, after: dict) -> float:
    return max(math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(corners(before), corners(after)))


def compare(before_seq: dict, after_seq: dict) -> list[dict]:
    """One row per Motion clip found in both saves, matched by track and start time."""
    key = lambda t, c: (t["index"], round(c["start"], 3))
    old = {key(t, c): c for t in before_seq["video_tracks"] for c in t["clips"]}
    rows = []
    for t in after_seq["video_tracks"]:
        for c in t["clips"]:
            b, a = old.get(key(t, c)), motion_model(c, after_seq["frame"])
            b = motion_model(b, before_seq["frame"]) if b else None
            if a and b:
                changed = {k: (b["raw"].get(k), v) for k, v in a["raw"].items() if b["raw"].get(k) != v}
                rows.append({"track": t["index"], "name": c["name"], "start": c["start"], "changed": changed,
                             "anchor": anchor_label(a), "drift": drift(b, a), "scale": (a["scale"], a["scale_h"]),
                             "rotation": a["rotation"]})
    return rows


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("before")
    p.add_argument("after")
    p.add_argument("--sequence", required=True)
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    seqs = {}
    for path in (args.before, args.after):
        seqs[path] = next((s for s in read_project(path)["sequences"] if s["name"] == args.sequence), None)
        if seqs[path] is None:
            sys.exit(f'No sequence "{args.sequence}" in {path}')
    for r in compare(seqs[args.before], seqs[args.after]):
        if not r["changed"]:
            continue
        print(f"V{r['track'] + 1} @{r['start']:.2f}s {r['name']}: anchor on {r['anchor']}, "
              f"picture moved {r['drift']:.2f} px, scale {r['scale'][0]:g}x{r['scale'][1]:g}, rotation {r['rotation']:g}")
        for k, (was, now) in r["changed"].items():
            print(f"    {k}: {was} -> {now}")


if __name__ == "__main__":
    main()
