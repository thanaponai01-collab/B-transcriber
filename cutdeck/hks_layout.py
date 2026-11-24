"""HKS build plan step 2.4: the picture layout of every second of a footage file.

Four kinds (the ``layout`` section of ``episode.json``, ``cutdeck/hks_episode.py``):

  * ``studio``   a studio camera fills the frame; a change of shot here is a real cut point;
  * ``clip``     windows over the show's blue frame: a news clip with the host in a small inset,
                 or the phone-call layout (studio box and caller photo);
  * ``footage``  a full-frame picture that is not the studio: CCTV or a field shot, a photo, a chat
                 screenshot, a map;
  * ``bumper``   a second inside one of the episode's ``drops`` (step 2.2: opening, bumper, ad
                 break, credits). Nothing here detects it: with no ``drops`` section the picture
                 decides, and a bumper second reads as one of the other three.

What tells them apart is the show's saturated blue, measured on a 1 fps 320x180 frame (decoded
once per file and cached, ``frames``):

  * clip: the blue frame runs under the ticker, so the bottom band (rows 140-180 of 180) is at
    least ``CLIP_BOTTOM`` blue. In studio picture the ticker sits over the set;
  * footage: above the ticker, at most ``FOOTAGE_BLUE`` of the picture is blue and at most
    ``FOOTAGE_RED`` is the set's red. Every studio shot shows the set's blue panels or its red
    wall. Footage that is itself blue or red (chat screenshots with blue bubbles, blue maps, red
    posters) breaks this and reads as studio: 3 of the 9 holdout footage labels were read right.

The TV clock cannot help: it is on over full-frame footage too (20261120, 584-627 s).
Thresholds and the remaining confusions are measured on the hand labels in
``tests/data/hks_layout_labels.json`` (``--check``).

    python -m cutdeck.hks_layout --all G:\\Me\\Works [--check] [--holdout]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np

from cutdeck import hks_cache, hks_episode
from cutdeck.hks_audit import _key
from cutdeck.hks_gold import day_folders

STUDIO, CLIP, FOOTAGE, BUMPER = "studio", "clip", "footage", "bumper"
CLIP_BOTTOM = 0.29    # blue share of the bottom band: clip >= 0.32, studio <= 0.26 on the tuning labels
FOOTAGE_BLUE = 0.058  # blue share above the band: footage <= 0.056, studio mostly >= 0.061
FOOTAGE_RED = 0.10    # red-wall share above the band: red-wall close-ups >= 0.103, red footage graphics <= 0.099
BAND = 140            # first row of the bottom band at 180 rows

CACHE = Path(tempfile.gettempdir()) / "hks_layout"
LABELS = Path(__file__).parent.parent / "tests" / "data" / "hks_layout_labels.json"
CCTV = ("20261120", 584, 628)  # the user's 44 s full-frame CCTV cover, source 583.92-627.96
W, H = 320, 180
FRAME_BYTES = W * H * 3


def blue(rgb: np.ndarray) -> np.ndarray:
    """The show's saturated blue (frame, set panels), per pixel of ``...xHxWx3`` uint8 RGB."""
    a = rgb.astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return (b > 150) & (b > r + 60) & (b > g + 20)


def red(rgb: np.ndarray) -> np.ndarray:
    """The set's red wall, per pixel of ``...xHxWx3`` uint8 RGB."""
    a = rgb.astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return (r > 100) & (r * 5 > g * 9) & (r * 5 > b * 6)


def measure(rgb: np.ndarray) -> np.ndarray:
    """``(bottom blue, upper blue, upper red)`` shares of each ``Nx180x320x3`` frame, ``Nx3``."""
    m, upper = blue(rgb), rgb[:, :BAND]
    return np.stack([m[:, BAND:].mean((1, 2)), m[:, :BAND].mean((1, 2)), red(upper).mean((1, 2))], axis=1)


def kind_of(bottom: float, upper: float, upper_red: float) -> str:
    if bottom >= CLIP_BOTTOM:
        return CLIP
    return FOOTAGE if upper <= FOOTAGE_BLUE and upper_red <= FOOTAGE_RED else STUDIO


def kinds(measures: np.ndarray, drops: list[dict] | None = None) -> list[str]:
    """The kind of every second; a second inside a drop is a bumper."""
    out = [kind_of(*m) for m in measures]
    for d in drops or []:
        for i in range(max(0, int(np.ceil(d["start"]))), min(len(out), int(np.ceil(d["end"])))):
            out[i] = BUMPER
    return out


def merged(ks: list[str]) -> list[list]:
    """Half-open runs ``[a, b, kind]`` of equal kind."""
    out = []
    for i, k in enumerate(ks):
        if out and out[-1][2] == k:
            out[-1][1] = i + 1
        else:
            out.append([i, i + 1, k])
    return out


def kind_at(layout: list[list], t: int) -> str | None:
    return next((k for a, b, k in layout if a <= t < b), None)


# --- ffmpeg shell --------------------------------------------------------------------------------

def measures(path: str, cache: Path = CACHE) -> np.ndarray:
    """``measure`` of every second of ``path``, cached. Second i is the frame the ``fps=1`` filter
    picks, the one at i + 0.48 s on this 25 fps footage (the same frames as
    ``hks_audit.clock_track``), decoded at 320x180 RGB and streamed: the frames are never kept."""
    out = cache / f"{_key(path)}.layout.npy"
    if out.exists():
        hks_cache.touch(out)
        return np.load(out)
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-an", "-vf", f"fps=1,scale={W}:{H}:flags=area",
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    chunks = []
    while len(buf := proc.stdout.read(256 * FRAME_BYTES)) >= FRAME_BYTES:
        n = len(buf) // FRAME_BYTES
        chunks.append(measure(np.frombuffer(buf, np.uint8, n * FRAME_BYTES).reshape(n, H, W, 3)))
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed reading {path}")
    m = np.concatenate(chunks)
    cache.mkdir(parents=True, exist_ok=True)
    np.save(out, m)
    hks_cache.trim(cache.parent)
    return m


# --- episode shell -------------------------------------------------------------------------------

def layout_day(folder: Path, cache: Path = CACHE, out: Path = hks_episode.OUT) -> tuple[dict, list[str]]:
    """Write the ``layout`` section of every footage file of ``folder``. Returns the episode and
    the files that had no ``drops`` section (their bumpers come from the picture alone)."""
    day = folder.name[:8]
    no_drops = []
    for media in sorted((folder / "1. FOOTAGE").glob("*.mp4")):
        drops = hks_episode.load(day, out)["files"].get(media.name, {}).get("drops")
        if drops is None:
            no_drops.append(media.name)
        hks_episode.update(day, media.name, "layout", merged(kinds(measures(str(media), cache), drops)), out)
    return hks_episode.load(day, out), no_drops


def score(rows: list[dict], folders: dict[str, Path], cache: Path = CACHE,
          out: Path = hks_episode.OUT) -> tuple[dict[str, Counter], dict[str, Counter]]:
    """Per labelled class, a count of the kinds given at the labelled seconds: by the written
    layout (drops included), and by the picture alone."""
    written: dict[str, Counter] = {}
    picture: dict[str, Counter] = {}
    for r in rows:
        f = hks_episode.load(r["day"], out)["files"][r["file"]]
        written.setdefault(r["label"], Counter())[kind_at(f["layout"], r["t"])] += 1
        m = measures(str(folders[r["day"]] / "1. FOOTAGE" / r["file"]), cache)[r["t"]]
        picture.setdefault(r["label"], Counter())[kind_of(*m)] += 1
    return written, picture


def report(res: dict[str, Counter]) -> str:
    parts = []
    for label in (STUDIO, CLIP, FOOTAGE, BUMPER):
        c = res.get(label)
        if c:
            n = sum(c.values())
            other = ", ".join(f"{k} {v}" for k, v in c.most_common() if k != label)
            parts.append(f"{label} {c[label]}/{n} = {c[label] / n:.1%}" + (f" (as {other})" if other else ""))
    return "; ".join(parts)


def cctv_share(out: Path = hks_episode.OUT) -> float:
    day, a, b = CCTV
    (f,) = hks_episode.load(day, out)["files"].values()
    return sum(kind_at(f["layout"], t) == FOOTAGE for t in range(a, b)) / (b - a)


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--all", required=True, help="the folder holding the day folders")
    p.add_argument("--check", action="store_true", help="score the tuning labels and the CCTV cover")
    p.add_argument("--holdout", action="store_true", help="also the three holdout days, scored once")
    p.add_argument("--cache", default=str(CACHE))
    p.add_argument("--out", default=str(hks_episode.OUT))
    args = p.parse_args(argv)
    cache, out = Path(args.cache), Path(args.out)
    tuning, holdout = day_folders(args.all)
    for folder in tuning + (holdout if args.holdout else []):
        ep, no_drops = layout_day(folder, cache, out)
        total = Counter()
        for f in ep["files"].values():
            for a, b, k in f.get("layout", []):
                total[k] += b - a
        note = f"; no drops section in {len(no_drops)} of {len(ep['files'])} files" if no_drops else ""
        print(f"{folder.name[:8]}: " + ", ".join(f"{k} {v} s" for k, v in total.most_common()) + note)
    if not args.check:
        return
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    folders = {d.name[:8]: d for d in tuning + holdout}
    written, picture = score(labels["tuning"], folders, cache, out)
    print("tuning labels, written layout: " + report(written))
    print("tuning labels, picture alone:  " + report(picture))
    share = cctv_share(out)
    print(f"CCTV cover 20261120 {CCTV[1]}-{CCTV[2]}: {share:.1%} footage (need 90 %)")
    if args.holdout:
        written, picture = score(labels["holdout"], folders, cache, out)
        print("HOLDOUT, written layout: " + report(written) + " | picture alone: " + report(picture))
    sys.exit(0 if share >= 0.9 else 1)


if __name__ == "__main__":
    main()
