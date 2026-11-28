"""Cut-edge ruler over many of the user's hand cuts (offline, saved .prproj files).

python scripts/timeline_listen/edge_ruler.py run [--pads 60,120] [--wordless 0] [--out runs.json]
python scripts/timeline_listen/edge_ruler.py compare A_SETTING B_SETTING [--split heldout] [--runs runs.json]

The set is `edge_set.json`: one entry per (project, source) the user cut by hand. For each, every
enabled clip of that source on audio track 1 of the project's own sequences (agent-made sequence
names left out) is a piece, deduplicated by source span across sequences, since the user derives
every sequence from its parent. `plan_pieces` places a piece for the words inside it, and its In
and Out are compared with the user's. An edge is a hit when it is within one 30 fps frame (34 ms).
`compare` gives the paired change in hit share between two settings with a 95% bootstrap interval
over sources (a source is never in both halves; see EDGE_RULER.md). Read-only on the projects;
needs each source transcribed in the store this checkout resolves (`transcriber.db`).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

from cutdeck import timeline_transcript as tt, word_cut
from cutdeck.prproj_reader import read_project
from transcribe.audio import levels as lv
from transcribe.db import store

HERE = Path(__file__).parent
SET = HERE / "edge_set.json"
TPF = 8467200000  # 30 fps
T = tt.TICKS_PER_MS
FRAME_MS = 34
AGENT = re.compile(r"cutdeck|listen|agent|scratch|rough|draft|test", re.I)


def pieces(project: dict, media: str) -> list[tuple[float, float]]:
    spans = set()
    for s in project["sequences"]:
        if AGENT.search(s["name"]) or not s["audio_tracks"]:
            continue
        for c in s["audio_tracks"][0]["clips"]:
            if not c["disabled"] and (c.get("media_path") or "") == media:
                spans.add((round(c["source_in"], 3), round(c["source_out"], 3)))
    return sorted(spans)


def score_entry(entry: dict, settings: list[tuple[int, int]], db: Path, levels_dir: Path) -> list[dict]:
    media = entry["media"]
    got = tt.source_words(media, db, levels_dir)
    if got is None:
        raise SystemExit(f"not transcribed: {media}")
    words, levels = got[1], got[2]
    over = lv.over(levels, lv.QUIET)
    last = len(over) - 1  # a clip may run to the file's end, past the last 10 ms level frame
    lvl = lambda m, t: float(over[max(min(int(t / T // 10), last) - 2, 0):min(int(t / T // 10), last) + 2].max())  # noqa: E731
    src = [tt.TimelineWord(w.text, w.start_ms * T, w.end_ms * T, "S", media, w.start_ms, w.end_ms, w.cue, None)
           for w in words]
    rows = []
    for i0, i1 in pieces(read_project(entry["project"]), media):
        i0, i1 = i0 * 1000, i1 * 1000
        k = [n for n, w in enumerate(src) if w.src_start_ms >= i0 - 40 and w.src_end_ms <= i1 + 40]
        if not k:
            continue
        for pad, wordless in settings:
            # Each edge from its own edge word, as keep_ranges places them: a piece the user kept may
            # hold a long pause, which plan_pieces refuses as one stretch.
            plan = lambda n: word_cut.plan_pieces(src, [{"word_range": [n, n]}], TPF, {media: words}, lvl,  # noqa: E731
                                                  pad, wordless)[0]
            head, tail = plan(k[0]), plan(k[-1])
            for side, owner, planned in (("in", i0, int(head["in_ticks"]) / T), ("out", i1, int(tail["out_ticks"]) / T)):
                rows.append({"source": entry["source"], "setting": f"{pad}/{wordless}", "side": side,
                             "owner_ms": round(owner), "planned_ms": round(planned), "diff": round(planned - owner),
                             "sound": lvl(media, owner * T) >= 0,
                             "inword": any(w.start_ms + 20 < owner < w.end_ms - 20 for w in words)})
    return rows


def hit(r: dict) -> int:
    return int(abs(r["diff"]) <= FRAME_MS)


def summary(rows: list[dict]) -> dict:
    n = len(rows)
    return {"edges": n, "sources": len({r["source"] for r in rows}),
            "w1": sum(map(hit, rows)) / n if n else 0.0,
            "w100": sum(abs(r["diff"]) <= 100 for r in rows) / n if n else 0.0,
            "off200": sum(abs(r["diff"]) > 200 for r in rows)}


def compare(rows: list[dict], a: str, b: str, iters: int = 2000, seed: int = 0) -> dict:
    """Paired change in within-1-frame share (b minus a), bootstrap over sources."""
    key = lambda r: (r["source"], r["side"], r["owner_ms"])  # noqa: E731
    ra = {key(r): r for r in rows if r["setting"] == a}
    rb = {key(r): r for r in rows if r["setting"] == b}
    pairs = [(ra[k], rb[k]) for k in ra if k in rb]
    by_src: dict[str, list[int]] = {}
    for x, y in pairs:
        by_src.setdefault(x["source"], []).append(hit(y) - hit(x))
    srcs = sorted(by_src)
    rng = random.Random(seed)
    boots = []
    for _ in range(iters if srcs else 0):
        pick = [by_src[rng.choice(srcs)] for _ in srcs]
        n = sum(map(len, pick))
        boots.append(sum(map(sum, pick)) / n if n else 0.0)
    boots.sort()
    n = len(pairs)
    return {"a": a, "b": b, "edges": n, "sources": len(srcs),
            "delta": sum(map(sum, by_src.values())) / n if n else 0.0,
            "ci95": [boots[int(0.025 * len(boots))], boots[int(0.975 * len(boots)) - 1]] if boots else [0.0, 0.0],
            "better": sum(hit(y) > hit(x) for x, y in pairs), "worse": sum(hit(y) < hit(x) for x, y in pairs)}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--pads", default="60,120")
    r.add_argument("--wordless", type=int, default=0)
    r.add_argument("--out", type=Path, default=Path("output/edge_ruler/runs.json"))
    c = sub.add_parser("compare")
    c.add_argument("a"); c.add_argument("b")
    c.add_argument("--split", default="heldout")
    c.add_argument("--runs", type=Path, default=Path("output/edge_ruler/runs.json"))
    args = ap.parse_args()
    entries = json.loads(SET.read_text(encoding="utf-8"))["cuts"]
    if args.cmd == "run":
        settings = [(int(p), args.wordless) for p in args.pads.split(",")]
        db = store.resolve_db_path({"store": {"path": "transcriber.db"}})
        rows = []
        for e in entries:
            got = score_entry(e, settings, db, Path("output/timeline_transcripts/levels"))
            for x in got:
                x["split"] = e["split"]
            rows += got
            print(e["source"], e["split"], {s: summary([x for x in got if x["setting"] == f"{s[0]}/{s[1]}"])["w1"]
                                            for s in settings}, flush=True)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        for split in ("tune", "heldout"):
            for s in settings:
                tag = f"{s[0]}/{s[1]}"
                print(split, tag, summary([x for x in rows if x["split"] == split and x["setting"] == tag]))
    else:
        rows = [x for x in json.loads(args.runs.read_text(encoding="utf-8")) if x["split"] == args.split]
        print(json.dumps(compare(rows, args.a, args.b), indent=1))


if __name__ == "__main__":
    main()
