"""Export a job's tokens to SRT (default) next to the source media.

Usage:
    python scripts/export_job.py <job_id> [<name>] [--db transcriber.db]
    python scripts/export_job.py <job_id> --vtt          # also emit .vtt
    python scripts/export_job.py <job_id> --out-dir DIR  # override destination
"""

from __future__ import annotations

import argparse
from pathlib import Path

from transcribe.db.store import connect, get_tokens, get_job, get_media
from transcribe.pipeline.align_force import export_srt, export_vtt

ROOT = Path(__file__).resolve().parent.parent
FALLBACK_OUTPUT_DIR = ROOT / "output"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id", type=int)
    parser.add_argument("name", nargs="?", default=None, help="output filename stem (default: derived from source media)")
    parser.add_argument("--db", default=str(ROOT / "transcriber.db"))
    parser.add_argument("--fps", type=float, default=None,
                         help="target sequence frame rate (e.g. 23.976, 25, 29.97); "
                              "quantizes cue boundaries to frame ticks so Premiere import "
                              "doesn't re-round them. Varies per clip, so pass it explicitly.")
    parser.add_argument("--out-dir", default=None, help="destination directory (default: source media's directory)")
    parser.add_argument("--vtt", action="store_true", help="also export .vtt alongside .srt")
    args = parser.parse_args()

    conn = connect(Path(args.db))
    tokens = get_tokens(conn, args.job_id)
    if not tokens:
        raise SystemExit(f"No tokens found for job {args.job_id}")

    job = get_job(conn, args.job_id)
    media = get_media(conn, job.media_id) if job else None
    stem = args.name if args.name else (Path(media.path).stem if media else f"job{args.job_id}")

    if args.out_dir:
        out_dir = Path(args.out_dir)
    elif media and Path(media.path).parent.is_dir():
        out_dir = Path(media.path).parent
    else:
        out_dir = FALLBACK_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = [{"text": t.text, "start_ms": t.start_ms, "end_ms": t.end_ms} for t in tokens]
    srt_path = out_dir / f"{stem}.srt"
    export_srt(rows, str(srt_path), fps=args.fps)
    suffix = f" (quantized to {args.fps} fps)" if args.fps else ""

    if args.vtt:
        vtt_path = out_dir / f"{stem}.vtt"
        export_vtt(rows, str(vtt_path), fps=args.fps)
        print(f"Exported {len(rows)} tokens to {srt_path} / {vtt_path.name}{suffix}")
    else:
        print(f"Exported {len(rows)} tokens to {srt_path}{suffix}")


if __name__ == "__main__":
    main()
