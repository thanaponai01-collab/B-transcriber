"""Drive live Premiere from a terminal or any script, through the helper and the CutDeck panel.

    python -m cutdeck.premiere_cli status
    python -m cutdeck.premiere_cli read_sequence
    python -m cutdeck.premiere_cli apply_cuts <job_id>
    python -m cutdeck.premiere_cli add_markers markers.json   # [{"start_s": 1.5, "name": "..."}]

Prints the result as JSON. The helper (`python -m cutdeck.xml_bridge`) must be running and the
CutDeck panel open in Premiere. Python scripts can call `cutdeck.ai_backend.Backend().premiere`
directly instead (docs/arch-design-helper-v2.md move 3).
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

from cutdeck.ai_backend import Backend
from cutdeck.xml_bridge import PORT


async def run(args, backend: Backend):
    if args.command == "status":
        return await backend.premiere_status()
    if args.command == "read_sequence":
        return await backend.premiere("read_sequence")
    if args.command == "apply_cuts":
        return await backend.premiere("apply_cuts", {"job_id": args.target})
    markers = json.loads(Path(args.target).read_text(encoding="utf-8"))
    return await backend.premiere("add_markers", {"markers": markers})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live Premiere commands through the CutDeck panel")
    parser.add_argument("command", choices=["status", "read_sequence", "apply_cuts", "add_markers"])
    parser.add_argument("target", nargs="?", help="job_id for apply_cuts; a JSON file for add_markers")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args(argv)
    if args.command in ("apply_cuts", "add_markers") and not args.target:
        parser.error(f"{args.command} needs a {'job_id' if args.command == 'apply_cuts' else 'JSON file'}")
    try:
        result = asyncio.run(run(args, Backend(args.port)))
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
