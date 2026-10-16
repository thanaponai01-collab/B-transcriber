"""One native Add Edit to All Tracks, through the CutDeck Cutter Probe Control Surface plugin
(tools/native-cutter-spike). UXP has no razor on 26.x (docs/PREMIERE_FACTS.md), so the panel sets
the sequence and playhead, and this hands the plugin a one-shot request file.

The request carries no command: the plugin runs only `cmd.sequence.razorateditline.all`, and only
when Premiere's displayed timecode equals `expected_timecode`. It deletes the file before running,
so one request runs once at most. Plan: docs/research/cutdeck-native-cutter-2026-10-16.md."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import tempfile
import time
import uuid

FOLDER = Path(tempfile.gettempdir()) / "CutDeckCutterSpike"
PICKUP_TIMEOUT_S = 10.0  # the plugin refuses requests older than this anyway
GRACE_S = 2.0  # after the plugin has taken the request, for its result file
POLL_S = 0.1
_TIMECODE = re.compile(r"\d{2}:\d{2}:\d{2}:\d{2,3}")


def _write_request(folder: Path, nonce: str, expected: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    request = folder / f"request-{nonce}.txt"
    partial = folder / f"partial-request-{nonce}"  # not request-*.txt: the plugin never sees a half-written file
    partial.write_bytes(f"{nonce}\n{expected}\n{int(time.time() * 1000)}\n".encode("ascii"))
    os.replace(partial, request)
    return request


# The plugin's result fields -> this protocol's reply fields.
_REPLY = {"nonce": "nonce", "status": "status", "reason": "reason", "error": "error", "context": "context",
          "command": "command", "expected": "expected", "timeBefore": "time_before", "timeAfter": "time_after",
          "displayMode": "display_mode", "pickupMs": "pickup_ms", "pid": "pid"}


def _take_result(path: Path) -> dict | None:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    path.unlink(missing_ok=True)
    return {_REPLY[k]: v for k, v in result.items() if k in _REPLY}


async def request_split(expected_timecode, folder: Path | None = None, timeout_s: float = PICKUP_TIMEOUT_S,
                        grace_s: float = GRACE_S) -> dict:
    """The plugin's result, or {"status": "not_picked_up"} (the request was withdrawn unrun) or
    {"status": "unknown"} (the plugin took it but wrote no result: it may have run)."""
    if not isinstance(expected_timecode, str) or not _TIMECODE.fullmatch(expected_timecode):
        raise ValueError("expected_timecode must be hh:mm:ss:ff")
    folder = folder or FOLDER
    if any(folder.glob("request-*.txt")):
        raise ValueError("A native split request is already waiting")
    nonce = uuid.uuid4().hex
    request = _write_request(folder, nonce, expected_timecode)
    result_path = folder / f"result-{nonce}.json"
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if (result := _take_result(result_path)) is not None:
            return result
        await asyncio.sleep(POLL_S)
    try:
        request.unlink()
        return {"status": "not_picked_up", "nonce": nonce,
                "message": "The Cutter Probe plugin did not take the request. Is it enabled under Control Surface?"}
    except FileNotFoundError:
        pass  # taken just now: wait for its result
    deadline = loop.time() + grace_s
    while loop.time() < deadline:
        if (result := _take_result(result_path)) is not None:
            return result
        await asyncio.sleep(POLL_S)
    return {"status": "unknown", "nonce": nonce,
            "message": "The plugin took the request but wrote no result; it may have cut. Check the sequence."}
