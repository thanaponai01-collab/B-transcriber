"""hks_gates.py: the HKS handover gates, measured on a saved .prproj (never live Premiere).

Each gate catches one mistake the user corrected (projects/hks/gates/failure-table.md). Its kind
(control or warning), pass line and status live in projects/hks/gates/registry.json, set from the
backtest on the user's finished cuts (``hks_gates_backtest``). A control that fails blocks the
handover; a warning is listed in it. Gates in code:

- ``same_frame_share``: share of body sound cuts where the picture cuts on the same frame.
- ``near_miss_covers``: share of body sound cuts where the picture changes 1-4 frames off the
  cut and not on it: a cover placed a frame or two late or early.
- ``source_repeats``: two neighbouring A1 pieces that overlap in source, so words play twice.
- ``draft_labels``: share of body A1 pieces carrying a label colour (not the default).
- ``day_setup``: the day's ``Editing`` is split with its keepers labelled, yellow marks the
  must-keep moments, and ``Backup`` holds the inserts.

The cold-reviewer gates (endings, set-up) need judgment; ``hks_handover`` runs them.

    python -m cutdeck.hks_gates --prproj <day>.prproj --sequence "1 YOUTUBE agent v2" --from 26.76
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cutdeck.hks_cut_check import check, footage, sound_cuts, visible

REGISTRY = Path(__file__).resolve().parent.parent / "projects" / "hks" / "gates" / "registry.json"
# The transcript store and level cache live in the main checkout (its .git is a folder); a
# worktree (.git is a file) sits under it, and an empty store there would pass every gate.
MAIN = next((p for p in Path(__file__).resolve().parents if (p / ".git").is_dir()),
            Path(__file__).resolve().parent.parent)
DEFAULT_LABEL = 14  # BE.Prefs.LabelColors.14: an unlabelled clip (projects/hks/study/labels.md)
YELLOW = 10


def registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def body_audio(seq: dict, lo: float, hi: float) -> list[dict]:
    return sorted((c for c in seq["audio_tracks"][0]["clips"]
                   if not c.get("disabled") and c["end"] > lo and c["start"] < hi), key=lambda c: c["start"])


def same_frame_share(cut: dict) -> dict:
    n = cut["sound_cuts"]
    return {"value": round(len(cut["same_frame_cuts"]) / max(n, 1), 3), "items": cut["same_frame_cuts"],
            "detail": f"{len(cut['same_frame_cuts'])} of {n} sound cuts"}


def near_miss_covers(seq: dict, cut_times: list[float], fps: float = 25.0) -> dict:
    """Sound cuts where the picture changes 1-4 frames off the cut and not on it: a cover that
    starts or ends a few frames late or early (user, 20261123 v4 red marker). Counting every
    picture change near a cut instead was tried: same finals, 3 more unflagged drafts."""
    frame = 1.0 / fps
    vt, items = seq["video_tracks"], []

    def shown(t: float):
        c = visible(vt, t)
        return id(c) if c else None
    for t in cut_times:
        if shown(t - frame / 2) != shown(t + frame / 2):
            continue  # the picture cuts on the sound cut: same_frame_share counts it
        for k in (1, 2, 3, 4):
            if (shown(t + (k - 0.5) * frame) != shown(t + (k + 0.5) * frame)
                    or shown(t - (k + 0.5) * frame) != shown(t - (k - 0.5) * frame)):
                items.append({"at_s": round(t, 2), "frames_off": k})
                break
    return {"value": round(len(items) / max(len(cut_times), 1), 3), "items": items,
            "detail": f"{len(items)} of {len(cut_times)} sound cuts"}


def source_repeats(clips: list[dict], tol: float = 0.04) -> dict:
    items = []
    for p, n in zip(clips, clips[1:]):
        if (p.get("media_path") == n.get("media_path") and n["source_in"] < p["source_out"] - tol
                and n["source_out"] > p["source_out"] and abs(n["start"] - p["end"]) < 0.5):
            items.append({"at_s": round(n["start"], 2), "src_s": round(n["source_in"], 2),
                          "overlap_s": round(p["source_out"] - n["source_in"], 2)})
    return {"value": len(items), "items": items}


def draft_labels(clips: list[dict]) -> dict:
    bare = [round(c["start"], 2) for c in clips if c.get("label") in (None, DEFAULT_LABEL)]
    return {"value": round(1 - len(bare) / max(len(clips), 1), 3), "items": bare[:20]}


def day_setup(project: dict) -> dict:
    """Editing split + labelled keepers + yellow marks + a filled Backup."""
    def named(*names):
        found = [s for s in project["sequences"] if s["name"].strip().lower() in names
                 and any(t.get("clips") for t in s["video_tracks"])]
        return max(found, key=lambda s: sum(len(t["clips"]) for t in s["video_tracks"])) if found else None
    editing, backup = named("editing", "edit"), named("backup")
    missing = []
    if editing is None:
        missing.append("no Editing sequence")
    else:
        clips = [c for t in editing["video_tracks"] + editing["audio_tracks"] for c in t["clips"] if footage(c) or c.get("media_path")]
        pieces = len([c for c in editing["audio_tracks"][0]["clips"]]) if editing["audio_tracks"] else 0
        labelled = [c for c in clips if c.get("label") not in (None, DEFAULT_LABEL)]
        if pieces < 5:
            missing.append(f"Editing not split ({pieces} A1 pieces)")
        if len(labelled) < 0.5 * max(len(clips), 1):
            missing.append(f"Editing keepers not labelled ({len(labelled)} of {len(clips)})")
        if not any(c.get("label") == YELLOW for c in clips):
            missing.append("no yellow (must-keep / hot spot) on Editing")
    if backup is None or sum(len(t["clips"]) for t in backup["video_tracks"]) < 5:
        missing.append("Backup empty")
    return {"value": len(missing), "items": missing}


def run(project: dict, seq: dict, sources: dict, body_from: float, show_end: float | None,
        fps: float = 25.0) -> dict:
    """Every code gate on one sequence, with each gate's kind and line from the registry."""
    reg = registry()["gates"]
    hi = show_end or 1e9
    cut = check(seq, sources, fps, body_from)
    cut_times = [t for t, _, _ in sound_cuts(seq["audio_tracks"][0]["clips"]) if body_from <= t <= hi]
    # One body for every count: the same-frame share's numerator and denominator end at ``hi``.
    cut["same_frame_cuts"] = [t for t in cut["same_frame_cuts"] if t <= hi]
    cut["sound_cuts"] = len(cut_times)
    clips = body_audio(seq, body_from, hi)
    found = {
        "same_frame_share": same_frame_share(cut),
        "near_miss_covers": near_miss_covers(seq, cut_times, fps),
        "source_repeats": source_repeats(clips),
        "draft_labels": draft_labels(clips),
        "day_setup": day_setup(project) if project else None,
        "visible_cuts_in_speech": {"value": len(cut["visible_cuts_in_speech"]), "items": cut["visible_cuts_in_speech"]},
        "unsafe_holds": {"value": len(cut["unsafe_holds"]), "items": cut["unsafe_holds"]},
    }
    out = {}
    for gid, f in found.items():
        if f is None:
            continue
        g = reg[gid]
        if g["line"] is None:
            ok = True  # a list to look at, never a pass line
        else:
            ok = f["value"] <= g["line"] if g["direction"] == "max" else f["value"] >= g["line"]
        out[gid] = {**f, "line": g["line"], "direction": g["direction"], "kind": g["kind"],
                    "status": g["status"], "passed": ok}
    return out


def load_sources(seq: dict, db: Path, levels: Path) -> dict:
    """Words and level envelope per A1 media. Raises when a source has no words: a gate run on
    an empty transcript passes everything (every edge looks like a pause)."""
    from cutdeck.timeline_transcript import media_sha256, source_levels, source_words
    out = {}
    for media in {c.get("media_path") for c in seq["audio_tracks"][0]["clips"]} - {None}:
        if not Path(media).is_file():
            continue
        got = source_words(media, db)
        if not got or not got[1]:
            raise RuntimeError(f"no transcript words for {media}: run hks_day first (db {db})")
        lv = None
        try:
            lv = source_levels(media, levels / f"{media_sha256(media, db)}.npy")
        except (RuntimeError, OSError):
            pass
        out[media] = (got[1], lv)
    return out


def main(argv: list[str] | None = None) -> int:
    from cutdeck.prproj_reader import read_project
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prproj", required=True)
    ap.add_argument("--sequence", required=True)
    ap.add_argument("--from", dest="body_from", type=float, default=0.0)
    ap.add_argument("--to", dest="show_end", type=float, default=None)
    ap.add_argument("--db", type=Path, default=MAIN / "transcriber.db")
    ap.add_argument("--levels", type=Path, default=MAIN / "output/timeline_transcripts/levels")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    project = read_project(a.prproj)
    seq = next((s for s in project["sequences"] if s["name"] == a.sequence
                and any(t.get("clips") for t in s["audio_tracks"])), None)
    if seq is None:
        print(f"no sequence {a.sequence!r} with audio clips", file=sys.stderr)
        return 2
    res = run(project, seq, load_sources(seq, a.db, a.levels), a.body_from, a.show_end)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        for gid, r in res.items():
            mark = "PASS" if r["passed"] else ("FAIL" if r["kind"] == "control" else "WARN")
            print(f"{mark} {gid}: {r['value']} (line {'<=' if r['direction'] == 'max' else '>='} {r['line']}, "
                  f"{r['kind']}, {r['status']}) {r.get('detail', '')} {r['items'][:6]}")
    return 1 if any(not r["passed"] and r["kind"] == "control" and r["status"] != "retired" for r in res.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
