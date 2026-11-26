"""hks_gates_mutate.py: mutation-test the HKS handover gates on the user's finished cuts.

For every final (tuning days and holdouts) the kept gates must pass the real cut, and each must
fail once the mistake it guards against (projects/hks/gates/failure-table.md) is put back into a
copy of the parsed sequence. The .prproj files are only read; every mutant is a deep copy.

    python tools/hks_gates_mutate.py --root G:\\Me\\Works --out output/hks_rules/mutation
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cutdeck import hks_gates  # noqa: E402
from cutdeck.hks_cut_check import footage, in_sync, sound_cuts, visible  # noqa: E402
from cutdeck.hks_enforce import MAX_BODY_FROM, judge  # noqa: E402
from cutdeck.hks_gates_backtest import entries  # noqa: E402
from cutdeck.hks_gold import HOLDOUT, OUTPUTS, _pick, output_cut  # noqa: E402

FPS = 25.0
FRAME = 1.0 / FPS
GATES = ("same_frame_share", "near_miss_covers", "source_repeats", "draft_labels", "body_range")


def cut_times(seq: dict, lo: float, hi: float) -> list:
    return [(t, o, i) for t, o, i in sound_cuts(seq["audio_tracks"][0]["clips"]) if lo <= t <= hi]


def same_frame_count(seq: dict, lo: float, hi: float) -> int:
    """The same-frame numerator of ``hks_cut_check.check``, without its slow hold scan."""
    vt, h = seq["video_tracks"], FRAME / 2
    return sum(1 for t, o, i in cut_times(seq, lo, hi)
               if (b := visible(vt, t - h)) is not (a := visible(vt, t + h))
               and in_sync(b, o, t - h, FRAME) and in_sync(a, i, t + h, FRAME))


def need(n: int, line: float, bad) -> int:
    """Smallest count k of n whose rounded share is on the failing side of ``line``."""
    return next((k for k in range(n + 1) if bad(round(k / max(n, 1), 3), line)), n + 1)


def uncover(seq: dict, lo: float, hi: float, target: int) -> tuple[dict, dict]:
    """Remove the V2+ footage covers over body sound cuts, one cut at a time, until ``target``
    more cuts show sound and picture cutting on the same frame (K11, K23)."""
    m = copy.deepcopy(seq)
    base = got = same_frame_count(m, lo, hi)
    removed = 0
    for t, o, i in cut_times(m, lo, hi):
        if got - base >= target:
            break
        trial = copy.deepcopy(m)
        hit = 0
        for track in trial["video_tracks"][1:]:
            keep = [c for c in track["clips"] if not (c["start"] < t + FRAME and c["end"] > t - FRAME
                                                      and is_cover(c, o, i, t))]
            hit += len(track["clips"]) - len(keep)
            track["clips"] = keep
        if hit and (n := same_frame_count(trial, lo, hi)) > got:
            m, got, removed = trial, n, removed + hit
    return m, {"cuts_exposed": got - base, "covers_removed": removed, "reached": got - base >= target}


def is_cover(c: dict, out_clip: dict | None, in_clip: dict | None, t: float) -> bool:
    """A cutaway: footage in sync with neither side of the sound cut at ``t``. The user's V2+
    also holds synced re-framings of the speaker; those are the main picture, not covers."""
    return footage(c) and not in_sync(c, out_clip, t - FRAME / 2, FRAME) and not in_sync(c, in_clip, t + FRAME / 2, FRAME)


def covers_on_cuts(seq: dict, lo: float, hi: float) -> list[tuple[int, int]]:
    """(track, clip) of each V2+ cutaway that starts on a body sound cut and shows there."""
    cuts = cut_times(seq, lo, hi)
    out = []
    for ti, track in enumerate(seq["video_tracks"][1:], 1):
        for ci, c in enumerate(track["clips"]):
            on = next(((t, o, i) for t, o, i in cuts if abs(c["start"] - t) < FRAME / 2), None)
            if on and is_cover(c, on[1], on[2], on[0]) and visible(seq["video_tracks"], c["start"] + FRAME / 2) is c:
                out.append((ti, ci))
    return out


def shift_covers(seq: dict, lo: float, hi: float, late: bool, limit: int | None = None) -> tuple[dict, dict]:
    """Start each cover that sits on a sound cut 1-4 frames late or early, its source with it (K7a)."""
    m = copy.deepcopy(seq)
    found = covers_on_cuts(m, lo, hi)[:limit]
    for n, (ti, ci) in enumerate(found):
        c = m["video_tracks"][ti]["clips"][ci]
        d = (n % 4 + 1) * FRAME * (1 if late else -1)
        c["start"] += d
        c["source_in"] += d
    return m, {"covers_shifted": len(found), "direction": "late" if late else "early"}


def overlap_source(seq: dict, lo: float, hi: float) -> tuple[dict, dict]:
    """Run one body A1 piece's source 0.5 s into its neighbour's, timeline untouched (K27).
    The pair with the smallest forward source gap is used, as in the ripple slip of 20261125."""
    m = copy.deepcopy(seq)
    body = hks_gates.body_audio(m, lo, hi)
    pairs = [(n["source_in"] - p["source_out"], p, n) for p, n in zip(body, body[1:])
             if p.get("media_path") == n.get("media_path") and abs(n["start"] - p["end"]) < 0.5
             and n["source_in"] >= p["source_out"] - 0.04 and n["source_out"] - n["source_in"] > 0.5]
    if not pairs:
        return m, {"pair": None}
    gap, p, n = min(pairs, key=lambda x: x[0])
    p["source_out"] = n["source_in"] + 0.5
    return m, {"pair_at_s": round(n["start"], 2), "source_gap_s": round(gap, 2)}


def unlabel(seq: dict, lo: float, hi: float, count: int) -> tuple[dict, dict]:
    """Reset ``count`` labelled body A1 pieces, spread evenly, to the default label (K6)."""
    m = copy.deepcopy(seq)
    labelled = [c for c in hks_gates.body_audio(m, lo, hi) if c.get("label") not in (None, hks_gates.DEFAULT_LABEL)]
    picked = labelled[::max(len(labelled) // max(count, 1), 1)][:count]
    for c in picked:
        c["label"] = hks_gates.DEFAULT_LABEL
    return m, {"reset": len(picked), "labelled_before": len(labelled)}


def verdict(seq: dict, sources: dict, body_from: float, show_end: float | None) -> dict:
    found = hks_gates.run(None, seq, sources, body_from, show_end)
    v = judge(seq, found, body_from, {}, {}, {})
    values = {g: found[g]["value"] for g in GATES[:-1]}
    values["body_range"] = v["body_from"]
    return {"values": values, "failed": v["failed"], "found": found}


def mutate_final(seq: dict, sources: dict, body_from: float, show_end: float) -> dict:
    hi = show_end
    reg = hks_gates.registry()["gates"]
    base = verdict(seq, sources, body_from, show_end)
    n_cuts = len(cut_times(seq, body_from, hi))
    body = hks_gates.body_audio(seq, body_from, hi)
    sf = same_frame_count(seq, body_from, hi)
    sf_need = need(n_cuts, reg["same_frame_share"]["line"], lambda v, line: v > line) - sf
    nm_need = need(n_cuts, reg["near_miss_covers"]["line"], lambda v, line: v > line) \
        - len(base["found"]["near_miss_covers"]["items"])
    bare = sum(1 for c in body if c.get("label") in (None, hks_gates.DEFAULT_LABEL))
    lab_need = need(len(body), 1 - reg["draft_labels"]["line"], lambda v, line: v > line) - bare
    end = max((c["end"] for t in seq["audio_tracks"] for c in t["clips"]), default=0.0)
    margin = {
        "same_frame_share": {"to_line": round(reg["same_frame_share"]["line"] - base["values"]["same_frame_share"], 3),
                             "cuts_to_fail": sf_need, "of_cuts": n_cuts},
        "near_miss_covers": {"to_line": round(reg["near_miss_covers"]["line"] - base["values"]["near_miss_covers"], 3),
                             "cuts_to_fail": nm_need, "of_cuts": n_cuts},
        "source_repeats": {"to_line": reg["source_repeats"]["line"] - base["values"]["source_repeats"],
                           "overlaps_to_fail": 1},
        "draft_labels": {"to_line": round(base["values"]["draft_labels"] - reg["draft_labels"]["line"], 3),
                         "pieces_to_fail": lab_need, "of_pieces": len(body)},
        "body_range": {"to_line": round(MAX_BODY_FROM - base["values"]["body_range"], 3)},
    }
    covers = len(covers_on_cuts(seq, body_from, hi))
    nm_min = next((k for k in range(1, covers + 1)
                   if hks_gates.near_miss_covers(shift_covers(seq, body_from, hi, False, k)[0],
                                                 [t for t, _, _ in cut_times(seq, body_from, hi)])["value"]
                   > reg["near_miss_covers"]["line"]), None)
    margin["near_miss_covers"]["early_shifts_to_fail"] = nm_min
    margin["near_miss_covers"]["covers_on_cuts"] = covers
    mutants = {
        "noop": ("none", copy.deepcopy(seq), {}, body_from),
        "same_frame_share": ("same_frame_share", *uncover(seq, body_from, hi, max(sf_need, 1)), body_from),
        "near_miss_early": ("near_miss_covers", *shift_covers(seq, body_from, hi, late=False), body_from),
        "near_miss_late": ("near_miss_covers", *shift_covers(seq, body_from, hi, late=True), body_from),
        "source_repeats": ("source_repeats", *overlap_source(seq, body_from, hi), body_from),
        "draft_labels": ("draft_labels", *unlabel(seq, body_from, hi, max(math.ceil(0.1 * len(body)), 1)), body_from),
        "body_range": ("body_range", copy.deepcopy(seq), {"body_from": round(0.5 * end, 2)}, 0.5 * end),
        # The sequence end counts the YouTube pool after the show; half the show is the agent's slip.
        "body_range_half_show": ("body_range", copy.deepcopy(seq), {"body_from": round(0.5 * show_end, 2)},
                                 0.5 * show_end),
    }
    out = {}
    for name, (target, m, info, bf) in mutants.items():
        r = verdict(m, sources, bf, show_end)
        if name == "noop":
            state = "unchanged" if r["found"] == base["found"] else "CHANGED"
        elif name == "same_frame_share" and not info["reached"]:
            state = "unreachable"
        elif name == "source_repeats" and "pair_at_s" not in info:
            state = "no pair"
        else:
            state = "killed" if target in r["failed"] else "survived"
        out[name] = {"target": target, "state": state, "info": info, "values": r["values"], "failed": r["failed"],
                     "also_failed": [g for g in r["failed"] if g != target]}
    return {"baseline": {"values": base["values"], "failed": base["failed"]}, "margin": margin, "mutants": out}


def digest(seq: dict) -> str:
    return hashlib.sha256(json.dumps(seq, sort_keys=True, default=str).encode()).hexdigest()


def measure(root: Path, db: Path, levels: Path, days: list[str] | None = None) -> list[dict]:
    from cutdeck.prproj_reader import read_project
    rows = []
    for e in entries(root):
        if e["kind"] != "final" or (days and e["day"] not in days):
            continue
        project = read_project(e["prproj"])
        names = {p.name.lower() for p in (e["folder"] / "1. FOOTAGE").glob("*.mp4")}
        problems: list[str] = []
        if e["sequence"]:
            seq = next(s for s in project["sequences"] if s["name"] == e["sequence"]
                       and any(t.get("clips") for t in s["audio_tracks"]))
        else:
            seq = _pick(project, "yt", lambda n: n.startswith(OUTPUTS["yt"]) and "agent" not in n, problems)
        oc = output_cut(seq, names, seq["name"], problems) if seq else None
        if oc is None:
            print(e["day"], "skipped:", problems, flush=True)  # a day still being edited has no final yet
            continue
        body_from = e["body_from"] if e["body_from"] is not None else (oc.hook_end or 0.0)
        before = digest(seq)
        res = mutate_final(seq, hks_gates.load_sources(seq, db, levels), body_from, oc.show_end)
        assert digest(seq) == before, "a mutator changed the parsed final"
        rows.append({"id": f"{e['day']} {seq['name']}", "day": e["day"], "holdout": e["day"] in HOLDOUT,
                     "body_from": body_from, "show_end": oc.show_end, **res})
        print(rows[-1]["id"], {k: v["state"] for k, v in res["mutants"].items()}, flush=True)
    return rows


def settle(rows: list[dict]) -> list[dict]:
    """A kill needs a pass that flips: a final already failing the target gate is ``baseline fails``,
    and a gate that failed before the mutation is not collateral."""
    for r in rows:
        for m in r["mutants"].values():
            if m["target"] in r["baseline"]["failed"]:
                m["state"] = "baseline fails"
            m["also_failed"] = [g for g in m["failed"] if g != m["target"] and g not in r["baseline"]["failed"]]
    return rows


def summary(rows: list[dict]) -> dict:
    out = {}
    for name in rows[0]["mutants"]:
        states = [r["mutants"][name]["state"] for r in rows]
        killed, survived = states.count("killed"), states.count("survived")
        out[name] = {"target": rows[0]["mutants"][name]["target"], "killed": killed, "survived": survived,
                     "other": len(states) - killed - survived,
                     "kill_rate": round(killed / (killed + survived), 3) if killed + survived else None}
    return out


def fails_from(r: dict) -> float:
    """The body start from which body_range fails."""
    return MAX_BODY_FROM


def markdown(rows: list[dict], summ: dict) -> str:
    def cell(r, name):
        m = r["mutants"][name]
        v = m["values"].get(m["target"]) if m["target"] in m["values"] else ""
        extra = f" (+{','.join(m['also_failed'])})" if m["also_failed"] else ""
        return f"{m['state']} {v}{extra}"
    lines = ["# HKS gate mutation test", "",
             "Each kept gate on the user's finals, then on a copy with the mistake it guards against put back.",
             "`tools/hks_gates_mutate.py`; data in `results.json`. Holdouts marked *.", "",
             "## Kill rate", "", "| Mutant | Target gate | Killed | Survived | Other | Kill rate |",
             "|---|---|---|---|---|---|"]
    for name, s in summ.items():
        lines.append(f"| {name} | {s['target']} | {s['killed']} | {s['survived']} | {s['other']} | {s['kill_rate']} |")
    lines += ["", "## Baseline and margin", "",
              "| Final | body_from | same_frame (cuts to fail) | near_miss (cuts / early shifts to fail) | "
              "repeats | labels (pieces to fail) | body share (fails from body_from s / show end s) | baseline fails |",
              "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        b, mg = r["baseline"]["values"], r["margin"]
        lines.append(
            f"| {r['day']}{'*' if r['holdout'] else ''} | {r['body_from']:.2f} | {b['same_frame_share']} "
            f"({mg['same_frame_share']['cuts_to_fail']} of {mg['same_frame_share']['of_cuts']}) | "
            f"{b['near_miss_covers']} ({mg['near_miss_covers']['cuts_to_fail']} / "
            f"{mg['near_miss_covers']['early_shifts_to_fail']} of {mg['near_miss_covers']['covers_on_cuts']} covers) | "
            f"{b['source_repeats']} | {b['draft_labels']} ({mg['draft_labels']['pieces_to_fail']} of "
            f"{mg['draft_labels']['of_pieces']}) | {b['body_range']} ({fails_from(r):.0f} / {r['show_end']:.0f}) | "
            f"{', '.join(r['baseline']['failed']) or '-'} |")
    names = list(rows[0]["mutants"])
    lines += ["", "## Mutants (state, target value, other gates that failed)", "",
              "| Final | " + " | ".join(names) + " |", "|---" * (len(names) + 1) + "|"]
    for r in rows:
        lines.append(f"| {r['day']}{'*' if r['holdout'] else ''} | " + " | ".join(cell(r, n) for n in names) + " |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path("G:/Me/Works"))
    ap.add_argument("--out", type=Path, default=Path("output/hks_rules/mutation"))
    ap.add_argument("--db", type=Path, default=hks_gates.MAIN / "transcriber.db")
    ap.add_argument("--levels", type=Path, default=hks_gates.MAIN / "output/timeline_transcripts/levels")
    ap.add_argument("--days", nargs="*", help="only these days (default: every final)")
    ap.add_argument("--reuse", action="store_true", help="re-report from --out/results.json without re-measuring")
    a = ap.parse_args(argv)
    saved = a.out / "results.json"
    rows = json.loads(saved.read_text(encoding="utf-8"))["rows"] if a.reuse else measure(a.root, a.db, a.levels, a.days)
    rows = settle(rows)
    summ = summary(rows)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "results.json").write_text(json.dumps({"summary": summ, "rows": rows}, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    (a.out / "results.md").write_text(markdown(rows, summ), encoding="utf-8")
    print(json.dumps(summ, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
