"""hks_gates_backtest.py: run every code gate on the agent's drafts and the user's finished cuts.

The user's verdicts come from the failure table (projects/hks/gates/failure-table.md): a draft is a
positive for a gate when the user corrected that gate's mistake on it (in words, a red marker, or
a fix seen in the diff). Every other draft is a negative. Every user final is a negative that the
gate must pass. Pass lines are proposed from the finals' spread, never from the drafts.

    python -m cutdeck.hks_gates_backtest --root G:\\Me\\Works --out output/hks_gates/backtest.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

from cutdeck import hks_gates
from cutdeck.hks_gold import HOLDOUT, OUTPUTS, _pick, output_cut

# (day, sequence, body start s) for the agent's YT drafts that were handed to the user.
DRAFTS = [
    ("20261123", "YT draft", 0.0), ("20261123", "YT draft v2", 0.0), ("20261123", "YT draft v3", 0.0),
    ("20261123", "YT draft v4", 0.0), ("20261123", "YT draft v5", 0.0),
    ("20261124", "1 YOUTUBE agent v1", 0.0), ("20261124", "1 YOUTUBE agent v2", 0.0),
    ("20261124", "1 YOUTUBE agent v3", 0.0), ("20261124", "1 YOUTUBE agent v4", 0.0),
    # The pristine v1 rotated out of Auto-Save; 19:46 is the earliest left (~20 min into the user's edit).
    ("20261125", "1 YOUTUBE agent v1", 26.76, "Adobe Premiere Pro Auto-Save/20261125 - โหนกระแส--e7b6a2f0-896c-40f9-ea09-8348d4c12168-2026-11-25_19-46-22.prproj"),
]
# The user's final when the day folder holds more than one candidate (hks_gold refuses those).
FINAL_SEQUENCE = {"20261124": "1 YOUTUBE D1", "20261125": "1 YOUTUBE agent v1"}
FINAL_BODY_FROM = {"20261124": 32.0}  # hook 0-24.76 + sting (memory/yt-20261124-draft.md)

# The user's verdicts: draft -> gates whose mistake the user corrected on it (failure-table.md).
# "The cut shows": K7a (1123 v4), K11 (1124 v2, "cover v2 with insert"), K23 (1125 v1).
# Labels: K6 ("all your draft", said after v3). Repeats: K27. Near-miss covers: K7a.
POSITIVE = {
    "same_frame_share": {"20261123 YT draft v4", "20261124 1 YOUTUBE agent v2", "20261125 1 YOUTUBE agent v1"},
    "near_miss_covers": {"20261123 YT draft v4"},
    "source_repeats": {"20261125 1 YOUTUBE agent v1", "20261125 agent v1 @19:34 (A1)"},
    "draft_labels": {"20261123 YT draft", "20261123 YT draft v2", "20261123 YT draft v3"},
}


def day_folder(root: Path, day: str) -> Path:
    return next(p for p in root.iterdir() if p.name.startswith(day) and "โหน" in p.name)


def day_project(folder: Path, day: str) -> Path:
    base = folder / "4. PROJECTS" / "1. PREMIERE PRO"
    named = [p for p in base.glob("*.prproj") if p.name.startswith(day)]
    return (named or list(base.glob("*.prproj")))[0]


def entries(root: Path):
    for folder in sorted(p for p in root.iterdir() if p.name[:4] == "2026" and "โหน" in p.name):
        day = folder.name[:8]
        if "หลัง" in folder.name:
            continue  # compilations have no YT body
        yield {"day": day, "kind": "final", "folder": folder, "prproj": day_project(folder, day),
               "sequence": FINAL_SEQUENCE.get(day), "body_from": FINAL_BODY_FROM.get(day)}
    for d in DRAFTS:
        folder = day_folder(root, d[0])
        prproj = folder / "4. PROJECTS" / "1. PREMIERE PRO" / d[3] if len(d) > 3 else day_project(folder, d[0])
        yield {"day": d[0], "kind": "draft", "folder": folder, "prproj": prproj, "sequence": d[1], "body_from": d[2]}


def measure(root: Path, db: Path, levels: Path) -> list[dict]:
    from cutdeck.prproj_reader import read_project
    projects, rows = {}, []
    for e in entries(root):
        if e["prproj"] not in projects:
            projects[e["prproj"]] = read_project(e["prproj"])
        project = projects[e["prproj"]]
        footage = {p.name.lower() for p in (e["folder"] / "1. FOOTAGE").glob("*.mp4")}
        problems: list[str] = []
        if e["sequence"]:
            seq = next(s for s in project["sequences"] if s["name"] == e["sequence"]
                       and any(t.get("clips") for t in s["audio_tracks"]))
        else:
            seq = _pick(project, "yt", lambda n: n.startswith(OUTPUTS["yt"]) and "agent" not in n, problems)
        oc = output_cut(seq, footage, seq["name"], problems)
        body_from = e["body_from"] if e["body_from"] is not None else (oc.hook_end if oc and oc.hook_end else 0.0)
        show_end = oc.show_end if oc and e["kind"] == "final" else None
        found = hks_gates.run(project if e["kind"] == "final" else None, seq,
                              hks_gates.load_sources(seq, db, levels), body_from, show_end)
        rows.append({"id": f"{e['day']} {seq['name']}", "day": e["day"], "kind": e["kind"],
                     "holdout": e["day"] in HOLDOUT, "body_from": body_from,
                     "gates": {g: {"value": r["value"], "items": r["items"][:40]} for g, r in found.items()}})
        print(rows[-1]["id"], {g: r["value"] for g, r in found.items()}, flush=True)
    # 20261125 v1's A1 as saved at 19:34 (the .prproj rotated out; projects/hks/gates/data).
    v1 = json.loads((hks_gates.REGISTRY.parent / "data" / "20261125-v1-1934-a1.json").read_text(encoding="utf-8"))
    rep = hks_gates.source_repeats([p for p in v1["pieces"] if p["start"] >= 26.76])
    rows.append({"id": "20261125 agent v1 @19:34 (A1)", "day": "20261125", "kind": "draft", "holdout": False,
                 "body_from": 26.76, "gates": {"source_repeats": {"value": rep["value"], "items": rep["items"]}}})
    return rows


def report(rows: list[dict]) -> dict:
    out = {}
    for gid, spec in hks_gates.registry()["gates"].items():
        finals = [r for r in rows if r["kind"] == "final" and gid in r["gates"]]
        tune = [r["gates"][gid]["value"] for r in finals if not r["holdout"]]
        held = {r["day"]: r["gates"][gid]["value"] for r in finals if r["holdout"]}
        if not tune:
            continue
        line = max(tune) if spec["direction"] == "max" else min(tune)
        bad = (lambda v: v > line) if spec["direction"] == "max" else (lambda v: v < line)
        drafts = [r for r in rows if r["kind"] == "draft" and gid in r["gates"]]
        tp = [r["id"] for r in drafts if bad(r["gates"][gid]["value"]) and r["id"] in POSITIVE.get(gid, ())]
        fp = [r["id"] for r in drafts if bad(r["gates"][gid]["value"]) and r["id"] not in POSITIVE.get(gid, ())]
        fn = [r["id"] for r in drafts if not bad(r["gates"][gid]["value"]) and r["id"] in POSITIVE.get(gid, ())]
        out[gid] = {
            "finals_tuning": {"n": len(tune), "min": min(tune), "median": statistics.median(tune), "max": max(tune)},
            "holdout": held, "proposed_line": line,
            "holdout_pass": {d: not bad(v) for d, v in held.items()},
            "finals_failing": [r["id"] for r in finals if bad(r["gates"][gid]["value"])],
            "drafts": {r["id"]: r["gates"][gid]["value"] for r in drafts},
            "tp": tp, "fp": fp, "fn": fn,
            "precision": len(tp) / len(tp + fp) if tp + fp else None,
            "recall": len(tp) / len(tp + fn) if tp + fn else None,
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path("G:/Me/Works"))
    ap.add_argument("--out", type=Path, default=hks_gates.MAIN / "output/hks_gates/backtest.json")
    ap.add_argument("--db", type=Path, default=hks_gates.MAIN / "transcriber.db")
    ap.add_argument("--levels", type=Path, default=hks_gates.MAIN / "output/timeline_transcripts/levels")
    ap.add_argument("--reuse", action="store_true", help="re-report from --out without re-measuring")
    a = ap.parse_args(argv)
    rows = json.loads(a.out.read_text(encoding="utf-8"))["rows"] if a.reuse else measure(a.root, a.db, a.levels)
    rep = report(rows)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"rows": rows, "report": rep}, ensure_ascii=False, indent=1), encoding="utf-8")
    for gid, r in rep.items():
        print(f"\n{gid}: finals {r['finals_tuning']} holdout {r['holdout']} -> line {r['proposed_line']}")
        print(f"  finals failing: {r['finals_failing']}  holdout pass: {r['holdout_pass']}")
        print(f"  drafts: {r['drafts']}")
        print(f"  TP {r['tp']} FP {r['fp']} FN {r['fn']} precision {r['precision']} recall {r['recall']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
