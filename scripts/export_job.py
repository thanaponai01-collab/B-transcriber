"""Export a job's tokens to SRT/VTT in output/.

Usage:
    python scripts/export_job.py <job_id> [<name>] [--db transcriber.db]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from transcribe.db.store import connect, get_tokens, get_job, get_media
from transcribe.pipeline.align_force import export_srt, export_vtt

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id", type=int)
    parser.add_argument("name", nargs="?", default=None, help="output filename stem (default: derived from source media)")
    parser.add_argument("--db", default=str(ROOT / "transcriber.db"))
    args = parser.parse_args()

    conn = connect(Path(args.db))
    tokens = get_tokens(conn, args.job_id)
    if not tokens:
        raise SystemExit(f"No tokens found for job {args.job_id}")

    if args.name:
        stem = args.name
    else:
        job = get_job(conn, args.job_id)
        media = get_media(conn, job.media_id) if job else None
        stem = Path(media.path).stem if media else f"job{args.job_id}"

    OUTPUT_DIR.mkdir(exist_ok=True)
    rows = [{"text": t.text, "start_ms": t.start_ms, "end_ms": t.end_ms} for t in tokens]
    srt_path = OUTPUT_DIR / f"{stem}.srt"
    vtt_path = OUTPUT_DIR / f"{stem}.vtt"
    export_srt(rows, str(srt_path))
    export_vtt(rows, str(vtt_path))
    print(f"Exported {len(rows)} tokens to {srt_path} / {vtt_path.name}")


if __name__ == "__main__":
    main()
