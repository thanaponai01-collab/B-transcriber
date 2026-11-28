"""The hand-labelled timing reference: a Praat labelling package out, the marked TextGrids back in.

`pack` writes one short WAV + empty TextGrid per clip span (plus a few blind repeats, to measure
label noise), named by random ids in shuffled order so no file says which split or clip it is.
The person marks, on the spectrogram, every onset after a pause (tier `onset`) and every offset
before a pause (tier `offset`) inside the `label` interval. Nothing is seeded from the pipeline:
speech the engine missed must still get marks.

`collect` reads the marked TextGrids back into one reference JSON per clip (clip-time ms):
tune and heldout into the repo's `reference/`, lockbox under the lockbox folder outside the repo,
and prints only the repeat-vs-original noise, never lockbox marks."""
from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
from pathlib import Path

from transcribe.eval.judge.prepare import MANIFEST, wav_path

PAD_S = 1.0
REPEATS = ("obs_tiw2", "hks_studio2", "obs_lec2")  # re-labelled blind, shifted, to measure label noise
REPEAT_SHIFT_S = 0.37
REFERENCE = Path(__file__).with_name("reference")
PRAAT = Path("E:/Me/5.Claude/praat/Praat.exe")


def textgrid(dur: float, a: float, b: float) -> str:
    return (f'File type = "ooTextFile"\nObject class = "TextGrid"\n\nxmin = 0\nxmax = {dur:.3f}\ntiers? <exists>\n'
            f'size = 3\nitem []:\n'
            f'    item [1]:\n        class = "IntervalTier"\n        name = "span"\n        xmin = 0\n        xmax = {dur:.3f}\n'
            f'        intervals: size = 3\n'
            f'        intervals [1]:\n            xmin = 0\n            xmax = {a:.3f}\n            text = ""\n'
            f'        intervals [2]:\n            xmin = {a:.3f}\n            xmax = {b:.3f}\n            text = "label"\n'
            f'        intervals [3]:\n            xmin = {b:.3f}\n            xmax = {dur:.3f}\n            text = ""\n'
            + "".join(f'    item [{i}]:\n        class = "TextTier"\n        name = "{name}"\n        xmin = 0\n'
                      f'        xmax = {dur:.3f}\n        points: size = 0\n' for i, name in ((2, "onset"), (3, "offset"))))


def read_points(text: str) -> dict[str, list[float]]:
    """Point times (s) per TextTier name, from a Praat TextGrid saved as a (long) text file."""
    out: dict[str, list[float]] = {}
    for block in re.split(r'(?m)^\s+class = "', text)[1:]:
        kind = block.split('"', 1)[0]
        name = re.search(r'name = "([^"]*)"', block).group(1)
        if kind == "TextTier":
            out[name] = sorted(float(t) for t in re.findall(r'(?:number|time) = ([0-9.eE+-]+)', block))
    return out


def from_marks(marks_dir: Path, label_dir: Path, out_dir: Path) -> int:
    """Agent marks (marks_dir/NN_xxxx.json: onset/offset seconds) written into copies of the
    package TextGrids, so they go through the same `collect` as marks made in Praat."""
    import shutil
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for m in sorted(marks_dir.glob("*.json")):
        d = json.loads(m.read_text(encoding="utf-8"))
        tg = (label_dir / f"{m.stem}.TextGrid").read_text(encoding="utf-8")
        for tier in ("onset", "offset"):
            pts = sorted(float(t) for t in d.get(tier, []))
            body = "".join(f'        points [{i}]:\n            number = {t:.4f}\n            mark = ""\n'
                           for i, t in enumerate(pts, 1))
            empty = "points: size = 0\n"
            j = tg.index(empty, tg.index(f'        name = "{tier}"\n'))
            tg = tg[:j] + f"points: size = {len(pts)}\n" + body + tg[j + len(empty):]
        (out_dir / f"{m.stem}.TextGrid").write_text(tg, encoding="utf-8")
        shutil.copy2(label_dir / f"{m.stem}.wav", out_dir / f"{m.stem}.wav")
        n += 1
    return n


def pack(out_dir: Path, key_path: Path, seed: int = 20261128) -> list[dict]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    jobs = [(c, 0.0, False) for c in manifest["clips"]]
    jobs += [(c, REPEAT_SHIFT_S, True) for c in manifest["clips"] if c["name"] in REPEATS]
    rng = random.Random(seed)
    rng.shuffle(jobs)
    first = next(i for i, (c, _, rep) in enumerate(jobs) if c["split"] == "tune" and not rep)
    jobs.insert(0, jobs.pop(first))  # the pilot (file 01) is a tune clip
    out_dir.mkdir(parents=True, exist_ok=True)
    key = []
    for n, (clip, shift, repeat) in enumerate(jobs, 1):
        fid = f"{n:02d}_{rng.randrange(16**4):04x}"
        a, b = clip["span"]
        lo = max(0.0, a - PAD_S - shift)
        dur = (b + PAD_S) - lo
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{lo:.3f}", "-t", f"{dur:.3f}", "-i",
                        str(wav_path(manifest, clip)), "-c:a", "pcm_s16le", str(out_dir / f"{fid}.wav")], check=True)
        (out_dir / f"{fid}.TextGrid").write_text(textgrid(dur, a - lo, b - lo), encoding="utf-8")
        key.append({"file": fid, "clip": clip["name"], "split": clip["split"], "offset_s": lo, "repeat": repeat})
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(json.dumps(key, indent=1), encoding="utf-8")
    return key


def _match_noise(a: list[float], b: list[float], tol_ms: float = 150) -> list[float]:
    """Signed ms differences between two markings of the same span, nearest one-to-one within tol."""
    pairs = sorted((abs(x - y), x, y) for x in a for y in b if abs(x - y) <= tol_ms)
    used_a, used_b, out = set(), set(), []
    for _, x, y in pairs:
        if x not in used_a and y not in used_b:
            used_a.add(x), used_b.add(y)
            out.append(y - x)
    return out


def normalized(tg: Path, tmp: Path) -> str:
    """The TextGrid as Praat's long text form, whichever way it was saved (short text, UTF-16,
    binary): Praat itself reads it and writes it back."""
    out = tmp / f"{tg.stem}.long.TextGrid"
    script = tmp / "normalize.praat"
    script.write_text(f'Read from file: "{tg}"' + chr(10) + f'Save as text file: "{out}"' + chr(10), encoding="utf-8")
    subprocess.run([str(PRAAT), "--run", str(script)], check=True, capture_output=True)
    raw = out.read_bytes()
    return raw.decode("utf-16") if raw[:2] in (bytes([255, 254]), bytes([254, 255])) else raw.decode("utf-8")


def collect(label_dir: Path, key_path: Path, lockbox_dir: Path, source: str = "praat-user") -> dict:
    """Read every marked TextGrid. A file Praat cannot read stops the run; a file with no marks is
    listed as not labelled yet. Lockbox files are moved out of the labels folder once read."""
    import tempfile
    key = json.loads(key_path.read_text(encoding="utf-8"))
    marks: dict[tuple[str, bool], dict[str, list[float]]] = {}
    unlabelled = []
    with tempfile.TemporaryDirectory() as tmp:
        for k in key:
            tg = label_dir / f"{k['file']}.TextGrid"
            moved = lockbox_dir / "labelled" / tg.name
            src = tg if tg.exists() else moved
            pts = read_points(normalized(src, Path(tmp)))
            if not (pts.get("onset") or pts.get("offset")):
                unlabelled.append(k["file"])
                continue
            marks[(k["clip"], k["repeat"])] = {t: [round((s + k["offset_s"]) * 1000, 1) for s in pts.get(t, [])]
                                               for t in ("onset", "offset")}
            if k["split"] == "lockbox" and src == tg:
                moved.parent.mkdir(parents=True, exist_ok=True)
                tg.replace(moved)
                (label_dir / f"{k['file']}.wav").replace(moved.with_suffix(".wav"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    REFERENCE.mkdir(exist_ok=True)
    counts = {}
    for clip in manifest["clips"]:
        m = marks.get((clip["name"], False))
        if m is None or not (m["onset"] or m["offset"]):
            continue
        dest = (lockbox_dir / "reference") if clip["split"] == "lockbox" else REFERENCE
        dest.mkdir(parents=True, exist_ok=True)
        (dest / f"{clip['name']}.json").write_text(json.dumps({"clip": clip["name"], "source": source, "span_ms": [clip["span"][0] * 1000, clip["span"][1] * 1000], **m}, indent=1), encoding="utf-8")
        counts.setdefault(clip["split"], 0)
        counts[clip["split"]] += len(m["onset"]) + len(m["offset"])
    noise = []
    for name in REPEATS:
        o, r = marks.get((name, False)), marks.get((name, True))
        if o and r:
            for t in ("onset", "offset"):
                noise += _match_noise(o[t], r[t])
    return {"edges_per_split": counts, "not_labelled_yet": unlabelled, "repeat_pairs": len(noise),
            "repeat_abs_ms_median": sorted(abs(x) for x in noise)[len(noise) // 2] if noise else None}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("action", choices=["pack", "collect"])
    p.add_argument("--labels", default="E:/Me/5.Claude/timing-judge-labels")
    p.add_argument("--source", default="praat-user", help="who marked them (stored in each reference file)")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    lockbox = Path(manifest["lockbox_dir"])
    key_path = lockbox / "label_key.json"
    if args.action == "pack":
        key = pack(Path(args.labels), key_path)
        print(f"{len(key)} files in {args.labels}")
    else:
        print(json.dumps(collect(Path(args.labels), key_path, lockbox, args.source), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
