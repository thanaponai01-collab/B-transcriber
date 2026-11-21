"""Export one โหนกระแส episode's four deliverables through Media Encoder, in one command.

    python -m cutdeck.honekasae_export "<works folder>\\20261120 - โหนกระแส"
    python -m cutdeck.honekasae_export "<works folder>\\20261120 - โหนกระแส" --only FB "REEL 3M"
    python -m cutdeck.honekasae_export "<works folder>\\20261120 - โหนกระแส" --dry-run

Each version is exported from its sequence by name (the copy with content), with that
sequence's In/Out, to `<day folder>\\5. EXPORTS\\โหนกระแส <DDMMYY BE> <VERSION> D<n>.mp4`.
D counts per version: the next number after the highest one already in the folder (the
user's practice, see projects/hks/workflow-log.md). Jobs go to Media Encoder's queue, which
starts by itself. Needs the helper running and the CutDeck panel open in Premiere.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from cutdeck.ai_backend import Backend
from cutdeck.helper import PORT

# version in the file name -> the episode template's sequence name
VERSIONS = {
    "YT": "1 YOUTUBE D1",
    "FB": "2 FACEBOOK D1",
    "REEL 3M": "5 REEL 1-3 SIZE D1",
    "REEL 1M": "4 REEL SIZE D1",
}
PRESET = Path.home() / "Documents" / "Adobe" / "Adobe Media Encoder" / "27.0" / "Presets" / "BAS4.epr"
SHOW = "โหนกระแส"


def episode_date(day_folder: Path) -> str:
    """`20261120 - โหนกระแส` -> `201169` (day, month, Buddhist-Era year % 100)."""
    match = re.match(r"(\d{4})(\d{2})(\d{2})\b", day_folder.name)
    if not match:
        raise ValueError(f"day folder name must start with YYYYMMDD: {day_folder.name}")
    year, month, day = (int(part) for part in match.groups())
    return f"{day:02d}{month:02d}{(year + 543) % 100:02d}"


def next_output(exports: Path, date: str, version: str) -> Path:
    pattern = re.compile(rf"^{re.escape(SHOW)} {date} {re.escape(version)} D(\d+)\.mp4$")
    taken = [int(m.group(1)) for f in exports.iterdir() if (m := pattern.match(f.name))] if exports.is_dir() else []
    return exports / f"{SHOW} {date} {version} D{max(taken, default=0) + 1}.mp4"


def plan(day_folder: Path, versions: list[str]) -> list[dict]:
    exports = day_folder / "5. EXPORTS"
    date = episode_date(day_folder)
    return [{"version": v, "sequence_name": VERSIONS[v], "output_file": str(next_output(exports, date, v))}
            for v in versions]


async def run(jobs: list[dict], preset: Path, backend: Backend) -> list[dict]:
    results = []
    # One at a time (the panel refuses a second command while busy). All jobs go into AME's
    # queue first; only the last starts it, so the queue runs once with every version in it.
    for i, job in enumerate(jobs):
        result = await backend.premiere("export_sequence", {
            "output_file": job["output_file"], "preset_file": str(preset),
            "queue": "ame", "sequence_name": job["sequence_name"], "start": i == len(jobs) - 1})
        results.append({"version": job["version"], **result})
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a โหนกระแส episode's versions via Media Encoder")
    parser.add_argument("day_folder", type=Path)
    parser.add_argument("--only", nargs="+", choices=list(VERSIONS), default=list(VERSIONS))
    parser.add_argument("--preset", type=Path, default=PRESET)
    parser.add_argument("--dry-run", action="store_true", help="print the plan, export nothing")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args(argv)
    try:
        jobs = plan(args.day_folder, args.only)
        if args.dry_run:
            print(json.dumps(jobs, ensure_ascii=False, indent=2))
            return 0
        if not (args.day_folder / "5. EXPORTS").is_dir():
            raise ValueError(f"no 5. EXPORTS folder in {args.day_folder}")
        print(json.dumps(asyncio.run(run(jobs, args.preset, Backend(args.port))), ensure_ascii=False, indent=2))
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
