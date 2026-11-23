"""Check a saved 9:16 timeline against the measurable 1RaceClub Shorts rules (issue 128).

Rules and definitions are in projects/1raceclub/shorts-rules.md (settled by the user 2026-11-23):
- A Short is a run of clips between empty stretches of the timeline; the gap between two Shorts
  is parking, not a break of "zero gaps".
- Moving race broadcast on screen at most 3 s per Short. Only the race feed counts (media path
  matches ``feed``), not interviews or other clips. A still on a higher track hides it.
- Boxes (cropped assets narrower than the frame) stay inside x 60-890, y 250-1561.
- The title, the text that starts on a Short's first frame, ends on a cut.

Reads only what ``prproj_reader.read_project`` returns; never touches Premiere.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

from cutdeck.prproj_reader import read_project

# The synced race feed ("Las Vegas GP 2026 Race.mp4"), or a clip rendered from it into the
# episode's "6. ASSETS" folder (every moving asset there so far is one). Matched on the media path.
FEED = r"GP \d{4} (Race|Qualifying|Sprint|Practice|FP[123])|\\6\. ASSETS\\"
MAX_MOVING_S = 3.0
SAFE_ZONE = (60, 250, 890, 1561)  # left, top, right, bottom in a 1080x1920 frame
TOL = 0.5 / 30  # half a frame at 30 fps
STILL = (".png", ".jpg", ".jpeg", ".psd", ".tif", ".tiff")


def _is_text(c: dict) -> bool:
    return any(e.get("text") for e in c["effects"])


def _is_still(c: dict) -> bool:
    return "frame_hold" in c or (c.get("media_path") or c["name"]).lower().endswith(STILL)


def _is_feed(c: dict, pattern: re.Pattern) -> bool:
    return bool(pattern.search(c.get("media_path") or c["name"]))


def _motion(c: dict) -> dict | None:
    return next((e["params"] for e in c["effects"] if e.get("match_name") == "AE.ADBE Motion"), None)


def _box(c: dict, frame: list[int]) -> list[int] | None:
    """On-screen [left, top, right, bottom] of a cropped clip narrower than the frame, else None."""
    m = _motion(c)
    if m is None or not c.get("source_frame"):
        return None
    crop = [m.get(k, {}).get("value", 0.0) for k in ("crop_left", "crop_top", "crop_right", "crop_bottom")]
    if not any(crop) or m.get("rotation", {}).get("value", 0.0):
        return None
    (w, h), (W, H) = c["source_frame"], frame
    s = m["scale"]["value"] / 100
    px, py = m["position"]["value"][0] * W, m["position"]["value"][1] * H
    ax, ay = m["anchor"]["value"][0] * w, m["anchor"]["value"][1] * h
    box = [px + (crop[0] / 100 * w - ax) * s, py + (crop[1] / 100 * h - ay) * s,
           px + ((1 - crop[2] / 100) * w - ax) * s, py + ((1 - crop[3] / 100) * h - ay) * s]
    if box[2] - box[0] >= W - 1:
        return None
    return [round(v) for v in box]


def _merge(spans: list[tuple[float, float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + TOL:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _clip_in(span: tuple[float, float], a: float, b: float) -> tuple[float, float] | None:
    lo, hi = max(span[0], a), min(span[1], b)
    return (lo, hi) if hi > lo else None


def check_sequence(sequence: dict, feed: str = FEED) -> list[dict]:
    """Every rule break in the sequence, one dict per flag, in timeline order per Short."""
    frame = sequence["frame"]
    tracks = [(t["index"], [c for c in t["clips"] if not c["disabled"]])
              for t in sequence["video_tracks"] if not t["muted"]]
    clips = [(i, c) for i, cs in tracks for c in cs]
    pattern = re.compile(feed, re.IGNORECASE)
    flags = []
    for short in _merge([(c["start"], c["end"]) for _, c in clips]):
        a, b = short
        inside = [(i, c) for i, c in clips if _clip_in((c["start"], c["end"]), a, b)]
        tag = [round(a, 2), round(b, 2)]

        covers = [(i, c) for i, c in inside if _is_still(c) and not _is_text(c) and _box(c, frame) is None]
        visible = []
        for i, c in inside:
            if _is_feed(c, pattern) and not _is_still(c):
                lo = c["start"]
                for x, y in _merge([(o["start"], o["end"]) for j, o in covers if j > i]):
                    if y > lo and x < c["end"]:
                        visible.append((lo, max(lo, x)))
                        lo = max(lo, y)
                visible.append((lo, max(lo, c["end"])))
        seconds = sum(y - x for x, y in _merge([v for v in visible if v[1] > v[0]]))
        if seconds > MAX_MOVING_S + TOL:
            flags.append({"short": tag, "rule": "moving_video", "seconds": round(seconds, 2)})

        l, t, r, btm = SAFE_ZONE
        for i, c in inside:
            box = _box(c, frame)
            if box and (box[0] < l or box[1] < t or box[2] > r or box[3] > btm):
                flags.append({"short": tag, "rule": "safe_zone", "track": i + 1, "start": c["start"],
                              "name": c["name"], "box": box})

        cuts = {a, b} | {x for _, c in inside if not _is_text(c) for x in (c["start"], c["end"])}
        for i, c in inside:
            if _is_text(c) and abs(c["start"] - a) <= TOL and not any(abs(c["end"] - x) <= TOL for x in cuts):
                words = next(e["text"].get("text") for e in c["effects"] if e.get("text"))
                flags.append({"short": tag, "rule": "title_on_cut", "track": i + 1, "end": c["end"], "text": words})
    return flags


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Flag 9:16 timelines in a .prproj that break the Shorts rules.")
    p.add_argument("project")
    p.add_argument("--sequence", action="append", help="only this sequence (repeatable); default every 9:16 one")
    p.add_argument("--feed", default=FEED, help="regex for the race feed's media path")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    report = {}
    for s in read_project(args.project)["sequences"]:
        if (s["name"] in args.sequence) if args.sequence else s["frame"] == [1080, 1920]:
            report[s["name"]] = check_sequence(s, args.feed)
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 1 if any(report.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
