"""How different are our sources as audio? Loudness and noise-floor spread (read-only).

For every transcribed source still on disk (``media`` table) plus a few untranscribed shows:
  - ffprobe: audio streams, channels, layout
  - EBU R128 (ffmpeg loudnorm, measure only): integrated LUFS, loudness range, true peak
  - the shared 10 ms envelope (cutdeck.timeline_transcript.source_levels): 5th percentile
    (the file floor rule C uses, before levels.FLOOR_CLAMP_DB), median and 95th percentile
  - what the fixed rules see: share of time below -35 dB (rule A, silencedetect) and below
    floor + 6 dB (rule C)
  - channels (first 10 min): per-channel level, how often one channel is 10+ dB quieter than
    the other while the louder one has sound, and their sample correlation, because ingest and
    source_levels average channels into mono.

    python tools/measure_audio_condition.py --json output/audio_condition/sources.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cutdeck.timeline_transcript import level_db, source_levels  # noqa: E402
from transcribe.audio.levels import floor as noise_floor  # noqa: E402

EXTRA = [  # shows with no transcript yet, one file each
    r"G:\Me\Works\20261007 - คชาภา EP33\1. FOOTAGE",
    r"G:\Me\Works\20261015 - พุธทอล์คพุธโทร 234\1. FOOTAGE",
    r"G:\Me\Works\20261022 - CFD 97\1. FOOTAGE",
]
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def sources(db: Path) -> list[str]:
    conn = sqlite3.connect(db)
    try:
        paths = [r[0] for r in conn.execute("SELECT path FROM media") if r[0]]
    finally:
        conn.close()
    seen, out = set(), []
    for p in paths + [str(next(Path(d).glob("*.mp4"))) for d in EXTRA if Path(d).is_dir()]:
        key = os.path.normcase(os.path.abspath(p))
        if key not in seen and os.path.isfile(p) and os.path.getsize(p) > 30e6:
            seen.add(key)
            out.append(p)
    return sorted(out)


def probe(path: str) -> list[dict]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                          "stream=index,codec_name,sample_rate,channels,channel_layout", "-of", "json", path],
                         capture_output=True, text=True, encoding="utf-8", **NO_WINDOW)
    return json.loads(out.stdout or "{}").get("streams", [])


def r128(path: str) -> dict:
    out = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", path, "-map", "0:a:0", "-vn",
                          "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", **NO_WINDOW)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", out.stderr)
    if not m:
        return {}
    j = json.loads(m.group(0))
    return {"lufs": float(j["input_i"]), "lra": float(j["input_lra"]), "true_peak": float(j["input_tp"])}


def channels(path: str, n_ch: int, seconds: int = 600, sr: int = 16000) -> dict | None:
    if n_ch < 2:
        return None
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-t", str(seconds), "-i", path, "-map", "0:a:0",
                          "-vn", "-ac", "2", "-ar", str(sr), "-f", "f32le", "pipe:1"],
                         capture_output=True, **NO_WINDOW).stdout
    x = np.frombuffer(raw[:len(raw) - len(raw) % 8], dtype=np.float32).reshape(-1, 2)
    if len(x) < sr:
        return None
    left, right = level_db(x[:, 0].copy(), sr), level_db(x[:, 1].copy(), sr)
    loud = np.maximum(left, right)
    sound = loud > noise_floor(loud) + 10
    diff = (left - right)[sound]
    corr = float(np.corrcoef(x[:, 0], x[:, 1])[0, 1]) if x[:, 0].std() and x[:, 1].std() else None
    return {"median_l_minus_r_db": round(float(np.median(diff)), 1) if len(diff) else None,
            "one_side_10db_quieter": round(float(np.mean(np.abs(diff) >= 10)), 3) if len(diff) else None,
            "sample_corr": None if corr is None else round(corr, 3)}


def measure(path: str, cache_dir: Path) -> dict:
    streams = probe(path)
    rec = {"path": path, "kind": "export" if "EXPORTS" in path else "raw",
           "audio_streams": len(streams),
           "layout": [f"{s.get('channels')}ch {s.get('channel_layout', '')}".strip() for s in streams]}
    if not streams:
        return rec
    cache = cache_dir / (hashlib.sha1(os.path.abspath(path).encode()).hexdigest() + ".npy")
    lev = np.asarray(source_levels(path, cache))
    live = lev[lev > -120.0]  # digital silence is not the room
    p5, p50, p95 = (float(np.percentile(live, q)) for q in (5, 50, 95))
    floor_c = noise_floor(lev)
    rec.update(r128(path))
    rec.update({
        "minutes": round(len(lev) / 6000, 1),
        "digital_silence": round(1 - len(live) / max(len(lev), 1), 3),
        "p5_db": round(p5, 1), "p50_db": round(p50, 1), "p95_db": round(p95, 1),
        "floor_c_db": round(floor_c, 1), "floor_clamped": not (-65.0 < float(np.percentile(lev, 5)) < -35.0),
        "span_p95_minus_floor_db": round(p95 - floor_c, 1),
        "quiet_A_below_-35": round(float(np.mean(lev < -35.0)), 3),
        "quiet_C_below_floor+6": round(float(np.mean(lev < floor_c + 6.0)), 3),
        "channels": channels(path, int(streams[0].get("channels") or 1)),
    })
    print(f"done {Path(path).name}", file=sys.stderr, flush=True)
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "transcriber.db"))
    ap.add_argument("--cache", default=str(ROOT / "output" / "audio_condition" / "levels"))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--json", required=True)
    args = ap.parse_args(argv)
    cache_dir = Path(args.cache)
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths = sources(Path(args.db))
    print(f"{len(paths)} sources", file=sys.stderr)

    def safe(p):
        try:
            return measure(p, cache_dir)
        except Exception as e:  # one unreadable file must not lose the rest
            return {"path": p, "error": str(e)}

    with ThreadPoolExecutor(args.workers) as pool:
        rows = list(pool.map(safe, paths))
    Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
