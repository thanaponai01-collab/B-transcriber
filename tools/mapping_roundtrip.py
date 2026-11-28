"""Round-trip check of cutdeck.timeline_transcript's mapping against Premiere's own render.

For every mapped clip of one audio track, the mapping predicts which source time plays at each
sequence time: ``source = in + (t - start) * speed``. This script cuts a window of the exported
audio at the clip, finds where that sound sits in the source (normalised cross-correlation, the
source optionally resampled by the clip's speed), and reports the difference in ms.

    lag_ms > 0: the sound plays LATER on the timeline than the mapping says.

Clips come from a saved project (``--prproj``, via timeline_from_prproj) or from a live
``read_timeline`` result saved as JSON (``--timeline-json``). No Premiere needed for either.

    python tools/mapping_roundtrip.py --prproj P --sequence yt --export X.mp4 --out DIR
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cutdeck.timeline_transcript import TICKS_PER_MS, audio_clips, timeline_from_prproj  # noqa: E402

SR = 16000


def decode(path: str, stream: str = "0:a:0") -> np.ndarray:
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-map", stream, "-ac", "1", "-ar", str(SR),
           "-f", "f32le", "pipe:1"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, dtype=np.float32)


def start_times(path: str) -> list[float]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=start_time",
                          "-of", "csv=p=0", path], capture_output=True, text=True).stdout.split()
    return [float(x) for x in out if x not in ("", "N/A")]


def ncc_lag(seg: np.ndarray, win: np.ndarray) -> tuple[int, float]:
    """(offset of seg inside win in samples, peak normalised correlation)."""
    from scipy.signal import fftconvolve
    seg = seg - seg.mean()
    num = fftconvolve(win, seg[::-1], mode="valid")
    c2 = np.concatenate(([0.0], np.cumsum(win.astype(np.float64) ** 2)))
    energy = c2[len(seg):] - c2[:-len(seg)]
    den = np.sqrt(np.maximum(energy, 1e-12) * float((seg ** 2).sum()))
    r = num / den
    k = int(np.argmax(r))
    return k, float(r[k])


def check(clips, export: np.ndarray, sources: dict[str, np.ndarray], search_ms: int = 500,
          seg_ms: int = 3000, min_ms: int = 600) -> list[dict]:
    rows = []
    for c in clips:
        start_ms, end_ms = c.start / TICKS_PER_MS, c.end / TICKS_PER_MS
        if end_ms - start_ms < min_ms:
            continue
        a_ms = start_ms + 50
        b_ms = min(end_ms - 50, a_ms + seg_ms)
        seg = export[int(a_ms * SR / 1000):int(b_ms * SR / 1000)]
        if len(seg) < SR // 4 or float(np.abs(seg).max()) < 1e-4:
            continue  # silent on the export: nothing to correlate
        src = sources[c.media]
        pred_ms = c.in_ / TICKS_PER_MS + (a_ms - start_ms) * c.speed  # source time playing at a_ms
        lo_ms = pred_ms - search_ms * c.speed
        span_ms = (b_ms - a_ms) * c.speed + 2 * search_ms * c.speed
        lo = int(lo_ms * SR / 1000)
        win = src[max(lo, 0):max(lo, 0) + int(span_ms * SR / 1000)]
        if c.speed != 1.0:  # play the source at the clip's speed (Premiere's default: pitch follows speed)
            from scipy.signal import resample
            win = resample(win, int(round(len(win) / c.speed))).astype(np.float32)
        if len(win) <= len(seg):
            continue
        k, peak = ncc_lag(seg, win)
        found_src_ms = max(lo, 0) * 1000 / SR + k * 1000 / SR * c.speed
        d_src = found_src_ms - pred_ms  # the export plays source pred + d at a_ms
        rows.append({"clip": c.id, "media": Path(c.media).name, "speed": c.speed, "seq_start_s": round(start_ms / 1000, 4),
                     "src_in_s": round(c.in_ / TICKS_PER_MS / 1000, 4), "lag_ms": round(-d_src / c.speed, 2),
                     "ncc": round(peak, 3)})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prproj")
    ap.add_argument("--sequence")
    ap.add_argument("--timeline-json", help="a read_timeline result saved as JSON (the live path)")
    ap.add_argument("--export", required=True, help="Premiere's render of the sequence")
    ap.add_argument("--track", default="A1")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--min-ncc", type=float, default=0.6)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.timeline_json:
        timeline, path = json.loads(Path(args.timeline_json).read_text(encoding="utf-8")), "read_timeline"
    else:
        from cutdeck.prproj_reader import read_project
        seq = next(s for s in read_project(args.prproj)["sequences"] if s["name"] == args.sequence)
        timeline, path = timeline_from_prproj(seq, args.fps), "prproj"
    track, clips, skipped = audio_clips(timeline, args.track)
    export = decode(args.export)
    sources = {m: decode(m) for m in {c.media for c in clips}}
    rows = check(clips, export, sources)
    good = [r for r in rows if r["ncc"] >= args.min_ncc]
    lags = np.array([r["lag_ms"] for r in good]) if good else np.zeros(0)
    frame_ms = 1000 / args.fps
    summary = {"path": path, "track": track, "clips": len(clips), "skipped": skipped, "checked": len(rows),
               "reliable": len(good), "min_ncc": args.min_ncc,
               "export_start_times": start_times(args.export),
               "source_start_times": {Path(m).name: start_times(m) for m in sources}}
    if len(lags):
        summary.update({"lag_median_ms": float(np.median(lags)), "lag_max_abs_ms": float(np.abs(lags).max()),
                        "lag_p99_abs_ms": float(np.percentile(np.abs(lags), 99)),
                        "within_half_frame": float((np.abs(lags) <= frame_ms / 2).mean()),
                        "within_1ms": float((np.abs(lags) <= 1).mean()),
                        "max_abs_frames": float(np.abs(lags).max() / frame_ms)})
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"roundtrip-{path}-{track}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1,
                                                                   ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
