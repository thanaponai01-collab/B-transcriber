"""HKS build plan step 2.2: the source ranges a rough cut drops, per footage file.

Writes the ``drops`` section of ``episode.json`` (``cutdeck/hks_episode.py``) for every footage
file, in source seconds: ``[{"start", "end", "kind", "why"}]``, sorted and not overlapping.
Four kinds, from two signals (projects/hks/build-plan.md step 2.2, rule-audit.md question 7):

- ``opening``: from 0 to the end of the opening title, found by its audio fingerprint in the
  first ``OPEN_SEARCH_S`` seconds.
- ``credits``: from the hard picture cut into the end credits to the end of the file. The
  credits music is found by fingerprint after the first ``OPEN_SEARCH_S`` seconds; the drop
  starts at the last hard cut (``HARD_CUT``) in the ``CREDITS_LEAD_S`` seconds before it,
  because the host's goodbye runs over the credits picture before the music starts.
- ``bumper``: each match of the in- or out-sting fingerprint.
- ``clock_off``: the rest of every clock-off run of 10 s or more inside the TV part (the user's
  rule 7: drop every one; they un-drop the graphics they keep). The run's edges come from the
  1 fps clock track (``hks_audit.clock_track``), each moved to the hard picture cut inside that
  second when there is one, else to the middle of the second.

Every fingerprint drop spans only the part of the clip heard on this file (``heard``): the
station music often runs on under the host's first words, and the drop ends where the host
starts.

Fingerprints are reference clips (``REFS``), cut once with ``--cut-refs`` from tuning day
20261117 into ``test_projects/hks_refs/`` (gitignored): ``<name>.wav`` (16 kHz mono, the clip a
person can listen to) and ``refs.json`` (where each was cut and from how many partners). Each
clip is the stretch around its anchor that most other occurrences of the same sound in the
tuning days share (the median, over the partners, of the per-band correlation in a 0.4 s window
stays at ``AGREE`` or more), plus ``REF_PAD_S`` each side so that ``heard`` places the edges on
each file rather than the clip's. Partners come from every tuning day except 20261120, so the
20261120 check below is not checked against its own audio. ``--cut-refs`` redoes them.

Audio features: mono 16 kHz, a 32-band log-mel frame every 40 ms (one per 25 fps video frame),
streamed from ffmpeg and cached under ``%TEMP%/hks_breaks``. A match is the per-band Pearson
correlation of the clip with the file at every frame, averaged over bands (``match_curve``).

``--check`` (written before the first finder run, not changed after):

- 20261120, the one day with an ``Edit`` sequence: each gold boundary within ``TOL_S`` of the
  edge of the merged proposed drop that overlaps it. 824.56 (break 1 start) is reported but not
  gated: the brief names 824.56-~860 a sponsor, step 2.7's job.
- One-sided, every tuning day: no drop overlaps the YT keeps (``hks_gold``) of its file by 1 s or
  more, except drops over the three 20261001 flood-map runs the user kept (``KEPT_GRAPHICS``),
  which are correct drops under rule 7 and are listed, not failed.
- Every bumper/ad dip of the audit (``AUDIT_DIPS``) is covered: the drops cover the dip without
  its first and last second (the 1 fps track places an edge only to the second).

The holdout days (``hks_gold.HOLDOUT``) run only with ``--holdout``, once, reported on their own
line.

    python -m cutdeck.hks_breaks --cut-refs G:\\Me\\Works
    python -m cutdeck.hks_breaks --all G:\\Me\\Works [--check] [--holdout]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from cutdeck.hks_audit import clock_track, dips, tv_part
from cutdeck.hks_episode import CACHE as CLOCK_CACHE, OUT, update
from cutdeck.hks_gold import day_folders, read_day

SR = 16000
HOP = 640           # 40 ms: one feature frame per 25 fps video frame
WIN = 1024
FPS = SR / HOP      # 25 feature frames per second
N_MELS = 32
FEATURES = "mel32v1"  # in the cache file name: change it when the feature recipe changes
CACHE = Path(tempfile.gettempdir()) / "hks_breaks"
REFS_DIR = Path("test_projects/hks_refs")

MATCH = 0.8           # fingerprint score that counts as the same sound
AGREE = 0.5           # median partner agreement that keeps a sample inside a reference clip
AGREE_WIN = 10        # frames (0.4 s) per agreement window
HARD_CUT = 25.0       # mean |gray difference| of consecutive 64x36 frames: a hard picture cut
CREDITS_LEAD_S = 8.0  # how far before the credits music a hard cut into the credits is looked for
OPEN_SEARCH_S = 90.0  # the opening title starts within this many seconds of the file start
CORE_S = 6.0          # seconds in the middle of a clip that are matched
REF_PAD_S = 1.0       # the clip runs this far past the shared span each side; ``heard`` sets the edges
SLIVER_S = 1.0        # a bumper piece shorter than this left beside the opening or credits is not proposed

# Where each reference clip is cut: a tuning day, a time inside the sound, where its partners are
# looked for. The clip's edges are not set by hand: see shared_span.
REF_DAY = "20261117"
REFS = {
    "opening":   {"anchor": 10.0,   "region": "head"},
    "sting_in":  {"anchor": 1764.0, "region": "tv"},
    "sting_out": {"anchor": 1820.0, "region": "tv"},
    "credits":   {"anchor": 5288.0, "region": "tail"},
}

# --- the 2.2 check, fixed before the first finder run ---------------------------------------
TOL_S = 0.5
GOLD_1120 = [  # (name, start, end, gate start, gate end); end None = the end of the file
    ("opening", 0.0, 22.68, True, True),
    ("break 1", 824.56, 877.20, False, True),
    ("break 2", 2004.88, 2069.32, True, True),
    ("credits", 4428.24, None, True, True),
]
KEEP_OVERLAP_S = 1.0
# hks_audit dips (1 fps seconds) that are bumpers or TV ads: rule-audit.md, rule 3.
AUDIT_DIPS = {
    "20261001": [(838, 855), (1704, 1723)],
    "20261003": [(873, 945), (1569, 1635)],
    "20261012": [(1028, 1047), (2434, 2453)],
    "20261020": [(1047, 1115), (2186, 2253)],
    "20261110": [(1405, 1464), (2268, 2317)],
    "20261112": [(1164, 1222), (1844, 1910)],
    "20261117": [(967, 1025), (1763, 1828)],
    "20261120": [(819, 876), (2006, 2069)],
    "20261002": [(1117, 1135), (2041, 2060)],
    "20261109": [(888, 949), (1668, 1714)],
    "20261118": [(1107, 1165), (1785, 1850)],
}
# The 20261001 clock-off runs that are flood-map graphics the user kept (audit dips with kept seconds).
KEPT_GRAPHICS = {"20261001": [(257, 558), (1320, 1378), (1483, 1519)]}


# --- audio features --------------------------------------------------------------------------

def _mel_bank() -> np.ndarray:
    import librosa
    return librosa.filters.mel(sr=SR, n_fft=WIN, n_mels=N_MELS, fmin=100, fmax=7000).astype(np.float32)


def _key(path: str) -> str:
    from cutdeck.hks_audit import _key as audit_key
    return audit_key(path)


def audio_features(path: str, cache: Path = CACHE) -> tuple[np.ndarray, np.ndarray]:
    """(log-mel ``[frames, N_MELS]``, loudness dB ``[frames]``) of ``path`` at ``FPS`` frames per
    second, frame i centred on i / FPS s. The audio is streamed from ffmpeg and cached."""
    out = cache / f"{_key(path)}.{FEATURES}.npz"
    if out.exists():
        z = np.load(out)
        return z["mel"].astype(np.float32), z["db"].astype(np.float32)
    bank, window = _mel_bank(), np.hanning(WIN).astype(np.float32)
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SR),
                             "-f", "s16le", "-"], stdout=subprocess.PIPE)
    carry = np.zeros(WIN // 2, np.float32)  # centre frame 0 on t = 0
    mels, dbs = [], []
    while True:
        raw = proc.stdout.read(SR * 2 * 60)
        if not raw:
            break
        x = np.concatenate([carry, np.frombuffer(raw, np.int16).astype(np.float32) / 32768])
        n = max(0, (len(x) - WIN) // HOP + 1)
        if n:
            frames = x[np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]]
            power = np.abs(np.fft.rfft(frames * window, axis=1)) ** 2
            mels.append(np.log10(power @ bank.T + 1e-10).astype(np.float16))
            dbs.append((10 * np.log10((frames ** 2).mean(axis=1) + 1e-10)).astype(np.float16))
        carry = x[n * HOP:]
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed reading {path}")
    mel, db = np.concatenate(mels), np.concatenate(dbs)
    cache.mkdir(parents=True, exist_ok=True)
    np.savez(out, mel=mel, db=db)
    return mel.astype(np.float32), db.astype(np.float32)


# --- matching (pure) -------------------------------------------------------------------------

def _centred(mel: np.ndarray) -> np.ndarray:
    """Per-frame band shape: the frame's mean log level removed, so a gain change does not count."""
    return mel - mel.mean(axis=1, keepdims=True)


def match_curve(ref: np.ndarray, mel: np.ndarray) -> np.ndarray:
    """How well ``ref`` ([n, bands]) matches ``mel`` ([N, bands]) at every start frame: the
    Pearson correlation of each band's level over time, averaged over the bands. 1.0 is the same
    sound; a fixed spectral tilt or a gain change does not count."""
    from scipy.signal import fftconvolve
    r, s = _centred(ref).astype(np.float64), _centred(mel).astype(np.float64)
    n = len(r)
    if len(s) < n or n == 0:
        return np.zeros(0, np.float32)
    r = r - r.mean(axis=0)
    rn = np.maximum(np.linalg.norm(r, axis=0), 1e-9)
    c1 = np.vstack([np.zeros(s.shape[1]), np.cumsum(s, axis=0)])
    c2 = np.vstack([np.zeros(s.shape[1]), np.cumsum(s ** 2, axis=0)])
    total = np.zeros(len(s) - n + 1)
    for b in range(r.shape[1]):
        num = fftconvolve(s[:, b], r[::-1, b], mode="valid")
        ws = c1[n:, b] - c1[:-n, b]
        var = np.maximum(c2[n:, b] - c2[:-n, b] - ws ** 2 / n, 1e-9)
        total += num / (np.sqrt(var) * rn[b])
    return (total / r.shape[1]).astype(np.float32)


def peaks(curve: np.ndarray, threshold: float, gap: int) -> list[int]:
    """Start frames of the local maxima of ``curve`` at ``threshold`` or above, ``gap`` frames apart."""
    from scipy.signal import find_peaks
    return [int(i) for i in find_peaks(np.concatenate([[-1.0], curve, [-1.0]]),
                                       height=threshold, distance=gap)[0] - 1]


def shared_span(mel: np.ndarray, anchor: int, partners: list[tuple[np.ndarray, int]],
                win: int = AGREE_WIN, agree: float = AGREE) -> tuple[int, int]:
    """Frames ``[start, end)`` around ``anchor`` where ``mel`` sounds like its partners: each
    partner is (features, lag), partner frame = frame + lag. A frame is inside while the median
    partner agreement of the ``win`` frames centred on it is ``agree`` or more."""
    def ok(k: int) -> bool:
        a, b = k - win // 2, k + win - win // 2
        if a < 0 or b > len(mel):
            return False
        scores = [match_curve(mel[a:b], p[a + lag:b + lag])[0] if 0 <= a + lag and b + lag <= len(p) else -1.0
                  for p, lag in partners]
        return bool(np.median(scores) >= agree)

    end = anchor
    while ok(end):
        end += 1
    start = anchor
    while ok(start - 1):
        start -= 1
    return start, end


def locate(ref: np.ndarray, mel: np.ndarray, lo: int = 0, hi: int | None = None) -> list[tuple[int, float]]:
    """(clip start frame, score) of each match of ``ref`` whose core starts in ``mel[lo:hi]``.
    Only the clip's middle ``CORE_S`` seconds are matched, so a host talking over either end of
    the music does not lower the score; the start frame can be negative when the clip starts
    before the file."""
    core = int(CORE_S * FPS)
    k = max(0, len(ref) // 2 - core // 2)
    hi = len(mel) if hi is None else min(hi, len(mel))
    curve = match_curve(ref[k:k + core], mel[lo:hi])
    return [(lo + i - k, float(curve[i])) for i in peaks(curve, MATCH, max(core, len(ref)))]


def heard(ref: np.ndarray, mel: np.ndarray, i: int, win: int = AGREE_WIN) -> tuple[int, int]:
    """Frames ``[start, end)`` of ``mel`` where the reference matched at frame ``i`` is heard: the
    ``shared_span`` of the clip with this one file, walked out from its best-agreeing window. A
    host talking over the music's tail ends it there."""
    if i < 0:  # the clip starts before the file does
        a, b = heard(ref[-i:], mel, 0, win)
        return a, b
    n = min(len(ref), len(mel) - i)
    scores = [match_curve(ref[k:k + win], mel[i + k:i + k + win])[0] for k in range(0, n - win + 1, win // 2)]
    anchor = int(np.argmax(scores)) * (win // 2) + win // 2
    a, b = shared_span(ref[:n], anchor, [(mel, i)], win)
    return i + a, i + b


# --- drops (pure) ----------------------------------------------------------------------------

def merged(spans) -> list[tuple[float, float]]:
    """Union of (start, end) spans, touching ones (within a frame) joined."""
    out: list[list[float]] = []
    for a, b in sorted((s[0], s[1]) for s in spans):
        if out and a <= out[-1][1] + 0.04:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def subtract(a: float, b: float, cover: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The parts of ``[a, b)`` outside every span of ``cover``."""
    out, t = [], a
    for s, e in sorted(cover):
        if e <= t or s >= b:
            continue
        if s > t:
            out.append((t, s))
        t = max(t, e)
    if t < b:
        out.append((t, b))
    return out


def combine(candidates: list[dict]) -> list[dict]:
    """Non-overlapping drops from overlapping candidates. Precedence: opening and credits, then
    bumpers, then clock-off runs; a lower one keeps only what the higher ones leave. A bumper
    leftover shorter than ``SLIVER_S`` (the edge of a sting inside the opening or credits) is
    dropped; every clock-off leftover stays, because rule 7 drops the whole run."""
    rank = {"opening": 0, "credits": 0, "bumper": 1, "clock_off": 2}
    out: list[dict] = []
    for c in sorted(candidates, key=lambda c: (rank[c["kind"]], c["start"])):
        taken = [(d["start"], d["end"]) for d in out]
        for a, b in subtract(c["start"], c["end"], taken):
            if c["kind"] != "bumper" or b - a >= SLIVER_S:
                out.append({**c, "start": round(a, 2), "end": round(b, 2)})
    return sorted(out, key=lambda d: d["start"])


def edge_in_second(diffs: list[tuple[float, float]], s: int) -> float:
    """Where a clock change between samples ``s - 1`` and ``s`` happened: the biggest hard
    picture cut in that second, else its middle. ``diffs`` is [(time, frame difference)]."""
    cuts = [(d, t) for t, d in diffs if s - 1 <= t <= s and d >= HARD_CUT]
    return max(cuts)[1] if cuts else s - 0.5


def last_cut_before(diffs: list[tuple[float, float]], t: float, lead: float = CREDITS_LEAD_S) -> float | None:
    cuts = [x for x, d in diffs if t - lead <= x <= t and d >= HARD_CUT]
    return max(cuts) if cuts else None


# --- the shell: ffmpeg frames, references, one file ------------------------------------------

def frame_diffs(path: str, a: float, b: float) -> list[tuple[float, float]]:
    """(time of the later frame, mean |gray difference|) for consecutive 64x36 frames in [a, b]."""
    a = max(a, 0.0)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{a:.3f}", "-i", path, "-t", f"{b - a:.3f}",
                          "-vf", "scale=64:36", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, 36, 64).astype(np.int16)
    d = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))
    return [(round(a + (i + 1) / FPS, 2), float(x)) for i, x in enumerate(d)]


def _footage(folder: Path) -> list[Path]:
    return sorted(p for p in (folder / "1. FOOTAGE").glob("*") if p.suffix.lower() == ".mp4")


def _region(region: str, mel: np.ndarray, clock: np.ndarray) -> tuple[int, int] | None:
    n = len(mel)
    if region == "head":
        return 0, min(n, int(60 * FPS))
    if region == "tail":
        return max(0, n - int(120 * FPS)), n
    part = tv_part(clock)
    return None if part is None else (int(part[0] * FPS), min(n, int(part[1] * FPS)))


def cut_refs(root: str | Path, out: Path = REFS_DIR) -> dict:
    """Cut every ``REFS`` clip from ``REF_DAY`` (see the module docstring) and write the record."""
    tuning, _ = day_folders(root)
    src_folder = next(f for f in tuning if f.name.startswith(REF_DAY))
    src = _footage(src_folder)[0]
    mel, _ = audio_features(str(src))
    files = [p for f in tuning if not f.name.startswith("20261120") for p in _footage(f)]
    record = {}
    for name, spec in REFS.items():
        anchor = int(spec["anchor"] * FPS)
        core = mel[anchor - 50:anchor + 50]
        partners = []
        for p in files:
            pm, _ = audio_features(str(p))
            span = _region(spec["region"], pm, clock_track(str(p), CLOCK_CACHE))
            if span is None:
                continue
            curve = match_curve(core, pm[span[0]:span[1]])
            for i in peaks(curve, MATCH, int(30 * FPS)):
                lag = span[0] + i - (anchor - 50)
                if not (p == src and abs(lag) < FPS):
                    partners.append((pm, lag))
        start, end = shared_span(mel, anchor, partners)
        a, b = max(0.0, start / FPS - REF_PAD_S), min(len(mel) / FPS, end / FPS + REF_PAD_S)
        out.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-i", str(src), "-t", f"{b - a:.3f}",
                        "-vn", "-ac", "1", "-ar", str(SR), str(out / f"{name}.wav")], check=True)
        record[name] = {"day": REF_DAY, "file": src.name, "start": round(a, 2), "end": round(b, 2),
                        "shared": [round(start / FPS, 2), round(end / FPS, 2)], "pad": REF_PAD_S,
                        "anchor": spec["anchor"], "region": spec["region"], "partners": len(partners),
                        "rule": f"median per-band correlation of {AGREE_WIN} frames with the partners >= {AGREE}"}
        print(f"{name}: {src.name} shared {start / FPS:.2f}-{end / FPS:.2f}, clip {a:.2f}-{b:.2f}, "
              f"{len(partners)} partners")
    (out / "refs.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return record


def load_refs(out: Path = REFS_DIR) -> dict:
    """name -> (features, clip seconds). Missing clips: run ``--cut-refs`` first."""
    record = json.loads((out / "refs.json").read_text(encoding="utf-8"))
    return {name: (audio_features(str(out / f"{name}.wav"))[0], r["end"] - r["start"])
            for name, r in record.items()}


def file_drops(path: Path, refs: dict) -> list[dict]:
    """The proposed drops of one footage file (see the module docstring)."""
    mel, _ = audio_features(str(path))
    clock = clock_track(str(path), CLOCK_CACHE)
    end_s = round(len(mel) / FPS, 2)
    cands: list[dict] = []

    ref, _ = refs["opening"]
    found = locate(ref, mel, 0, int(OPEN_SEARCH_S * FPS))
    if found:
        i, score = max(found, key=lambda m: m[1])
        b = heard(ref, mel, i)[1] / FPS
        cands.append({"start": 0.0, "end": b, "kind": "opening",
                      "why": f"opening fingerprint {score:.2f} at {i / FPS:.2f}, heard to {b:.2f}"})

    ref, _ = refs["credits"]
    found = locate(ref, mel, int(OPEN_SEARCH_S * FPS))
    if found:
        i, score = max(found, key=lambda m: m[1])
        t = heard(ref, mel, i)[0] / FPS
        cut = last_cut_before(frame_diffs(str(path), t - CREDITS_LEAD_S - 0.1, t + 0.1), t)
        cands.append({"start": t if cut is None else cut, "end": end_s, "kind": "credits",
                      "why": f"credits fingerprint {score:.2f}, heard from {t:.2f}; "
                             + ("no hard cut before it" if cut is None else f"hard cut into the credits at {cut:.2f}")})

    for name in ("sting_in", "sting_out"):
        ref, _ = refs[name]
        for i, score in locate(ref, mel):
            a, b = heard(ref, mel, i)
            cands.append({"start": a / FPS, "end": b / FPS, "kind": "bumper",
                          "why": f"{name} fingerprint {score:.2f}, heard {a / FPS:.2f}-{b / FPS:.2f}"})

    part = tv_part(clock)
    for a, b in (dips(clock, part) if part else []):
        sa = edge_in_second(frame_diffs(str(path), a - 1.1, a + 0.1), a)
        sb = edge_in_second(frame_diffs(str(path), b - 1.1, b + 0.1), b)
        cands.append({"start": sa, "end": sb, "kind": "clock_off",
                      "why": f"clock off {a}-{b} s (1 fps) in the TV part {part[0]}-{part[1]}"})
    return combine(cands)


# --- the check (pure over drops and gold) ----------------------------------------------------

def _cover(drops: list[dict]) -> list[tuple[float, float]]:
    return merged((d["start"], d["end"]) for d in drops)


def _overlap(spans, a: float, b: float) -> float:
    return sum(max(0.0, min(b, e) - max(a, s)) for s, e in spans)


def check_1120(drops: list[dict], end_s: float) -> list[str]:
    """One line per gold boundary of 20261120: measured edge, error, pass/fail (gated ones)."""
    cover, lines = _cover(drops), []
    for name, g0, g1, gate0, gate1 in GOLD_1120:
        g1 = end_s if g1 is None else g1
        hit = [s for s in cover if s[0] < g1 and s[1] > g0]
        if not hit:
            lines.append(f"FAIL 20261120 {name} {g0}-{g1}: no drop overlaps it")
            continue
        u0, u1 = hit[0][0], hit[-1][1]
        for which, gold, got, gate in (("start", g0, u0, gate0), ("end", g1, u1, gate1)):
            err = got - gold
            verdict = ("ok" if abs(err) <= TOL_S else "FAIL") if gate else "info"
            lines.append(f"{verdict} 20261120 {name} {which}: gold {gold:.2f}, drop {got:.2f} ({err:+.2f} s)")
    return lines


def check_kept(day: str, drops: list[dict], keeps: list[tuple[float, float]]) -> tuple[list[str], list[str]]:
    """(failures, expected): drops overlapping the YT keeps by ``KEEP_OVERLAP_S`` or more."""
    fails, expected = [], []
    for d in drops:
        kept = _overlap(keeps, d["start"], d["end"])
        if kept < KEEP_OVERLAP_S:
            continue
        line = f"{day} {d['kind']} {d['start']:.2f}-{d['end']:.2f}: {kept:.2f} s kept in YT"
        graphic = any(min(b, d["end"]) > max(a, d["start"]) for a, b in KEPT_GRAPHICS.get(day, []))
        (expected if graphic else fails).append(line)
    return fails, expected


def check_dips(day: str, drops: list[dict]) -> list[str]:
    """Audit dips whose inner part (first and last second off) the drops do not cover."""
    cover = _cover(drops)
    return [f"{day} dip {a}-{b} not covered ({(b - a - 2) - _overlap(cover, a + 1, b - 1):.2f} s open)"
            for a, b in AUDIT_DIPS.get(day, []) if _overlap(cover, a + 1, b - 1) < b - a - 2 - 1e-6]


# --- CLI -------------------------------------------------------------------------------------

def day_drops(folder: Path, refs: dict, out: Path = OUT) -> dict[str, list[dict]]:
    day = folder.name[:8]
    found = {}
    for p in _footage(folder):
        found[p.name] = file_drops(p, refs)
        update(day, p.name, "drops", found[p.name], out)
    return found


def check_day(folder: Path, found: dict[str, list[dict]]) -> tuple[list[str], list[str], list[str]]:
    """(failures, expected kept graphics, info lines) of the 2.2 check for one day."""
    day = folder.name[:8]
    gold = read_day(folder)
    fails, expected, info = [], [], []
    for name, drops in found.items():
        keeps = [(k.source_in, k.source_out) for k in gold.yt.keeps if k.media.lower() == name.lower()]
        f, e = check_kept(day, drops, keeps)
        fails += f
        expected += e
    dip_file = next(n for n in found if tv_part(clock_track(str(folder / "1. FOOTAGE" / n), CLOCK_CACHE)))
    fails += check_dips(day, found[dip_file])
    if day == "20261120":
        (name, drops), = found.items()
        lines = check_1120(drops, round(len(audio_features(str(folder / "1. FOOTAGE" / name))[0]) / FPS, 2))
        info += lines
        fails += [l for l in lines if l.startswith("FAIL")]
    return fails, expected, info


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--all", help="the folder holding the day folders")
    p.add_argument("--cut-refs", metavar="ROOT", help="cut the reference clips from the day folders under ROOT")
    p.add_argument("--check", action="store_true", help="run the 2.2 check")
    p.add_argument("--holdout", action="store_true", help="also the three holdout days, reported apart")
    p.add_argument("--out", default=str(OUT))
    args = p.parse_args(argv)
    if args.cut_refs:
        cut_refs(args.cut_refs)
    if not args.all:
        return
    out, refs = Path(args.out), load_refs()
    tuning, holdout = day_folders(args.all)
    fails, hold_fails = [], []
    for folder in tuning + (holdout if args.holdout else []):
        found = day_drops(folder, refs, out)
        n = sum(len(ds) for ds in found.values())
        print(f"{folder.name[:8]}: {n} drops, {sum(d['end'] - d['start'] for ds in found.values() for d in ds):.1f} s")
        for name, ds in found.items():
            for d in ds:
                print(f"    {d['start']:9.2f} {d['end']:9.2f} {d['kind']:9s} {d['why']}")
        if args.check:
            f, e, info = check_day(folder, found)
            for line in info + [f"expected (kept graphic): {x}" for x in e] + [x for x in f if x not in info]:
                print(f"  {line}")
            (hold_fails if folder in holdout else fails).extend(f)
    if args.check:
        print(f"tuning: {'ok' if not fails else f'{len(fails)} failures'}")
        if args.holdout:
            print(f"holdout: {'ok' if not hold_fails else f'{len(hold_fails)} failures: ' + '; '.join(hold_fails)}")
    sys.exit(1 if fails or hold_fails else 0)


if __name__ == "__main__":
    main()
