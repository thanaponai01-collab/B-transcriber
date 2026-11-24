"""HKS build plan step 2.6: host vs guest turns of every footage file, the ``turns`` section of
``episode.json`` (``[[a, b, "host" | "guest"], ...]`` in source seconds; see ``hks_episode``).

The host is the same man every episode, so one voice profile serves all of them: the mean ECAPA
embedding (``topic_speakers``) of his opening monologue on 20261120, source 24.0-92.5 s, stored in
``hks_host_profile.json`` so no run needs that day's footage. Each 1.5 s speech window, 0.25 s apart,
is scored by cosine to it, median-smoothed over its neighbours within 0.75 s, and called host above
``topic_speakers.HOST_THRESHOLD``. Speech shorter than one window gets no turn.

Measured on the hand labels (``tests/data/hks_turns_*.json``, made from the transcript, not by ear):
the same procedure seeded on 20261012's own monologue gives a profile at cosine 0.90 to this one and
scores within a few points of it on both label sets; a per-episode profile reseeded from each
episode's top-scoring windows, or guest centroids per episode, did not beat it. What differs per
episode is how close the guests sit to the host (median window score 0.33 on 20261120, 0.19 on
20261012), so precision is the weak side on 20261120.

``--check`` is the step's proof:
  - host precision >= MIN_PRECISION and recall >= MIN_RECALL on each label set;
  - the host share of the story-1 host-prompt cuts of 20261120 (266.04-298.80, 312.60-321.40)
    >= MIN_STORY1. The labels themselves put only 40 % of those seconds in host speech: the cuts
    also hold the guests' short answers, and 312.6-319.2 is the guest telling;
  - a detector that calls everything host fails the precision bar (tests/test_hks_turns.py).

    python -m cutdeck.hks_turns --all G:\\Me\\Works [--check] [--holdout] [--profile]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from cutdeck.hks_episode import OUT, load, update
from cutdeck import hks_cache
from cutdeck.hks_gold import day_folders
from cutdeck.topic_speakers import (HOST_THRESHOLD, SR, WINDOW_S, embed_windows, smooth,
                                    speech_window_starts, turns_from_scores)

CACHE = Path(tempfile.gettempdir()) / "hks_turns"
HOP_S = 0.25  # finer than topic_speakers' 0.75: host prompts are often 1-3 s
SMOOTH_WINDOWS = 1  # topic_speakers.smooth reach = 1 x its 0.75 s hop
PROFILE = Path(__file__).with_name("hks_host_profile.json")
SEED = ("20261120", "HKS Facebook 201169 Full.mp4", 24.0, 92.5)  # the host's opening monologue
LABELS = [Path(__file__).resolve().parent.parent / "tests" / "data" / f"hks_turns_{d}.json"
          for d in ("20261120", "20261012")]
STORY1 = ("20261120", [(266.04, 298.80), (312.60, 321.40)])
COLLAR = 0.25  # s ignored inside each label edge (word times are about +-0.3 s)
MIN_PRECISION = 0.80  # bars set after the hop-0.75 baseline was seen, before the hop and threshold choice
MIN_RECALL = 0.60
MIN_STORY1 = 0.25  # of 41.56 s; the labels' own host share is 0.40


# --- embeddings ---------------------------------------------------------------------------------

def load_audio(media: Path) -> np.ndarray:
    """16 kHz mono float32 of one footage file, piped from ffmpeg (no temp wav)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(media), "-vn", "-ac", "1", "-ar", str(SR),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def windows(media: Path, cache: Path = CACHE) -> tuple[np.ndarray, np.ndarray]:
    """Speech window starts and unit speaker embeddings of one footage file, cached per file."""
    path = cache / f"{media.parent.parent.name[:8]} {media.stem} {media.stat().st_size} h{HOP_S}.npz"
    if path.exists():
        hks_cache.touch(path)
        z = np.load(path)
        return z["starts"], z["emb"]
    audio = load_audio(media)
    starts = np.array(speech_window_starts(audio, HOP_S))
    emb = embed_windows(audio, list(starts))  # loads, runs and frees the GPU model
    del audio
    cache.mkdir(parents=True, exist_ok=True)
    np.savez(path, starts=starts, emb=emb)
    hks_cache.trim(cache.parent)
    return starts, emb


def build_profile(root: Path, cache: Path = CACHE) -> np.ndarray:
    day, name, a, b = SEED
    folder = next(Path(root).glob(f"{day}*"))
    starts, emb = windows(folder / "1. FOOTAGE" / name, cache)
    inside = (starts >= a) & (starts + WINDOW_S <= b)
    profile = emb[inside].mean(0)
    profile /= np.linalg.norm(profile)
    PROFILE.write_text(json.dumps({"seed": list(SEED), "window_s": WINDOW_S, "hop_s": HOP_S,
                                   "windows": int(inside.sum()),
                                   "profile": [round(float(x), 6) for x in profile]}), encoding="utf-8")
    return profile


def load_profile() -> np.ndarray:
    return np.array(json.loads(PROFILE.read_text(encoding="utf-8"))["profile"], np.float32)


def turns(starts: np.ndarray, emb: np.ndarray, profile: np.ndarray) -> list[list]:
    if len(starts) == 0:
        return []
    scores = smooth(starts, emb @ profile, SMOOTH_WINDOWS)
    return [[round(t.start_s, 2), round(t.end_s, 2), "host" if t.is_host else "guest"]
            for t in turns_from_scores(starts, scores, HOST_THRESHOLD)]


# --- check (pure) -------------------------------------------------------------------------------

def _is_host(turns_: list[list], t: float) -> bool:
    return any(a <= t < b and role == "host" for a, b, role in turns_)


def precision_recall(turns_: list[list], spans: list[list], step: float = 0.1) -> tuple[float, float]:
    """Host precision and recall over the labelled seconds, sampled every ``step`` s inside each
    label span less COLLAR at both ends. Unlabelled time is not scored."""
    tp = fp = fn = 0
    for a, b, role in spans:
        for t in np.arange(a + COLLAR, b - COLLAR, step):
            host = _is_host(turns_, t)
            if role == "host":
                tp += host
                fn += not host
            else:
                fp += host
    return tp / max(tp + fp, 1), tp / max(tp + fn, 1)


def host_share(turns_: list[list], ranges: list[tuple[float, float]]) -> float:
    """Share of the seconds of ``ranges`` that host turns cover."""
    hit = sum(max(0.0, min(b, y) - max(a, x)) for a, b in ranges for x, y, role in turns_ if role == "host")
    return hit / sum(b - a for a, b in ranges)


def check(turns_of: dict[tuple[str, str], list[list]], labels: list[dict]) -> tuple[list[str], list[str]]:
    """(report lines, failures). ``turns_of`` maps (day, file) to its turns."""
    lines, fails = [], []
    for lab in labels:
        p, r = precision_recall(turns_of[(lab["day"], lab["file"])], lab["spans"])
        lines.append(f"{lab['day']} labels: host precision {p:.2f}, recall {r:.2f}")
        if p < MIN_PRECISION or r < MIN_RECALL:
            fails.append(f"{lab['day']}: precision {p:.2f} / recall {r:.2f} below {MIN_PRECISION} / {MIN_RECALL}")
    day, ranges = STORY1
    (key,) = [k for k in turns_of if k[0] == day]
    share = host_share(turns_of[key], ranges)
    lines.append(f"{day} story-1 host-prompt cuts: {share:.2f} of their seconds in host turns")
    if share < MIN_STORY1:
        fails.append(f"{day}: story-1 cuts host share {share:.2f} below {MIN_STORY1}")
    return lines, fails


# --- CLI ----------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--all", required=True, help="the folder holding the day folders")
    p.add_argument("--check", action="store_true", help="run the 2.6 check")
    p.add_argument("--holdout", action="store_true", help="also the three holdout days")
    p.add_argument("--profile", action="store_true", help="rebuild the host profile from SEED")
    p.add_argument("--out", default=str(OUT))
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    out = Path(args.out)
    profile = build_profile(Path(args.all)) if args.profile or not PROFILE.exists() else load_profile()
    tuning, holdout = day_folders(args.all)
    result: dict[tuple[str, str], list[list]] = {}
    for folder in tuning + (holdout if args.holdout else []):
        for media in sorted((folder / "1. FOOTAGE").glob("*.mp4")):
            result[(folder.name[:8], media.name)] = turns(*windows(media), profile)
    for (day, name), t in result.items():
        update(day, name, "turns", t, out)
    for (day, name), t in result.items():
        assert load(day, out)["files"][name]["turns"] == t, f"{day} {name}: turns not written"
        host = sum(b - a for a, b, r in t if r == "host")
        speech = sum(b - a for a, b, _ in t)
        print(f"{day} {name}: {len(t)} turns, host {host / max(speech, 1):.0%} of {speech / 60:.0f} min speech")
    if not args.check:
        return 0
    labels = [json.loads(path.read_text(encoding="utf-8")) for path in LABELS]
    lines, fails = check(result, labels)
    print("\n".join(lines + fails) or "")
    print("check:", "pass" if not fails else "FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
