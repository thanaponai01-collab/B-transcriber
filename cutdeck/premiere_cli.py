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
from cutdeck.driver_commands import COMMANDS
from cutdeck.xml_bridge import PORT


async def run(args, backend: Backend):
    if args.command == "status":
        return await backend.premiere_status()
    cli_target = COMMANDS[args.command].cli_target
    return await backend.premiere(args.command, cli_target[1](args.target) if cli_target else {})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live Premiere commands through the CutDeck panel")
    parser.add_argument("command", choices=["status", *COMMANDS])
    parser.add_argument("target", nargs="?", help="job_id for apply_cuts; a JSON file for add_markers")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args(argv)
    cli_target = COMMANDS[args.command].cli_target if args.command != "status" else None
    if cli_target and not args.target:
        parser.error(f"{args.command} needs a {cli_target[0]}")
    try:
        result = asyncio.run(run(args, Backend(args.port)))
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
