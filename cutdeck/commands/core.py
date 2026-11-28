"""What the command table (cutdeck/driver_commands.py) and the command families in cutdeck/commands/
share: the Command type and the argument checks more than one family uses."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Awaitable, Callable

# Runs one command through the helper and returns its result: the helper's own dispatch, or
# `Backend().premiere` in a script.
Premiere = Callable[[str, dict], Awaitable]


@dataclass(frozen=True)
class Command:
    timeout_s: int
    # (args the caller sent, job lookup) -> the arguments the command receives
    prepare: Callable[[dict, Callable[[str], dict]], dict]
    # MCP hint: read (changes nothing), write, destructive, or outside (Adobe's own service)
    hint: str
    doc: str  # the premiere_<name> MCP tool's description
    # The MCP tool's parameters: (name, type) or (name, type, default). A None argument whose
    # default is None is left out, so the command sees it as not given.
    params: tuple[tuple, ...]
    # None: takes no CLI argument. Else (usage word, text from the CLI -> args for the command)
    cli_target: tuple[str, Callable[[str], dict]] | None = None
    # None: the CutDeck panel runs it. Else the helper runs it (Win32 routes: menu, keys, window
    # pixels, Adobe's AI Assistant), with `premiere` for any panel command it needs on the way.
    run: Callable[[dict, Premiere], Awaitable] | None = None
    # The ROUTES this command takes, its own and those of the commands it runs on the way.
    routes: tuple[str, ...] = ("uxp",)


PIECE_SUFFIX = " (CutDeck piece)"  # the only sequences remove_piece deletes


def _ticks(value, name: str, signed: bool = False) -> str:
    if not (isinstance(value, str) and re.fullmatch(r"-?\d+" if signed else r"\d+", value)):
        raise ValueError(f"{name} must be a tick string{' (may be negative)' if signed else ''}")
    return value


def _range_arguments(args: dict) -> dict:
    result = {"in_ticks": _ticks(args.get("in_ticks"), "in_ticks"), "out_ticks": _ticks(args.get("out_ticks"), "out_ticks")}
    if int(result["out_ticks"]) <= int(result["in_ticks"]):
        raise ValueError("out_ticks must be after in_ticks")
    return result
