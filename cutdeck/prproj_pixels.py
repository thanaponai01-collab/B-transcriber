"""Print each clip's Position and Anchor Point in pixels, read from a saved .prproj.

Diff it against Effect Controls after a live edit: save the project, run this, compare.
Position is normalized to the sequence frame, Anchor Point to the clip's source frame
(docs/PREMIERE_FACTS.md, "Motion / Opacity / Text transform in the saved .prproj"); a Text
layer's Anchor is sequence-normalized too. Values are the saved ones, so keyframed params show
their start value and are marked.

    python -m cutdeck.prproj_pixels test_projects/probe.prproj --sequence "Sequence 04"
"""

from __future__ import annotations

import argparse
import sys

from cutdeck.prproj_reader import read_project


def _px(param: dict | None, frame: list[int] | None) -> str:
    if not param or not frame:
        return "-"
    x, y = (round(v * d, 1) for v, d in zip(param["value"], frame))
    return f"{x:g}, {y:g}" + (" (keyframed)" if param.get("keyframes") else "")


def clip_rows(sequence: dict) -> list[tuple]:
    """(track, clip name, start, effect, position px, anchor px) per transform effect."""
    rows = []
    for track in sequence["video_tracks"]:
        for clip in track["clips"]:
            for fx in clip["effects"]:
                params = fx.get("params")
                if not params or "position" not in params:
                    continue
                # Motion anchors to the source frame; a Text layer's transform to the sequence's.
                anchor_frame = clip.get("source_frame") if fx["match_name"] == "AE.ADBE Motion" else sequence["frame"]
                rows.append((track["index"], clip["name"], clip["start"], fx["name"],
                             _px(params["position"], sequence["frame"]), _px(params.get("anchor"), anchor_frame)))
    return rows


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("project")
    p.add_argument("--sequence", help="only the sequence with this name")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    for seq in read_project(args.project)["sequences"]:
        if args.sequence and seq["name"] != args.sequence:
            continue
        rows = clip_rows(seq)
        if not rows:
            continue
        print(f"{seq['name']}  (sequence frame {seq['frame'][0]}x{seq['frame'][1]})")
        for track, name, start, fx, pos, anchor in rows:
            print(f"  V{track + 1} @{start:.2f}s  {name} / {fx}: position {pos} | anchor {anchor}")


if __name__ == "__main__":
    main()
