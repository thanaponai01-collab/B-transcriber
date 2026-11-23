"""HKS: the draft long form of one day as a ``build_sequence`` request, for a live run on a copy.

From ``hks_draft.draft`` (Phase 4) and ``hks_finish`` (Phase 5):
- the body: every keep, in order, video and audio linked on V1 / A1 from timeline 0;
- the covers (4.3): the best candidate of each covered cut, video only on V2, COVER_S long and
  centred on the cut;
- the music bed (5.2): ``hks_finish.music_bed`` with no hook, on A5 / A6.

Not in the request, and listed under ``not_built``: the hook (5.4, the user picks soundbites),
the clock blur (5.1, needs the template's adjustment layer as ``like``), film damage and the
news-window zoom on covers, and the ending (5.5, pasted from the template). The media paths are
the ones the day's own project uses, so the request only runs in a copy of that project.

``--check`` is the offline proof: the body runs without a gap or an overlap, every covered cut
has a cover over it, and the bed plays from 0 to the end. ``--out`` writes the request.

    python -m cutdeck.hks_assemble "G:\\Me\\Works\\20261120 - โหนกระแส" --check [--out req.json]
"""
from __future__ import annotations

import argparse
import json
import ntpath
import sys
from pathlib import Path

from cutdeck import hks_draft, hks_episode, hks_finish
from cutdeck.hks_build import FRAME, ticks
from cutdeck.hks_build import _secs as _s
from cutdeck.hks_covers import COVER_S

NOT_BUILT = ["hook (5.4)", "clock blur (5.1)", "film damage and window zoom on covers (4.3)", "ending (5.5)"]


def project_paths(project: str) -> dict[str, str]:
    """Basename (lower case) -> media path, for every clip in the saved project."""
    from cutdeck.prproj_reader import read_project
    out = {}
    for seq in read_project(project)["sequences"]:
        for track in seq["video_tracks"] + seq["audio_tracks"]:
            for c in track["clips"]:
                if c.get("media_path"):
                    out.setdefault(ntpath.basename(c["media_path"]).lower(), c["media_path"])
    return out


def request(folder: Path, name: str | None = None) -> dict:
    from cutdeck.hks_gold import read_day
    day = folder.name[:8]
    paths = project_paths(read_day(folder).project)
    d = hks_draft.draft(folder)
    items, covers, t = [], [], 0.0
    for media in hks_episode.broadcast_order(d):
        path = paths[media.lower()]
        for i, (a, b) in enumerate(d[media]["keeps"]):
            items.append({"id": f"V1@{t:.2f}", "media": path, "in_ticks": ticks(a), "out_ticks": ticks(b),
                          "at_ticks": ticks(t), "v": 0, "a": 0})
            t += b - a
            c = d[media]["covers"].get(round(b, 2))
            if c and i + 1 < len(d[media]["keeps"]):
                at = max(0.0, t - COVER_S / 2)
                covers.append({"id": f"V2@{at:.2f}", "media": path, "in_ticks": ticks(c[0]["source_in"]),
                               "out_ticks": ticks(c[0]["source_in"] + COVER_S), "at_ticks": ticks(at),
                               "v": 1, "a": None, "cut": round(t, 2), "kind": c[0]["kind"]})
    bed = hks_finish.items(hks_finish.music_bed(None, t), paths[hks_finish.BGM], (4, 5))
    return {"command": "build_sequence", "name": name or f"CutDeck draft {day} YT", "show_end": round(t, 2),
            "items": items + [{k: v for k, v in c.items() if k not in ("cut", "kind")} for c in covers] + bed,
            "covers": [(c["cut"], c["kind"]) for c in covers], "not_built": NOT_BUILT}


def check(req: dict) -> list[str]:
    """Problems with the request; empty when it holds."""
    bad = []
    body = sorted((it for it in req["items"] if it["v"] == 0), key=lambda it: int(it["at_ticks"]))
    t = 0.0
    for it in body:
        at = _s(it["at_ticks"])
        if abs(at - t) > FRAME / 2:
            bad.append(f"body gap or overlap at {at:.2f} (expected {t:.2f})")
        t = at + _s(it["out_ticks"]) - _s(it["in_ticks"])
    if abs(t - req["show_end"]) > FRAME:
        bad.append(f"body ends at {t:.2f}, not {req['show_end']}")
    v2 = [(_s(it["at_ticks"]), _s(it["at_ticks"]) + _s(it["out_ticks"]) - _s(it["in_ticks"]))
          for it in req["items"] if it["v"] == 1]
    for cut, _ in req["covers"]:
        if not any(a <= cut <= b for a, b in v2):
            bad.append(f"cut at {cut} has no cover over it")
    bed = [(_s(it["at_ticks"]), _s(it["at_ticks"]) + _s(it["out_ticks"]) - _s(it["in_ticks"]))
           for it in req["items"] if it["v"] is None]
    for i in range(round(req["show_end"] / FRAME)):
        s = (i + 0.5) * FRAME
        if not any(a <= s < b for a, b in bed):
            bad.append(f"no music at {s:.2f}")
            break
    return bad


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("folder")
    p.add_argument("--check", action="store_true")
    p.add_argument("--out")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    req = request(Path(args.folder))
    if args.out:
        Path(args.out).write_text(json.dumps(req, ensure_ascii=False, indent=1), encoding="utf-8")
    problems = check(req) if args.check else []
    print(json.dumps({"show_end": req["show_end"], "items": len(req["items"]), "covers": len(req["covers"]),
                      "problems": problems[:10], "not_built": req["not_built"]}, ensure_ascii=False))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
