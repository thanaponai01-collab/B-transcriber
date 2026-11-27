"""Caption edges the user moved in a finished cut: the SRT the pipeline placed against the user's
final captions, each final edge classed as

- kept: within one frame of a placed edge;
- nudge: moved more than a frame, and the caption owning it has the same text as the placed
  caption owning the nearest placed edge (a pure re-time);
- resplit_or_text: moved, and the text differs (a split, merge or wording fix).

This is a separate reference from the hand-marked onsets: these edges may follow reading rules,
not the sound. Matching is by time and text, never by caption index (the user merges and splits)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).with_name("user_edits")


def read_srt(path: Path) -> list[dict]:
    out = []
    for block in path.read_text(encoding="utf-8-sig").strip().split("\n\n"):
        lines = block.strip().splitlines()
        g = list(map(int, re.findall(r"\d+", lines[1])))
        out.append({"start_ms": ((g[0] * 60 + g[1]) * 60 + g[2]) * 1000 + g[3],
                    "end_ms": ((g[4] * 60 + g[5]) * 60 + g[6]) * 1000 + g[7], "text": " ".join(lines[2:])})
    return out


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


def classify(placed: list[dict], final: list[dict], fps: float, window_ms: tuple[float, float] | None = None) -> dict:
    frame = 1000 / fps
    edges = [(c[k], k, c) for c in placed for k in ("start_ms", "end_ms")]
    rows = []
    for cap in final:
        for k in ("start_ms", "end_ms"):
            t = cap[k]
            if window_ms and not window_ms[0] <= t <= window_ms[1]:
                continue
            pt, pk, pc = min(edges, key=lambda e: abs(e[0] - t))
            d = t - pt
            kind = "kept" if abs(d) <= frame + 1e-6 else ("nudge" if _norm(pc["text"]) == _norm(cap["text"]) else "resplit_or_text")
            rows.append({"edge": k[:-3], "final_ms": t, "placed_ms": pt, "moved_ms": d, "class": kind,
                         "final_text": cap["text"], "placed_text": pc["text"]})
    counts = {c: sum(r["class"] == c for r in rows) for c in ("kept", "nudge", "resplit_or_text")}
    return {"fps": fps, "placed_cues": len(placed), "final_cues": len(final), "edges": len(rows), "counts": counts, "rows": rows}


def singapore() -> dict:
    exports = Path("E:/Me/2.Tasks/20261011 - 3/5. EXPORTS")
    res = classify(read_srt(exports / "yt t1 singapore.srt"), read_srt(exports / "mine first min_yt t1 singapore.srt"),
                   30, (0, 60200))
    return {"cut": "yt t1 singapore (1RaceClub, 2026-10-11), first 60.2 s (the part the user re-timed)", **res}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(exist_ok=True)
    res = singapore()
    (OUT / "singapore.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, ensure_ascii=False, indent=1))
    for r in res["rows"]:
        if r["class"] != "kept":
            print(f"{r['edge']:5s} {r['final_ms']/1000:7.3f}s moved {r['moved_ms']:+6.0f} ms {r['class']:16s} "
                  f"{r['placed_text']} -> {r['final_text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
