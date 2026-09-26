"""The one table of commands the CutDeck panel drives in live Premiere.

The rule every command keeps: it runs as one Premiere transaction, or on a copy of the
sequence, and returns what it changed. Nothing here edits the user's original in steps.

A new command is: one entry in COMMANDS, its handler in `uxp/cutdeck/features/driver.js`
(with its name in that file's COMMANDS array) and one `premiere_<name>` MCP tool in
`cutdeck/mcp_server.py`. The helper's dispatch, `premiere_cli` and `ai_backend.capabilities`
read this table; `tests/test_cutdeck_driver_commands.py` fails if the pieces drift apart.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from cutdeck.xml_sequence import PPRO_TICKS_PER_SECOND

MAX_MARKERS = 5000


@dataclass(frozen=True)
class Command:
    timeout_s: int
    # (args the caller sent, job lookup) -> the arguments the panel receives
    prepare: Callable[[dict, Callable[[str], dict]], dict]
    doc: str
    # None: takes no CLI argument. Else (usage word, text from the CLI -> args for the command)
    cli_target: tuple[str, Callable[[str], dict]] | None = None


def _seconds_to_ticks(value, name: str) -> str:
    if type(value) not in (int, float) or not 0 <= value < 1e6:
        raise ValueError(f"{name} must be a number of seconds from 0")
    return str(round(value * PPRO_TICKS_PER_SECOND))


def _no_arguments(args: dict, jobs) -> dict:
    return {}


def _apply_cuts_arguments(args: dict, jobs) -> dict:
    job = jobs(args.get("job_id"))
    if job.get("job_type") != "cut" or job["state"] != "ready" or not job.get("cuts"):
        raise ValueError("apply_cuts needs a finished rough cut job with cuts")
    context = job.get("context") or {}
    return {"cuts": job["cuts"], "sequence_id": context.get("sequence_id"),
            "sequence_name": context.get("sequence_name"),
            "result_name": job.get("result_name") or f"CutDeck rough cut {job['job_id'][:8]}"}


def _marker_arguments(args: dict, jobs) -> dict:
    """Validate `add_markers`; the panel gets exact ticks, never float seconds."""
    markers = args.get("markers")
    if not isinstance(markers, list) or not 0 < len(markers) <= MAX_MARKERS:
        raise ValueError(f"markers must be a list of 1 to {MAX_MARKERS} markers")
    result = []
    for marker in markers:
        if not isinstance(marker, dict):
            raise ValueError("Each marker must be an object")
        name, comment = marker.get("name", ""), marker.get("comment", "")
        if not isinstance(name, str) or len(name) > 200 or not isinstance(comment, str) or len(comment) > 2000:
            raise ValueError("Marker name (max 200) and comment (max 2000) must be text")
        result.append({"start_ticks": _seconds_to_ticks(marker.get("start_s"), "start_s"),
                       "duration_ticks": _seconds_to_ticks(marker.get("duration_s", 0), "duration_s"),
                       "name": name, "comment": comment})
    return {"markers": result}


def _run_probe_arguments(args: dict, jobs) -> dict:
    probe = args.get("probe")
    valid = {"timing", "motion", "effect", "transform", "keyframe", "alcreate", "syncmoves", "nativecut"}
    if not isinstance(probe, str) or probe not in valid:
        raise ValueError(f"probe must be one of: {', '.join(sorted(valid))}")
    return {"probe": probe}


# apply_cuts edits a copy of a long sequence: 1735 cuts took minutes live (ledger 09-24).
COMMANDS: dict[str, Command] = {
    "read_sequence": Command(60, _no_arguments, "Read the active sequence."),
    "apply_cuts": Command(1800, _apply_cuts_arguments,
                          "Apply a finished rough cut job to a copy of the active sequence.",
                          ("job_id", lambda target: {"job_id": target})),
    "add_markers": Command(120, _marker_arguments, "Add markers to the active sequence.",
                           ("JSON file", lambda target: {
                               "markers": json.loads(Path(target).read_text(encoding="utf-8"))})),
    "run_probe": Command(300, _run_probe_arguments, "Run one diagnostic probe in live Premiere.",
                         ("probe_name", lambda target: {"probe": target})),
    "inspect_selection": Command(30, _no_arguments,
                                 "Inspect the selected track item(s) on the active sequence in live Premiere."),
}
