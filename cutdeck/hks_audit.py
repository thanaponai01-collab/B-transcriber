"""hks_audit.py — do the HKS rules learned on 20261120 hold on the other episodes? (step 0.3)

Measures, never changes a rule. Four rules (docs/HKS_BUILD_PLAN.md, step 0.3):

1. No jump cuts: an uncovered cut in the YT body is allowed only on a camera change. The test
   compares the source frame just before the cut with the one just after, both scaled to
   1280x720: a mean absolute RGB difference of ``CAMERA_CHANGE`` or more is a camera change.
   Below it the number cannot tell a still picture, a camera change inside the small studio
   inset of the news-clip layout, and a real same-shot jump apart, so those cuts are listed for
   a look at the frames.
2. Lengths: YT 15-20 min, FB = 179.96 s, 1-min = 59.96 s (reader values and the exported files).
3. Bumpers dropped: inside the TV part, a run of 10 s or more with the clock off is a
   bumper/VTR/graphic candidate. Counts the kept YT seconds that fall in one. Sponsors are not
   checked (they need step 2.7).
4. Blur wherever the clock shows: the YT body sampled every second. The visible picture is the
   topmost enabled footage clip or CutDeck frame hold; a framing wider than the main shot (a
   zoomed insert) pushes the clock off screen. Blur is on when a Gaussian Blur clip spans the
   time on that track or above (an adjustment layer blurs only what is below it).

Model check: every 10 s of the YT body, the picture the reader says is showing (placed by its
Motion scale and position) is compared with the frame of the exported file. A sample that
differs by ``MODEL_DIFF`` or more is listed: the reader's picture there is not what was exported.

The TV clock is read once per file at 1 fps and cached (``--cache``), so a second run is fast.

The holdout episodes (``hks_gold.HOLDOUT``, step 0.6) are left out unless ``--holdout`` is given;
then they get their own tables, never mixed with the tuning set.

    python -m cutdeck.hks_audit --all G:\\Me\\Works [--cache DIR] [--holdout]
"""

from __future__ import annotations

import argparse
import json
import ntpath
import re
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from cutdeck.hks_clock import CROP_H, CROP_W, CROP_X, CROP_Y, clock_in_frame, grab_crop
from cutdeck.hks_gold import (FRAME, HALF, HOLD, _framing, _non_empty, body, day_folders, is_holdout,
                              read_day)
from cutdeck.prproj_reader import read_project

CAMERA_CHANGE = 20.0  # mean |RGB difference| at 1280x720; set in docs/HKS_RULE_AUDIT.md, rule 1
MIN_DIP_S = 10        # a clock-off run this long inside the TV part is a bumper candidate
MIN_TV_RUN_S = 30     # the TV part ends with the last clock-on run at least this long
MODEL_STEP_S = 10     # spacing of the model-against-export samples
MODEL_DIFF = 30.0     # export frame vs the reader's picture: this far apart is a different picture
BLUR = "AE.ADBE Gaussian Blur 2"


# --- pure parts ----------------------------------------------------------------------------------

def frame_diff(a: np.ndarray, b: np.ndarray) -> float:
    """Mean absolute RGB difference of two same-sized frames (0-255)."""
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


def is_camera_change(diff: float, threshold: float = CAMERA_CHANGE) -> bool:
    return diff >= threshold


def runs(flags, value: bool, min_len: int = 1) -> list[tuple[int, int]]:
    """Half-open index runs ``[a, b)`` where ``flags`` equals ``value`` for at least ``min_len``."""
    out, start = [], None
    for i, f in enumerate([*flags, not value]):
        if bool(f) == value and start is None:
            start = i
        elif bool(f) != value and start is not None:
            if i - start >= min_len:
                out.append((start, i))
            start = None
    return out


def tv_part(clock, min_run: int = MIN_TV_RUN_S) -> tuple[int, int] | None:
    """Seconds ``[first clock-on, end of the last clock-on run of min_run s)``, or None."""
    on = runs(clock, True)
    sustained = [r for r in on if r[1] - r[0] >= min_run]
    return (on[0][0], sustained[-1][1]) if sustained else None


def dips(clock, part: tuple[int, int], min_len: int = MIN_DIP_S) -> list[tuple[int, int]]:
    """Clock-off runs of ``min_len`` s or more inside the TV part."""
    a, b = part
    return [(a + s, a + e) for s, e in runs(clock[a:b], False, min_len)]


def overlap(spans: list[tuple[float, float]], a: float, b: float) -> float:
    return sum(max(0.0, min(b, e) - max(a, s)) for s, e in spans)


@dataclass(frozen=True)
class Layer:
    """One enabled clip on a visible video track, as far as the picture is concerned."""
    track: int
    start: float
    end: float
    kind: str  # "footage", "hold" (frame-hold still) or "other" (overlays, graphics, adjustments)
    media: str
    path: str
    source_in: float
    framing: tuple
    blur: bool
    hold_at: float | None = None  # Premiere Frame Hold: the one source second this clip shows

    def source_at(self, t: float) -> float:
        return self.source_in + (t - self.start) if self.hold_at is None else self.hold_at


def layers(seq: dict, footage: set[str]) -> list[Layer]:
    """Enabled clips on visible video tracks, topmost track first."""
    out = []
    for track in sorted(seq["video_tracks"], key=lambda t: -t["index"]):
        if track["muted"]:
            continue
        for c in track["clips"]:
            if c["disabled"]:
                continue
            media = ntpath.basename(c.get("media_path") or "")
            kind = ("footage" if media.lower() in footage
                    else "hold" if media.lower().startswith(HOLD) else "other")
            blur = any(e.get("match_name") == BLUR and not e.get("bypass") for e in c["effects"])
            out.append(Layer(track["index"], c["start"], c["end"], kind, media, c.get("media_path") or "",
                             c["source_in"], _framing(c), blur, c.get("frame_hold")))
    return out


def picture_at(ls: list[Layer], t: float) -> Layer | None:
    """The topmost footage clip or frame hold showing at ``t``."""
    return next((l for l in ls if l.kind != "other" and l.start <= t < l.end), None)


def blurred_at(ls: list[Layer], t: float, track: int) -> bool:
    """A Gaussian Blur clip spans ``t`` on ``track`` or above."""
    return any(l.blur and l.track >= track and l.start <= t < l.end for l in ls)


def main_framing(ls: list[Layer], start: float, end: float) -> tuple | None:
    """The footage framing shown longest in ``[start, end)``: the main shot."""
    seconds = Counter()
    for l in ls:
        if l.kind == "footage":
            seconds[l.framing] += max(0.0, min(end, l.end) - max(start, l.start))
    return seconds.most_common(1)[0][0] if seconds else None


def wider(framing: tuple, main: tuple) -> bool:
    return framing[0] is not None and main[0] is not None and framing[0] > main[0]


def blur_samples(ls: list[Layer], clock_of, start: float, end: float, step: float = 1.0) -> list[dict]:
    """One row per ``step`` s in ``[start, end)``: what shows and whether it is blurred.
    ``clock_of(layer, t)`` -> clock on in that layer's picture at timeline ``t`` (None = unknown).
    ``state`` is clock / zoomed / no-clock / unknown / none."""
    main = main_framing(ls, start, end)
    rows = []
    t = start + step / 2
    while t < end:
        pic = picture_at(ls, t)
        if pic is None:
            state, blurred = "none", blurred_at(ls, t, 0)
        else:
            blurred = blurred_at(ls, t, pic.track)
            if main is not None and wider(pic.framing, main):
                state = "zoomed"
            else:
                on = clock_of(pic, t)
                state = "unknown" if on is None else "clock" if on else "no-clock"
        rows.append({"t": round(t, 3), "state": state, "blurred": blurred,
                     "kind": None if pic is None else pic.kind})
        t += step
    return rows


def placed(frame: np.ndarray, framing: tuple, seq_width: int) -> np.ndarray:
    """A full source frame as the sequence shows it under Motion scale and position (anchor at
    the centre, no rotation), on black, at the size of ``frame``."""
    h, w = frame.shape[:2]
    k = 1.0 if framing[0] is None else framing[0] / seq_width
    pic = Image.fromarray(frame).resize((max(1, round(w * k)), max(1, round(h * k))))
    out = Image.new("RGB", (w, h))
    out.paste(pic, (round(framing[1][0] * w - pic.width / 2), round(framing[1][1] * h - pic.height / 2)))
    return np.asarray(out)


def spans_of(times: list[float], step: float = 1.0) -> list[tuple[float, float]]:
    """Sample midpoints -> merged ``[start, end)`` ranges, each sample covering ``step``."""
    out: list[list[float]] = []
    for t in sorted(times):
        a, b = t - step / 2, t + step / 2
        if out and a - out[-1][1] <= 1e-6:
            out[-1][1] = b
        else:
            out.append([a, b])
    return [(round(a, 2), round(b, 2)) for a, b in out]


# --- ffmpeg shell --------------------------------------------------------------------------------

def _key(path: str) -> str:
    p = Path(path)
    return f"{re.sub(r'[^A-Za-z0-9]+', '_', p.stem)[:40]}_{p.stat().st_size}"


def clock_track(path: str, cache: Path) -> np.ndarray:
    """Clock on/off for each second of ``path`` (index i = the frame nearest i s), cached."""
    out = cache / f"{_key(path)}.clock.npy"
    if out.exists():
        return np.load(out)
    vf = f"fps=1,scale=1280:720,crop={CROP_W}:{CROP_H}:{CROP_X}:{CROP_Y}"
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-vf", vf, "-f", "rawvideo",
                             "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    size = CROP_W * CROP_H * 3
    flags = []
    while len(buf := proc.stdout.read(size)) == size:
        flags.append(clock_in_frame(np.frombuffer(buf, np.uint8).reshape(CROP_H, CROP_W, 3)))
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed reading {path}")
    track = np.array(flags, bool)
    cache.mkdir(parents=True, exist_ok=True)
    np.save(out, track)
    return track


def grab_frame(path: str, t: float) -> np.ndarray | None:
    """The first frame at or after ``t`` s, scaled to 1280x720 RGB."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(t, 0):.3f}", "-i", path, "-frames:v", "1",
                          "-vf", "scale=1280:720", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(720, 1280, 3) if len(raw) == 1280 * 720 * 3 else None


class DiffCache:
    """Frame differences by (file, time, time), kept in one JSON file."""

    def __init__(self, cache: Path):
        self.file = cache / "diffs.json"
        self.data = json.loads(self.file.read_text()) if self.file.exists() else {}

    def get(self, key: str, compute) -> float | None:
        if key not in self.data:
            self.data[key] = compute()
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.write_text(json.dumps(self.data))
        return self.data[key]

    def diff(self, path_a: str, t_a: float, path_b: str, t_b: float, place=lambda frame: frame,
             tag: str = "") -> float | None:
        """Frame difference of a@t_a and ``place``(b@t_b); ``tag`` names the placement in the key."""
        def compute():
            a, b = grab_frame(path_a, t_a), grab_frame(path_b, t_b)
            return None if a is None or b is None else round(frame_diff(a, place(b)), 2)
        return self.get(f"{_key(path_a)}@{t_a:.3f}|{_key(path_b)}@{t_b:.3f}{tag}", compute)


def latest_export(folder: Path, kind: str) -> Path | None:
    """The export ``… <kind> D<n>.mp4`` with the highest n (20261003 says ``REEL YT``)."""
    found = [(int(m.group(1)), p) for p in (folder / "5. EXPORTS").glob("*.mp4")
             if (m := re.search(rf"\b{kind} D(\d+)\.mp4$", p.name))]
    return max(found)[1] if found else None


def _duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


# --- one day folder ------------------------------------------------------------------------------

def _neighbours(keeps, tl: float):
    """The keep that starts at cut ``tl`` and the keep that ends nearest before it."""
    nxt = min(keeps, key=lambda k: abs(k.tl_start - tl))
    before = [k for k in keeps if k.tl_start < tl - HALF and k is not nxt]
    prev = min(before, key=lambda k: abs(k.tl_end - tl))
    return prev, nxt


def audit_day(folder: Path, cache: Path, diffs: DiffCache) -> dict:
    gold = read_day(folder)
    yt = gold.yt
    project = read_project(gold.project)
    seq = next(s for s in project["sequences"] if s["name"] == yt.sequence and _non_empty(s))
    paths = {name.lower(): str(folder / "1. FOOTAGE" / name) for name in gold.footage}
    ls = layers(seq, set(paths))
    export = latest_export(folder, "YT")
    keeps, cuts = body(yt)
    day = {"folder": folder.name[:8], "problems": gold.problems}

    # Rule 1: uncovered cuts in the YT body.
    rows = []
    for cut in (c for c in cuts if not c.covered):
        prev, nxt = _neighbours(yt.keeps, cut.tl)
        t_before, t_after = prev.source_out - 1.5 * FRAME, nxt.source_in - HALF
        rows.append({
            "tl": round(cut.tl, 2), "jump": None if cut.jump is None else round(cut.jump, 2),
            "src_before": round(prev.source_out, 2), "src_after": round(nxt.source_in, 2),
            "diff": diffs.diff(paths[prev.media.lower()], t_before, paths[nxt.media.lower()], t_after),
            "export_diff": None if export is None else
            diffs.diff(str(export), cut.tl - 1.5 * FRAME, str(export), cut.tl - HALF),
        })
    day["cuts"] = {"body_cuts": len(cuts), "uncovered": rows}

    # Rule 2: lengths, from the reader and from the latest exported files.
    day["lengths"] = {
        "yt": yt.show_end, "yt_body": yt.show_end - (yt.hook_end or 0.0),
        "body_keeps": sum(k.tl_end - k.tl_start for k in keeps),
        "fb": gold.fb and gold.fb.show_end, "square": gold.square and gold.square.show_end,
        **{f"export_{k}": (p := latest_export(folder, kind)) and round(_duration(p), 2)
           for k, kind in (("yt", "YT"), ("fb", "FB"), ("square", "REEL 1M"))},
    }

    # Rule 3: kept YT seconds inside clock-off dips of each footage file's TV part.
    clocks = {name: clock_track(p, cache) for name, p in paths.items()}
    files = []
    for name, clock in clocks.items():
        part = tv_part(clock)
        if part is None:
            files.append({"file": name, "tv_part": None})
            continue
        found = dips(clock, part)
        mine = [k for k in yt.keeps if k.media.lower() == name]
        covers = [c for c in yt.covers if c.media.lower() == name]
        files.append({
            "file": name, "tv_part": part, "dips": found, "seconds": len(clock),
            "late_clock_on": int(clock[part[1]:].sum()),
            "head_kept": overlap([(k.source_in, k.source_out) for k in mine], 0, part[0]),
            "dip_kept": [(a, b, round(overlap([(k.source_in, k.source_out) for k in mine], a, b), 2))
                         for a, b in found],
            "dip_cover": [(a, b, round(overlap([(c.source_in, c.source_out) for c in covers], a, b), 2))
                          for a, b in found],
        })
    day["dips"] = files

    # Rule 4: blur wherever the clock shows, in the YT body.
    holds: dict[str, bool | None] = {}

    def clock_of(layer: Layer, t: float) -> bool | None:
        if layer.kind == "hold":
            if layer.path not in holds:
                crop = grab_crop(layer.path, 0) if Path(layer.path).exists() else None
                holds[layer.path] = None if crop is None else clock_in_frame(crop)
            return holds[layer.path]
        clock = clocks[layer.media.lower()]
        s = round(layer.source_at(t))
        return bool(clock[s]) if 0 <= s < len(clock) else None

    start = yt.hook_end or 0.0
    samples = blur_samples(ls, clock_of, start, yt.show_end)
    seen = clock_track(str(export), cache) if export is not None else None
    for r in samples:
        s = int(r["t"])
        r["export_clock"] = None if seen is None or s >= len(seen) else bool(seen[s])
    day["blur"] = {"start": start, "end": yt.show_end, "main_framing": main_framing(ls, start, yt.show_end),
                   "samples": samples}

    # Model check: the reader's picture, placed by its Motion, against the exported frame.
    model = []
    t = start + MODEL_STEP_S / 2
    while export is not None and t < yt.show_end:
        pic = picture_at(ls, t)
        if pic is not None and (pic.kind == "footage" or Path(pic.path).exists()):
            source, at = (pic.path, 0.0) if pic.kind == "hold" else (paths[pic.media.lower()], pic.source_at(t))
            model.append({
                "t": t, "track": pic.track, "kind": pic.kind, "held": pic.hold_at is not None,
                "keyed": pic.framing[2], "source": round(at, 2),
                "above": sorted({l.media for l in ls if l.kind == "other" and l.track > pic.track
                                 and l.start <= t < l.end}),
                "diff": diffs.diff(str(export), t, source, at,
                                   lambda frame, f=pic.framing: placed(frame, f, seq["frame"][0]), f"|{pic.framing}"),
            })
        t += MODEL_STEP_S
    day["model"] = model
    return day


# --- report --------------------------------------------------------------------------------------

def _f(x, nd=2):
    return "-" if x is None else f"{x:.{nd}f}" if isinstance(x, float) else str(x)


def rule1(days: list[dict]) -> list[str]:
    out = ["| episode | body cuts | uncovered (reader) | camera change | "
           f"diff below {CAMERA_CHANGE:g} (eye check) |", "|---|---|---|---|---|"]
    detail = []
    for d in days:
        rows = d["cuts"]["uncovered"]
        change = [r for r in rows if r["diff"] is not None and is_camera_change(r["diff"])]
        low = [r for r in rows if r not in change]
        out.append(f"| {d['folder']} | {d['cuts']['body_cuts']} | {len(rows)} | {len(change)} | {len(low)} |")
        for r in low:
            detail.append(f"| {d['folder']} | {r['tl']:.2f} | {_f(r['jump'])} | {r['src_before']:.2f} → "
                          f"{r['src_after']:.2f} | {_f(r['diff'], 1)} | {_f(r['export_diff'], 1)} |")
    return out + ["", f"Uncovered cuts with a frame difference below {CAMERA_CHANGE:g} (look at each one):", "",
                  "| episode | tl | jump s | source | diff | export diff |", "|---|---|---|---|---|---|", *detail]


def rule2(days: list[dict]) -> list[str]:
    out = ["| episode | YT total | YT body (after hook) | body keeps | FB | 1-min | export YT | export FB | "
           "export 1M |", "|---|---|---|---|---|---|---|---|---|"]
    for d in days:
        n = d["lengths"]
        out.append(f"| {d['folder']} | {n['yt']:.2f} ({n['yt'] / 60:.1f} min) | {n['yt_body']:.2f} "
                   f"({n['yt_body'] / 60:.1f} min) | {n['body_keeps']:.2f} | {_f(n['fb'])} | {_f(n['square'])} | "
                   f"{_f(n['export_yt'])} | {_f(n['export_fb'])} | {_f(n['export_square'])} |")
    return out


def rule3(days: list[dict]) -> list[str]:
    out = ["| episode | file | TV part (s) | clock-on after it (s) | dips ≥10 s | dip seconds | "
           "kept audio in dips (s) | cover picture in dips (s) | kept before first clock (s) |",
           "|---|---|---|---|---|---|---|---|---|"]
    detail = []
    for d in days:
        for f in d["dips"]:
            if f["tv_part"] is None:
                out.append(f"| {d['folder']} | {f['file'][:24]} | no clock | | | | | | |")
                continue
            kept = sum(x[2] for x in f["dip_kept"])
            cover = sum(x[2] for x in f["dip_cover"])
            out.append(f"| {d['folder']} | {f['file'][:24]} | {f['tv_part'][0]}–{f['tv_part'][1]} | "
                       f"{f['late_clock_on']} | {len(f['dips'])} | {sum(b - a for a, b in f['dips'])} | "
                       f"{kept:.2f} | {cover:.2f} | {f['head_kept']:.2f} |")
            for (a, b, k), (_, _, c) in zip(f["dip_kept"], f["dip_cover"]):
                detail.append(f"| {d['folder']} | {f['file'][:24]} | {a}–{b} | {k:.2f} | {c:.2f} |")
    return out + ["", "Every dip (source seconds):", "",
                  "| episode | file | dip | kept audio s | cover picture s |", "|---|---|---|---|---|", *detail]


def rule4(days: list[dict]) -> list[str]:
    out = ["| episode | body s | clock on screen s | blurred | unblurred | zoomed (clock pushed off) | "
           "blur without clock | unknown/none | export: clock seen s |",
           "|---|---|---|---|---|---|---|---|---|"]
    detail = []
    for d in days:
        rows = d["blur"]["samples"]
        clock = [r for r in rows if r["state"] == "clock"]
        blurred = sum(r["blurred"] for r in clock)
        extra = [r for r in rows if r["state"] in ("no-clock", "zoomed") and r["blurred"]]
        other = sum(r["state"] in ("unknown", "none") for r in rows)
        seen = [r for r in rows if r["export_clock"]]
        share = f"{blurred} ({100 * blurred / len(clock):.0f} %)" if clock else "-"
        out.append(f"| {d['folder']} | {len(rows)} | {len(clock)} | {share} | {len(clock) - blurred} | "
                   f"{sum(r['state'] == 'zoomed' for r in rows)} | {len(extra)} | {other} | {len(seen)} |")
        for label, picked in (("unblurred clock", [r for r in clock if not r["blurred"]]),
                              ("blur, no clock", [r for r in extra if r["state"] == "no-clock"]),
                              ("blur, zoomed", [r for r in extra if r["state"] == "zoomed"]),
                              ("export shows clock", seen)):
            spans = spans_of([r["t"] for r in picked])
            if spans:
                text = ", ".join(f"{a:.0f}–{b:.0f}" for a, b in spans[:12])
                more = f" (+{len(spans) - 12} more)" if len(spans) > 12 else ""
                detail.append(f"| {d['folder']} | {label} | {len(picked)} | {text}{more} |")
    return out + ["", "Ranges (timeline seconds):", "", "| episode | kind | s | ranges |", "|---|---|---|---|",
                  *detail]


def model_check(days: list[dict]) -> list[str]:
    out = [f"| episode | samples | median diff | diff ≥ {MODEL_DIFF:g} |", "|---|---|---|---|"]
    detail = []
    for d in days:
        rows = [r for r in d["model"] if r["diff"] is not None]
        off = [r for r in rows if r["diff"] >= MODEL_DIFF]
        out.append(f"| {d['folder']} | {len(rows)} | {_f(float(np.median([r['diff'] for r in rows])), 1) if rows else '-'} "
                   f"| {len(off)} |")
        for r in off:
            what = r["kind"] + (", held frame" if r["held"] else "") + (", keyframed Motion" if r["keyed"] else "")
            detail.append(f"| {d['folder']} | {r['t']:.0f} | {r['diff']:.1f} | V{r['track'] + 1} {what} | "
                          f"{r['source']:.2f} | {', '.join(r['above']) or '-'} |")
    return out + ["", f"Samples at {MODEL_DIFF:g} or more:", "",
                  "| episode | tl | diff | reader's picture | source s | layers above it |", "|---|---|---|---|---|---|",
                  *detail]


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Audit the HKS rules across past day folders.")
    p.add_argument("folder", help="a day folder, or with --all the folder that holds them")
    p.add_argument("--all", action="store_true", help="every *โหนกระแส folder of the tuning set")
    p.add_argument("--holdout", action="store_true",
                   help="also report the holdout episodes, in their own tables (end-of-step scoring only)")
    p.add_argument("--cache", default=str(Path(tempfile.gettempdir()) / "hks_audit"),
                   help="where clock tracks and frame differences are cached")
    p.add_argument("--json", help="also write the raw per-day results here")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    cache = Path(args.cache)
    if args.all:
        tuning, held = day_folders(args.folder)
        groups = [("Tuning set", tuning)] + ([("Holdout", held)] if args.holdout else [])
    elif is_holdout(args.folder) and not args.holdout:
        p.error(f"{Path(args.folder).name[:8]} is a holdout episode; pass --holdout to report it")
    else:
        groups = [("Holdout" if is_holdout(args.folder) else "Tuning set", [Path(args.folder)])]
    diffs = DiffCache(cache)
    audited = []
    for group, folders in groups:
        days = []
        for folder in folders:
            print(f"... {folder.name}", file=sys.stderr, flush=True)
            days.append({**audit_day(folder, cache, diffs), "holdout": group == "Holdout"})
        audited.append((group, days))
    if args.json:
        Path(args.json).write_text(json.dumps([d for _, days in audited for d in days], ensure_ascii=False,
                                              indent=1), encoding="utf-8")
    for group, days in audited:
        print(f"\n# {group} ({len(days)} episodes)")
        for title, fn in (("Rule 1: no jump cuts", rule1), ("Rule 2: lengths", rule2),
                          ("Rule 3: bumpers dropped (clock dips)", rule3),
                          ("Rule 4: blur wherever the clock shows", rule4),
                          ("Model check: the reader's picture against the export", model_check)):
            print(f"\n## {title}\n")
            print("\n".join(fn(days)))


if __name__ == "__main__":
    main()
