"""HKS build plan step 2.5: legal uncovered cut points.

A legal uncovered cut point is a source time where a cut may stay uncovered because the picture
changes there anyway (the user's rules, projects/hks/rule-audit.md, answers of 2026-11-23):

- ``camera``: a hard cut to another camera or shot in full-frame picture. Studio picture is the
  main case. A shot change inside full-frame news footage and a hard cut between layouts count
  too, because the whole frame changes (step 2.4, which would tell studio from footage, is not
  built; the audit's 270 camera-change cuts include such cuts).
- ``inset``: a camera change inside the small studio inset of the news-clip layout. The big
  window stays and the inset switches angle.
- ``still``: a run of frames that does not move (a full-screen map or chat screenshot). A cut
  anywhere inside the run cannot be seen.

Not legal: a punch-in (the same shot, tighter or wider: one frame matches a scaled crop of the
other, e.g. 20261120 source 2518.64, the cut at tl 681.92), a jump inside one shot, a cut of the
big news window alone, an overlay change (sponsor box, captions), the news-clip background
loop restarting, and dissolves (no single frame where the picture changes).

Output, in ``episode.json`` (``hks_episode``), keyed by footage file, in source seconds:

    "cut_points": [[t, "camera"], [t, "inset"], [a, b, "still"], ...]   sorted by first time

``t`` is the time of the first frame of the new picture (frame index / fps), so a cut whose
next keep starts at ``t``, or whose previous keep ends at ``t``, sits on the change. A still is
a run ``[a, b, "still"]``: the first frame of the still picture and the end of its last frame.

How. Each footage file is decoded once at 320x180 at its full frame rate (one ffmpeg, streamed)
and cached under ``%TEMP%/hks_cutpoints``: a 64x36 grey thumbnail per frame, and the 160x90 RGB
frames either side of every loose spike. From those, offline:

1. A pixel changes *abruptly* at frame i when it moves more than ``ABRUPT_DELTA`` from i-1 to i
   and much more than it moves from i-2 to i-1 and from i to i+1. Frames whose abrupt share is a
   local maximum of at least ``CANDIDATE`` are candidates.
2. Inset boxes are learned per file: a rectangle of inset size that changes densely on its own,
   landscape (``BOX_ASPECT``: a picture, not the background loop's strip or a window's edge), with
   both frames in the news-clip layout, at least ``BOX_MIN_SEEN`` times. No box position is
   hard-coded; layouts differ by episode.
3. Both frames in the news-clip layout (``topic_layout``): ``inset`` when a learned box changed
   densely. Otherwise, an abrupt share of ``FULL_FRAME`` or more is a whole-frame change, and it
   is ``camera`` unless one frame matches a scaled crop of the other (``SAME_SHOT``).
4. ``still``: frames equal to the frame one second earlier (all but ``STILL_MOVED`` of the
   pixels), in runs of at least one second; overlapping runs are one run, and a run is kept
   from two seconds.

The thresholds were set on the eight tuning episodes only (``hks_gold.HOLDOUT`` excluded).

    python -m cutdeck.hks_cutpoints --all G:\\Me\\Works [--check] [--holdout]

``--check`` scores the audit's rule 1 cuts (recall within ``MATCH_S``, tuning and holdout apart),
the hand labels of ``tests/data/hks_cutpoints_20261120.json`` (precision) and the punch-in.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from PIL import Image
from scipy import ndimage

from cutdeck.topic_layout import CLIP, classify_frame
from cutdeck import hks_cache

CACHE = Path(tempfile.gettempdir()) / "hks_cutpoints"
LABELS = Path(__file__).resolve().parent.parent / "tests" / "data" / "hks_cutpoints_20261120.json"

SCAN_W, SCAN_H = 320, 180   # every frame is decoded at this size, once
THUMB = 5                   # grey thumbnail = 5x5 block means of the scan frame: 64x36
PAIR = 2                    # spike pairs are kept at 2x2 block means: 160x90 RGB
LOOSE_DELTA = 12            # scan: a thumbnail pixel that moved this much changed ...
LOOSE_FRAC = 0.02           # ... and a pair is kept when this share of pixels changed ...
LOOSE_RATIO = 2.0           # ... and at least this many times the share one frame earlier

ABRUPT_DELTA = 10           # grey levels, 64x36
CANDIDATE = 0.03            # abrupt share of the frame that makes a candidate
FULL_FRAME = 0.5            # abrupt share of a whole-frame change
BOX_AREA = (0.04, 0.25)     # share of the frame an inset box covers
BOX_ASPECT = (1.2, 2.4)     # width over height of an inset box: a landscape picture, not a strip
BOX_FILL = 0.55             # abrupt share inside a component's box, to learn it as an inset box
BOX_MIN_SEEN = 4            # a box is an inset box once it changed on its own this often
INSET_FILL = 0.45           # abrupt share inside a learned box that makes an inset change
SAME_SHOT = 0.29            # scaled-crop match prominence at or above which two frames are one shot
SCALES = (1.0, 1.15, 1.33, 1.6, 2.0, 2.5, 3.2, 4.0)
MATCH_TOL = 8               # grey levels for two pixels to match in the scaled-crop test
STILL_DELTA = 8             # grey levels, 64x36, against the frame one second earlier
STILL_MOVED = 0.01          # share of pixels allowed to move in a still (the ticking TV clock)
MATCH_S = 0.1               # a detected point this close to a cut's source time explains it


def _key(path: str | Path) -> str:
    p = Path(path).resolve()
    stat = p.stat()
    identity = f"{os.path.normcase(str(p))}\0{stat.st_size}\0{stat.st_mtime_ns}"
    digest = hashlib.sha256(os.fsencode(identity)).hexdigest()
    stem = re.sub(r"[^A-Za-z0-9]+", "_", p.stem)[:40]
    return f"{stem}_{digest}"


def _duration(path: str | Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                 "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout)


def _blocks(frame: np.ndarray, k: int) -> np.ndarray:
    h, w = frame.shape[:2]
    return frame.reshape(h // k, k, w // k, k, *frame.shape[2:]).mean(axis=(1, 3))


@dataclass
class Scan:
    """Per-frame features of one footage file. Frame ``i`` shows at ``i / fps`` s."""
    fps: float
    diff: np.ndarray     # (n,) mean |RGB| difference to the previous frame at 320x180 (0 for frame 0)
    thumbs: np.ndarray   # (n, 36, 64) uint8 grey, memory-mapped
    pair_at: np.ndarray  # (m,) frame index i of each kept spike pair (frames i-1 and i)
    pairs: np.ndarray    # (m, 2, 90, 160, 3) uint8, memory-mapped

    @property
    def n(self) -> int:
        return len(self.diff)


def scan(path: str | Path, cache: Path = CACHE) -> Scan:
    """Decode ``path`` once at 320x180 and cache its per-frame features (streamed, never whole)."""
    cache.mkdir(parents=True, exist_ok=True)
    base = cache / _key(path)
    meta, thumbs_f, pairs_f = base.with_suffix(".npz"), base.with_suffix(".thumbs"), base.with_suffix(".pairs")
    if meta.exists() and thumbs_f.exists() and pairs_f.exists():  # a half-trimmed entry is rebuilt
        hks_cache.touch(meta)
    else:
        size = SCAN_W * SCAN_H * 3
        proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-an", "-fps_mode", "passthrough",
                                 "-vf", f"scale={SCAN_W}:{SCAN_H}:flags=area", "-f", "rawvideo",
                                 "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, bufsize=size * 4)
        diffs, pair_at = [], []
        prev = prev_g = None
        prev_frac = 1.0
        with open(thumbs_f, "wb") as tf, open(pairs_f, "wb") as pf:
            while len(buf := proc.stdout.read(size)) == size:
                frame = np.frombuffer(buf, np.uint8).reshape(SCAN_H, SCAN_W, 3)
                g = _blocks(frame.mean(axis=2), THUMB)
                tf.write(np.round(g).astype(np.uint8).tobytes())
                if prev is None:
                    diffs.append(0.0)
                else:
                    diffs.append(float(np.abs(frame.astype(np.int16) - prev).mean()))
                    frac = float((np.abs(g - prev_g) > LOOSE_DELTA).mean())
                    if frac >= LOOSE_FRAC and frac >= LOOSE_RATIO * prev_frac:
                        pair_at.append(len(diffs) - 1)
                        pf.write(np.round(_blocks(prev, PAIR)).astype(np.uint8).tobytes())
                        pf.write(np.round(_blocks(frame, PAIR)).astype(np.uint8).tobytes())
                    prev_frac = frac
                prev, prev_g = frame.astype(np.int16), g
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed reading {path}")
        # The rate is the decoded count over the duration, not the stream's r_frame_rate: the
        # field-coded 20261112 files say 50 fps and decode 25 frames a second.
        np.savez(meta, fps=len(diffs) / _duration(path), diff=np.array(diffs, np.float32),
                 pair_at=np.array(pair_at, np.int64))
        hks_cache.trim(cache.parent)
    m = np.load(meta)
    n, k = len(m["diff"]), len(m["pair_at"])
    th, tw = SCAN_H // THUMB, SCAN_W // THUMB
    ph, pw = SCAN_H // PAIR, SCAN_W // PAIR
    return Scan(float(m["fps"]), m["diff"], np.memmap(thumbs_f, np.uint8, "r", shape=(n, th, tw)),
                m["pair_at"], np.memmap(pairs_f, np.uint8, "r", shape=(k, 2, ph, pw, 3)) if k else
                np.zeros((0, 2, ph, pw, 3), np.uint8))


# --- pure detection ------------------------------------------------------------------------------

def abrupt(thumbs: np.ndarray) -> np.ndarray:
    """Abrupt-change masks for frames 2..len-2 of a run of thumbnails: (len-3, h, w) bool, row k
    is frame k+2. A pixel changes abruptly at i when |g_i - g_i-1| > ABRUPT_DELTA and more than
    twice (plus 2) the change of the frame pairs either side."""
    a = np.abs(np.diff(thumbs.astype(np.int16), axis=0))  # a[j] = change into frame j+1
    now, around = a[1:-1], np.maximum(a[:-2], a[2:])
    return (now > ABRUPT_DELTA) & (now > 2 * around + 2)


def candidates(thumbs: np.ndarray, chunk: int = 4000) -> list[tuple[int, np.ndarray]]:
    """(frame index, abrupt mask) of every frame whose abrupt share is at least CANDIDATE and the
    largest within two frames either side."""
    n = len(thumbs)
    share = np.zeros(n)
    masks: dict[int, np.ndarray] = {}
    for a in range(0, n - 3, chunk):
        b = min(n, a + chunk + 3)
        m = abrupt(thumbs[a:b])
        s = m.mean(axis=(1, 2))
        share[a + 2:a + 2 + len(s)] = s
        for k in np.nonzero(s >= CANDIDATE)[0]:
            masks[a + 2 + int(k)] = m[k]
    out = []
    for i in sorted(masks):
        if share[i] >= share[max(0, i - 2):i + 3].max():
            out.append((i, masks[i]))
    return out


def components(mask: np.ndarray) -> list[tuple[tuple[int, int, int, int], float]]:
    """Boxes ``(x0, y0, x1, y1)`` (inclusive) of the connected change regions, with the abrupt
    share inside each box."""
    lab, n = ndimage.label(ndimage.binary_dilation(mask))  # dilated, so a box's speckles join
    lab[~mask] = 0
    out = []
    for sl in ndimage.find_objects(lab):
        if sl is not None:
            box = (sl[1].start, sl[0].start, sl[1].stop - 1, sl[0].stop - 1)
            out.append((box, float(mask[sl].mean())))
    return out


def _area(box, shape) -> float:
    return (box[2] - box[0] + 1) * (box[3] - box[1] + 1) / (shape[0] * shape[1])


def inset_boxes(cands: list[tuple[int, np.ndarray]]) -> list[tuple[int, int, int, int]]:
    """The boxes that change densely on their own, inset-sized, at least BOX_MIN_SEEN times.
    Boxes within one thumbnail pixel of each other count as one."""
    seen = Counter()
    for _, m in cands:
        if m.mean() >= FULL_FRAME:
            continue
        for box, fill in components(m):
            aspect = (box[2] - box[0] + 1) / (box[3] - box[1] + 1)
            if (fill >= BOX_FILL and BOX_AREA[0] <= _area(box, m.shape) <= BOX_AREA[1]
                    and BOX_ASPECT[0] <= aspect <= BOX_ASPECT[1]):
                seen[box] += 1
    boxes: list[list] = []  # [box, count]
    for box, c in seen.most_common():
        near = next((b for b in boxes if max(abs(p - q) for p, q in zip(b[0], box)) <= 1), None)
        if near:
            near[1] += c
        else:
            boxes.append([box, c])
    return [b for b, c in boxes if c >= BOX_MIN_SEEN]


def same_shot(a: np.ndarray, b: np.ndarray) -> float:
    """How well one frame matches a scaled crop of the other (a punch-in, or the same shot
    moved), as the prominence of the best match: the share of matching pixels at the best place
    minus the median share over all places tried. Grey 160x90, centre of the frame only, so the
    overlays (clock, logos, caption bar) are left out of the template."""
    a, b = a.mean(axis=2).astype(np.float32), b.mean(axis=2).astype(np.float32)
    H, W = a.shape
    best = 0.0
    for big, small in ((a, b), (b, a)):
        for sc in SCALES:
            w, h = round(W / sc), round(H / sc)
            sm = np.asarray(Image.fromarray(small).resize((w, h), Image.BILINEAR))
            y0, y1, x0, x1 = int(.12 * h), int(.74 * h), int(.16 * w), int(.84 * w)
            tpl = sm[y0:y1, x0:x1]
            region = (big[y0:H - (h - y1), x0:W - (w - x1)] if sc > 1 else
                      big[max(0, y0 - 8):y1 + 8, max(0, x0 - 10):x1 + 10])
            share = (np.abs(sliding_window_view(region, tpl.shape) - tpl) < MATCH_TOL).mean(axis=(2, 3))
            best = max(best, float(share.max() - np.median(share)))
    return best


def classify(mask: np.ndarray, frames, boxes) -> str | None:
    """The kind of one candidate from its abrupt mask; ``frames()`` -> the RGB frames before and
    after, fetched only when the mask alone cannot rule the candidate out."""
    box_hit = any(mask[y0:y1 + 1, x0:x1 + 1].mean() >= INSET_FILL for x0, y0, x1, y1 in boxes)
    if not box_hit and mask.mean() < FULL_FRAME:
        return None
    a, b = frames()
    if classify_frame(a) == CLIP and classify_frame(b) == CLIP:
        return "inset" if box_hit else None
    if mask.mean() >= FULL_FRAME and same_shot(a, b) < SAME_SHOT:
        return "camera"
    return None


def still_runs(thumbs: np.ndarray, fps: float, chunk: int = 4000) -> list[tuple[int, int]]:
    """Half-open frame runs ``[a, b)`` that show one unmoving picture for at least one second."""
    lag = max(1, round(fps))
    n = len(thumbs)
    still = np.zeros(n, bool)  # frame j equals frame j-lag
    for a in range(lag, n, chunk):
        b = min(n, a + chunk)
        t = thumbs[a - lag:b].astype(np.int16)
        still[a:b] = (np.abs(t[lag:] - t[:-lag]) > STILL_DELTA).mean(axis=(1, 2)) < STILL_MOVED
    out, start = [], None
    for j, s in enumerate([*still, False]):
        if s and start is None:
            start = j
        elif not s and start is not None:
            a = start - lag  # the run's first frame is lag before the first match
            if out and a < out[-1][1]:  # overlap: a flash under a second split one still
                # (a run that only touches the last one is the next still after a hard cut)
                out[-1] = (out[-1][0], j)
            else:
                out.append((a, j))
            start = None
    return out


@dataclass(frozen=True)
class Points:
    """Detected legal cut points of one file, in source seconds."""
    camera: list[float]
    inset: list[float]
    still: list[tuple[float, float]]

    def section(self) -> list[list]:
        rows = ([[t, "camera"] for t in self.camera] + [[t, "inset"] for t in self.inset]
                + [[a, b, "still"] for a, b in self.still])
        return sorted(rows, key=lambda r: r[0])

    def near(self, t: float, tol: float = MATCH_S) -> str | None:
        """The kind of a point within ``tol`` of ``t`` (a still run counts when ``t`` is in it)."""
        for kind in ("camera", "inset"):
            if any(abs(p - t) <= tol + 1e-6 for p in getattr(self, kind)):
                return kind
        return "still" if any(a - tol <= t <= b + tol for a, b in self.still) else None


def detect(sc: Scan, pair_of) -> Points:
    """Legal cut points of one scanned file. ``pair_of(i)`` -> the RGB frames i-1 and i at 160x90."""
    cands = candidates(sc.thumbs)
    kept = set(sc.pair_at.tolist())  # learn boxes from the news-clip layout only, without a grab
    boxes = inset_boxes([(i, m) for i, m in cands if i in kept
                         and all(classify_frame(f) == CLIP for f in pair_of(i))])
    found: dict[str, list[float]] = {"camera": [], "inset": []}
    for i, mask in cands:
        kind = classify(mask, lambda: pair_of(i), boxes)
        if kind:
            found[kind].append(round(i / sc.fps, 3))
    still = [(round(a / sc.fps, 3), round(b / sc.fps, 3))
             for a, b in still_runs(sc.thumbs, sc.fps) if b - a >= 2 * round(sc.fps)]
    return Points(found["camera"], found["inset"], still)


# --- file shell ----------------------------------------------------------------------------------

def _grab_pair(path: str | Path, i: int, sc: Scan) -> tuple[np.ndarray, np.ndarray]:
    """Frames i-1 and i at 160x90. An input seek can land a frame off (B-frames), so a short
    run around them is decoded and the pair is the one whose thumbnails match the scan's."""
    lo = max(0, i - 8)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{lo / sc.fps:.4f}", "-i", str(path), "-an",
                          "-frames:v", "17", "-vf", f"scale={SCAN_W}:{SCAN_H}:flags=area", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, SCAN_H, SCAN_W, 3)
    g = np.stack([_blocks(x.mean(axis=2), THUMB) for x in f])
    want = sc.thumbs[[i - 1, i]].astype(np.float32)
    k = min(range(len(f) - 1), key=lambda k: float(np.abs(g[k:k + 2] - want).mean()))
    a, b = (np.round(_blocks(x.astype(np.float32), PAIR)).astype(np.uint8) for x in f[k:k + 2])
    return a, b


def pairs_for(path: str | Path, sc: Scan, cache: Path = CACHE):
    """``pair_of`` for ``detect``: the scan's kept pairs, else two frames grabbed and cached."""
    index = {int(i): k for k, i in enumerate(sc.pair_at)}
    extra_f = cache / f"{_key(path)}.extra.npz"
    extra = dict(np.load(extra_f)) if extra_f.exists() else {}
    grabbed = []

    def pair_of(i: int):
        if i in index:
            return sc.pairs[index[i], 0], sc.pairs[index[i], 1]
        if str(i) not in extra:
            extra[str(i)] = np.stack(_grab_pair(path, i, sc))
            grabbed.append(i)
        return extra[str(i)][0], extra[str(i)][1]

    def save():
        if grabbed:
            np.savez(extra_f, **extra)
    return pair_of, save


def detect_file(path: str | Path, cache: Path = CACHE) -> Points:
    sc = scan(path, cache)
    out = cache / f"{_key(path)}.points.json"
    if out.exists():
        d = json.loads(out.read_text())
        return Points(d["camera"], d["inset"], [tuple(x) for x in d["still"]])
    pair_of, save = pairs_for(path, sc, cache)
    pts = detect(sc, pair_of)
    save()
    out.write_text(json.dumps({"camera": pts.camera, "inset": pts.inset, "still": pts.still}))
    return pts


# --- the check -----------------------------------------------------------------------------------

# The audit's eye check of the 15 uncovered cuts below the threshold (rule-audit.md, rule 1).
STILL_CUTS = {("20261002", 1017.68), ("20261002", 1035.40), ("20261020", 155.76), ("20261020", 157.72),
              ("20261020", 159.20)}
SLIPS = {("20261120", 686.60), ("20261120", 687.60)}  # same-shot cuts the user called slips
PUNCH_IN = ("20261120", 681.92)                        # not legal; must not be explained


def audit_cuts(folder: Path) -> list[dict]:
    """The rule 1 rows of ``hks_audit.audit_day``: every uncovered YT body cut, with the source
    time and file either side and the frame difference (from the audit's cache)."""
    from cutdeck.hks_audit import CAMERA_CHANGE, DiffCache, _neighbours
    from cutdeck.hks_gold import FRAME, HALF, body, read_day
    diffs = DiffCache(Path(tempfile.gettempdir()) / "hks_audit")
    gold = read_day(folder)
    if gold.yt is None:  # a day not cut yet has no cuts to score
        return []
    paths = {name.lower(): str(folder / "1. FOOTAGE" / name) for name in gold.footage}
    rows = []
    for cut in (c for c in body(gold.yt)[1] if not c.covered):
        prev, nxt = _neighbours(gold.yt.keeps, cut.tl)
        diff = diffs.diff(paths[prev.media.lower()], prev.source_out - 1.5 * FRAME,
                          paths[nxt.media.lower()], nxt.source_in - HALF)
        key = (folder.name[:8], round(cut.tl, 2))
        cls = ("punch" if key == PUNCH_IN else "slip" if key in SLIPS else "still" if key in STILL_CUTS
               else "camera" if diff is not None and diff >= CAMERA_CHANGE else "inset")
        rows.append({"day": key[0], "tl": key[1], "class": cls, "diff": diff,
                     "before": (prev.media, round(prev.source_out, 3)), "after": (nxt.media, round(nxt.source_in, 3))})
    return rows


def change_near(sc: Scan, t: float, tol: float = MATCH_S) -> float:
    """The largest abrupt share of any frame within ``tol`` of ``t``: whether the picture changes
    there at all, whatever the detector decides. A cut with none on either side is outside any
    detector's reach (the recall ceiling)."""
    i0, i1 = max(2, int(np.floor((t - tol) * sc.fps))), min(sc.n - 2, int(np.ceil((t + tol) * sc.fps)))
    if i1 <= i0:
        return 0.0
    return float(abrupt(sc.thumbs[i0 - 2:i1 + 2]).mean(axis=(1, 2)).max())


def explained(row: dict, points: dict[tuple[str, str], Points]) -> str | None:
    """The kind of the detected point that explains a cut, from either side's source time."""
    for media, t in (row["before"], row["after"]):
        kind = points[row["day"], media.lower()].near(t)
        if kind:
            return kind
    return None


def recall(rows: list[dict], points: dict[tuple[str, str], Points]) -> dict[str, tuple[int, int, list]]:
    out = {}
    for cls in ("camera", "inset", "still"):
        mine = [r for r in rows if r["class"] == cls]
        miss = [r for r in mine if not explained(r, points)]
        out[cls] = (len(mine) - len(miss), len(mine), miss)
    return out


def precision(points: Points, labels: dict) -> dict:
    """Detections inside the labelled stretch that sit within MATCH_S of a labelled legal point."""
    inside = lambda t: any(a <= t < b for a, b in labels["stretch"])
    legal = [t for kind in ("camera", "inset") for t in labels["legal"][kind]]
    out = {}
    for kind in ("camera", "inset"):
        det = [t for t in getattr(points, kind) if inside(t)]
        wrong = [t for t in det if not any(abs(t - x) <= MATCH_S + 1e-6 for x in legal)]
        out[kind] = (len(det) - len(wrong), len(det), wrong)
    stills = [(a, b) for a, b in points.still if inside(a) or inside(b)]
    out["still"] = (0, len(stills), stills) if not labels["legal"]["still"] else None
    found = [t for t in legal if any(abs(t - x) <= MATCH_S + 1e-6 for kind in ("camera", "inset")
                                     for x in getattr(points, kind))]
    out["label_recall"] = (len(found), len(legal), sorted(set(legal) - set(found)))
    return out


def main(argv: list[str] | None = None) -> None:
    from cutdeck.hks_episode import update
    from cutdeck.hks_gold import day_folders
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--all", required=True, help="the folder holding the day folders")
    p.add_argument("--check", action="store_true", help="recall on the audit cuts, precision on the labels")
    p.add_argument("--holdout", action="store_true", help="also the three holdout days (scored on their own)")
    p.add_argument("--out", default=None, help="episode.json folder (default: hks_episode's)")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    tuning, holdout = day_folders(args.all)
    groups = [("tuning", tuning)] + ([("holdout", holdout)] if args.holdout else [])
    extra = {} if args.out is None else {"out": Path(args.out)}
    fails = []
    for group, folders in groups:
        rows = []
        points: dict[tuple[str, str], Points] = {}
        for folder in folders:
            for media in sorted((folder / "1. FOOTAGE").glob("*.mp4")):
                pts = detect_file(media)
                points[folder.name[:8], media.name.lower()] = pts
                update(folder.name[:8], media.name, "cut_points", pts.section(), **extra)
                print(f"{folder.name[:8]} {media.name}: {len(pts.camera)} camera, {len(pts.inset)} inset, "
                      f"{len(pts.still)} still runs", file=sys.stderr, flush=True)
            if args.check:
                rows += audit_cuts(folder)
        if not args.check:
            continue
        print(f"\n## {group} ({len(folders)} episodes): recall on the audit's uncovered cuts, "
              f"a point within {MATCH_S} s of either side")
        scans = {(f.name[:8], m.name.lower()): scan(m)
                 for f in folders for m in (f / "1. FOOTAGE").glob("*.mp4")}

        def change(r):
            return max(change_near(scans[r["day"], media.lower()], t) for media, t in (r["before"], r["after"]))
        for cls, (hit, n, miss) in recall(rows, points).items():
            mine = [r for r in rows if r["class"] == cls]
            ceiling = "" if cls == "still" else (
                f"; {sum(change(r) >= CANDIDATE for r in mine)} of the {n} have an abrupt picture change "
                f"within {MATCH_S} s of a side")
            print(f"{cls}: {hit}/{n}" + (f" ({100 * hit / n:.0f} %)" if n else "") + ceiling)
            for r in miss:
                print(f"  miss {r['day']} tl {r['tl']:.2f} diff {r['diff']} source {r['before'][1]} -> "
                      f"{r['after'][1]}, abrupt share near {change(r):.3f}")
        for r in rows:
            if r["class"] in ("punch", "slip"):
                kind = explained(r, points)
                print(f"{r['class']} {r['day']} tl {r['tl']:.2f}: " + ("not explained (right)" if kind is None
                                                                      else f"explained as {kind} (WRONG)"))
                if r["class"] == "punch" and kind is not None:
                    fails.append("punch-in detected as legal")
        if group == "tuning":
            labels = json.loads(LABELS.read_text(encoding="utf-8"))
            pr = precision(points["20261120", labels["file"].lower()], labels)
            print("\n## precision on the hand labels (20261120, 10 min)")
            for kind in ("camera", "inset"):
                ok, n, wrong = pr[kind]
                print(f"{kind}: {ok}/{n} detections are labelled legal points; wrong at {wrong}")
            print(f"still: {pr['still'][1]} still runs detected where the labels have none: {pr['still'][2]}")
            ok, n, missed = pr["label_recall"]
            print(f"labelled legal points found: {ok}/{n}; missed {missed}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
