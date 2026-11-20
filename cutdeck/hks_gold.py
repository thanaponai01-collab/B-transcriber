"""hks_gold.py — the user's real editing decisions for one โหนกระแส (HKS) day folder.

Reads the finished day project (via ``prproj_reader.read_project``) and returns, per output
(YouTube long form, Facebook, 1-minute), the footage the user kept, the cuts between kept
pieces, and which cuts are covered by other picture. Later HKS steps are scored against it
(docs/HKS_BUILD_PLAN.md, step 0.2).

Rules (measured on the 11 day projects, 2026-11-20):
- Kept footage comes from the footage AUDIO clips; the main picture alternates between V1 and
  V2, so V1 alone misses keeps.
- The YouTube timeline holds the show, then a "pool" of unused footage far later. The show ends
  at the last end of any clip whose media is not footage (BGM, SFX, end logo, AE comps).
- The hook ends where the ``Transition Complex 14`` SFX starts.
- A cut is a boundary between consecutive dialogue keeps whose source does not continue. A
  boundary that keeps the same media at the same sync (a muted censor piece left out of the
  keeps) is not a cut. A cut is uncovered only when the picture on both sides is the footage in
  sync with its audio at the same Motion scale and position, i.e. the viewer sees the main shot
  jump. A zoomed insert of the same footage (271-405 %) counts as covering, and so does a
  still: a ``CutDeck_Hold_*`` PNG (20261110 covers 39 cuts with a slideshow of them) or a footage
  clip with Premiere's Frame Hold (``frame_hold`` from the reader), which shows one frozen frame.

Every condition that makes a value unusable becomes a string in ``problems``; nothing is guessed.

    python -m cutdeck.hks_gold "G:\\Me\\Works\\20261120 - โหนกระแส"
    python -m cutdeck.hks_gold --all G:\\Me\\Works
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import ntpath
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from cutdeck.prproj_reader import read_project

FRAME = 0.04  # 25 fps
HALF = FRAME / 2
HOOK_SFX = "transition complex 14"
HOLDOUT = ("20261002", "20261109", "20261118")  # never tuned on; scored once, at the end (step 0.6)
HOLD = "cutdeck_hold_"  # CutDeck frame-hold stills: a full-frame picture that is not the footage
OUTPUTS = {"yt": "1 YOUTUBE", "fb": "2 FACEBOOK", "square": "3 SQUARE SELECT"}
EDIT_SEQUENCE = "Edit"


@dataclass(frozen=True)
class SourceRange:
    media: str
    source_in: float
    source_out: float
    tl_start: float
    tl_end: float


@dataclass(frozen=True)
class Cut:
    tl: float
    jump: float | None  # next.source_in - prev.source_out; None across media
    covered: bool


@dataclass(frozen=True)
class OutputCut:
    sequence: str
    length: float  # last clip end in the sequence (the YouTube pool included)
    show_end: float  # last end of a non-footage clip: where the output really ends
    hook_end: float | None
    keeps: list[SourceRange]
    covers: list[SourceRange]
    cuts: list[Cut]


@dataclass(frozen=True)
class DayGold:
    folder: str
    project: str | None
    footage: list[str]
    durations: dict[str, float | None]
    clock: dict[str, float | None] | None
    edit_drops: list[tuple[float, float]] | None
    yt: OutputCut | None
    fb: OutputCut | None
    square: OutputCut | None
    problems: list[str]


def _media(clip: dict) -> str:
    return ntpath.basename(clip.get("media_path") or "")


def _clips(seq: dict, kind: str):
    for track in seq[f"{kind}_tracks"]:
        for clip in track["clips"]:
            yield track, clip


def _non_empty(seq: dict) -> bool:
    return any(t["clips"] for t in seq["video_tracks"] + seq["audio_tracks"])


def _pick(project: dict, label: str, match, problems: list[str]) -> dict | None:
    """The one non-empty sequence ``match`` accepts. Identical non-empty copies count as one."""
    found = [s for s in project["sequences"] if match(s["name"]) and _non_empty(s)]
    if not found:
        problems.append(f"{label}: no non-empty sequence")
        return None
    if any((s["video_tracks"], s["audio_tracks"]) != (found[0]["video_tracks"], found[0]["audio_tracks"])
           for s in found[1:]):
        names = ", ".join(repr(s["name"]) for s in found)
        problems.append(f"{label}: {len(found)} non-empty sequences differ ({names})")
        return None
    return found[0]


def edit_drops(project: dict, problems: list[str]) -> list[tuple[float, float]] | None:
    """The ``Edit`` sequence's V1 pieces (drops; keepers sit on V2), merged where they touch.
    None when the day has no ``Edit`` sequence; that is normal, not a problem."""
    if not any(s["name"] == EDIT_SEQUENCE and _non_empty(s) for s in project["sequences"]):
        return None
    seq = _pick(project, EDIT_SEQUENCE, lambda n: n == EDIT_SEQUENCE, problems)
    if seq is None:
        return None
    moved = [c for _, c in _clips(seq, "video") if abs(c["start"] - c["source_in"]) > HALF]
    if moved:
        problems.append(f"{EDIT_SEQUENCE}: {len(moved)} clips not at their source time; drops are timeline times")
    v1 = next((t for t in seq["video_tracks"] if t["index"] == 0), None)
    drops: list[list[float]] = []
    for c in sorted(v1["clips"] if v1 else [], key=lambda c: c["start"]):
        if drops and c["start"] - drops[-1][1] <= HALF:
            drops[-1][1] = max(drops[-1][1], c["end"])
        else:
            drops.append([c["start"], c["end"]])
    return [(a, b) for a, b in drops]


def _range(clip: dict) -> SourceRange:
    return SourceRange(_media(clip), clip["source_in"], clip["source_out"], clip["start"], clip["end"])


def _offset(r: SourceRange) -> float:
    return r.tl_start - r.source_in


def _framing(clip: dict) -> tuple:
    """On-screen width and position; a zoomed insert of the same footage is not the main shot.
    Width is scale x source width, so a 1280-wide file at 150 % matches a 1920-wide one at the
    default 100 % (20261112 mixes both). Premiere leaves Motion out at its defaults."""
    motion = next((e["params"] for e in clip["effects"] if e.get("match_name") == "AE.ADBE Motion"), {})
    keyed = any(p.get("keyframes") for p in motion.values())
    scale = motion.get("scale", {}).get("value", 100.0)
    position = motion.get("position", {}).get("value", (0.5, 0.5))
    width = (clip.get("source_frame") or [None])[0]
    return (None if width is None else round(scale * width / 100),
            tuple(round(p, 3) for p in position), keyed)


def _still(clip: dict) -> bool:
    return "frame_hold" in clip or _media(clip).lower().startswith(HOLD)


def _synced(picture: SourceRange | None, keep: SourceRange) -> bool:
    return (picture is not None and picture.media == keep.media
            and abs(_offset(picture) - _offset(keep)) <= HALF)


def output_cut(seq: dict, footage: set[str], label: str, problems: list[str],
               min_jump_frames: int = 1) -> OutputCut | None:
    """Keeps, covers and cuts of one output sequence. ``footage`` holds lower-case basenames."""
    def is_footage(clip: dict) -> bool:
        return _media(clip).lower() in footage

    everything = [c for kind in ("video", "audio") for _, c in _clips(seq, kind)]
    other = [c for c in everything if not is_footage(c)]
    if not other:
        problems.append(f"{label}: no non-footage clip, so no show end")
        return None
    show_end = max(c["end"] for c in other)
    hooks = [c["start"] for c in everything
             if HOOK_SFX in f"{c['name'] or ''} {_media(c)}".lower() and c["start"] < show_end]
    hook_end = min(hooks) if hooks else None
    if hook_end is None:
        problems.append(f"{label}: no 'Transition Complex 14' SFX, so no hook end")

    def live(clip: dict) -> bool:
        return is_footage(clip) and not clip["disabled"] and clip["start"] < show_end

    by_track = {t["index"]: sorted((_range(c) for c in t["clips"] if live(c)), key=lambda r: r.tl_start)
                for t in seq["audio_tracks"]}
    by_track = {i: rs for i, rs in by_track.items() if rs}
    if not by_track:
        problems.append(f"{label}: no footage audio before the show end {show_end:.2f}")
        return None
    if len(by_track) > 1:
        problems.append(f"{label}: footage audio on tracks A{', A'.join(str(i + 1) for i in by_track)}; "
                        "cuts use the longest one")
    dialogue = max(by_track.values(), key=lambda rs: sum(r.tl_end - r.tl_start for r in rs))
    keeps = sorted((r for rs in by_track.values() for r in rs), key=lambda r: r.tl_start)

    # Topmost first: the picture at a time is the first footage clip or still covering it.
    # A still has no framing: it is never the moving main shot.
    pictures = [(_range(c), None if _still(c) else _framing(c))
                for t in sorted(seq["video_tracks"], key=lambda t: -t["index"]) if not t["muted"]
                for c in t["clips"] if not c["disabled"] and (is_footage(c) or _still(c))]

    def picture(at: float) -> tuple[SourceRange | None, tuple | None]:
        return next(((r, f) for r, f in pictures if r.tl_start <= at < r.tl_end), (None, None))

    cuts = []
    for prev, nxt in zip(dialogue, dialogue[1:]):
        jump = nxt.source_in - prev.source_out if nxt.media == prev.media else None
        if jump is not None and (abs(round(jump / FRAME)) < min_jump_frames
                                 or abs(_offset(nxt) - _offset(prev)) <= HALF):
            continue
        before, frame_before = picture(prev.tl_end - HALF)
        after, frame_after = picture(nxt.tl_start + HALF)
        # The main shot jumps only if both sides show their own audio's picture, framed alike.
        uncovered = (frame_before is not None and frame_before == frame_after
                     and _synced(before, prev) and _synced(after, nxt))
        cuts.append(Cut(nxt.tl_start, jump, not uncovered))

    covers = [r for r, framing in pictures if r.tl_start < show_end
              and (framing is None or not any(_synced(r, k) for k in keeps
                                              if min(r.tl_end, k.tl_end) - max(r.tl_start, k.tl_start) > HALF))]
    return OutputCut(
        sequence=seq["name"],
        length=max(c["end"] for c in everything),
        show_end=show_end,
        hook_end=hook_end,
        keeps=keeps,
        covers=sorted(covers, key=lambda r: r.tl_start),
        cuts=cuts,
    )


def gold_from_project(project: dict, footage: list[str], *, folder: str = "",
                      min_jump_frames: int = 1) -> DayGold:
    """Pure core: a ``read_project`` dict plus the day's footage basenames -> DayGold."""
    problems: list[str] = []
    names = {f.lower() for f in footage}
    outputs = {}
    for key, prefix in OUTPUTS.items():
        seq = _pick(project, prefix, lambda n, p=prefix: n.startswith(p) and "Copy" not in n, problems)
        outputs[key] = seq and output_cut(seq, names, seq["name"], problems, min_jump_frames)
    return DayGold(
        folder=folder,
        project=project.get("path"),
        footage=list(footage),
        durations={},
        clock=None,
        edit_drops=edit_drops(project, problems),
        problems=problems,
        **outputs,
    )


def body(out: OutputCut) -> tuple[list[SourceRange], list[Cut]]:
    """Keeps and cuts after the hook (the whole output when there is no hook)."""
    start = out.hook_end if out.hook_end is not None else float("-inf")
    keeps = [k for k in out.keeps if k.tl_start >= start]
    first = keeps[0].tl_start if keeps else float("inf")
    return keeps, [c for c in out.cuts if c.tl > first]


# --- file system shell -------------------------------------------------------------------------

def is_holdout(folder: str | Path) -> bool:
    return Path(folder).name[:8] in HOLDOUT


def day_folders(root: str | Path) -> tuple[list[Path], list[Path]]:
    """The day folders under ``root`` as (tuning, holdout)."""
    days = sorted(Path(root).glob("*โหนกระแส"))
    return [d for d in days if not is_holdout(d)], [d for d in days if is_holdout(d)]


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def read_day(folder: str | Path, *, clock: bool = False, min_jump_frames: int = 1) -> DayGold:
    folder = Path(folder)
    problems: list[str] = []
    footage = sorted((p for p in (folder / "1. FOOTAGE").glob("*") if p.suffix.lower() == ".mp4"),
                     key=lambda p: p.name)
    if not footage:
        problems.append("no .mp4 in 1. FOOTAGE")
    projects = sorted((folder / "4. PROJECTS" / "1. PREMIERE PRO").glob("*.prproj"))
    gold = DayGold(str(folder), None, [p.name for p in footage], {}, None, None, None, None, None, [])
    if len(projects) != 1:
        problems.append(f"{len(projects)} .prproj files in 4. PROJECTS/1. PREMIERE PRO, need exactly 1")
    else:
        try:
            project = read_project(projects[0])
        except Exception as e:  # an unreadable project is a row in the table, not a crash
            problems.append(f"read_project failed: {e!r}")
        else:
            gold = gold_from_project(project, gold.footage, folder=str(folder),
                                     min_jump_frames=min_jump_frames)
            problems += gold.problems

    durations = {}
    for p in footage:
        try:
            durations[p.name] = _duration(p)
        except (OSError, subprocess.CalledProcessError, ValueError) as e:
            durations[p.name] = None
            problems.append(f"ffprobe failed on {p.name}: {e!r}")

    fractions = None
    if clock:
        try:
            from cutdeck.hks_clock import clock_fraction
        except ImportError:
            problems.append("--clock: cutdeck.hks_clock is not available")
        else:
            fractions = {}
            for p in footage:
                try:
                    fractions[p.name] = clock_fraction(str(p))
                except Exception as e:  # the clock reader is another worker's; record, don't crash
                    fractions[p.name] = None
                    problems.append(f"clock_fraction failed on {p.name}: {e!r}")
    return dataclasses.replace(gold, durations=durations, clock=fractions, problems=problems)


def _row(day: DayGold) -> dict:
    row = {"folder": Path(day.folder).name[:8], "footage": len(day.footage)}
    yt = day.yt
    if yt is not None:
        keeps, cuts = body(yt)
        covered = sum(c.covered for c in cuts)
        row.update({
            "yt_len": f"{yt.show_end:.2f}",
            "hook": "-" if yt.hook_end is None else f"{yt.hook_end:.2f}",
            "body_keeps_s": f"{sum(k.tl_end - k.tl_start for k in keeps):.2f}",
            "cuts": len(cuts), "covered": covered, "uncovered": len(cuts) - covered,
        })
    for key in ("fb", "square"):
        out = getattr(day, key)
        row[f"{key}_len"] = "-" if out is None else f"{out.show_end:.2f}"
    row["problems"] = "; ".join(day.problems) or "-"
    return row


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Read the user's HKS editing decisions from a day folder.")
    p.add_argument("folder", help="a day folder, or with --all the folder that holds them")
    p.add_argument("--all", action="store_true", help="one table row per *โหนกระแส folder")
    p.add_argument("--clock", action="store_true", help="also measure TV-clock presence (slow)")
    p.add_argument("--min-jump-frames", type=int, default=1,
                   help="ignore source jumps shorter than this many frames (default 1)")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if not args.all:
        day = read_day(args.folder, clock=args.clock, min_jump_frames=args.min_jump_frames)
        json.dump(dataclasses.asdict(day), sys.stdout, ensure_ascii=False, indent=2)
        print()
        return
    cols = ["folder", "footage", "yt_len", "hook", "body_keeps_s", "cuts", "covered", "uncovered",
            "fb_len", "square_len", "problems"]
    print(" | ".join(cols))
    for folder in sorted(Path(args.folder).glob("*โหนกระแส")):
        row = _row(read_day(folder, clock=args.clock, min_jump_frames=args.min_jump_frames))
        print(" | ".join(str(row.get(c, "-")) for c in cols))


if __name__ == "__main__":
    main()
