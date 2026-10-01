"""Is the live CutDeck stack up? Premiere running, helper listening, panel connected as the
driver, every command offered, a sequence readable, and what is selected.

`python -m cutdeck.live_check` prints one line per step; the exit code is 0 only when all
pass. tests/test_cutdeck_live_premiere.py runs the same steps before any live test, so a
missing piece fails with what to do instead of silently skipping."""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from dataclasses import dataclass

from cutdeck.ai_backend import Backend
from cutdeck.driver_commands import COMMANDS
from cutdeck.xml_bridge import PORT


@dataclass
class Step:
    name: str
    ok: bool
    detail: str


def premiere_running() -> bool:
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Adobe Premiere Pro.exe", "/NH"],
                             capture_output=True, text=True).stdout
        return "Adobe Premiere Pro.exe" in out
    if shutil.which("pgrep"):
        return subprocess.run(["pgrep", "-f", "Adobe Premiere Pro"], capture_output=True).returncode == 0
    return False


def check(port: int = PORT) -> tuple[list[Step], dict | None]:
    """Run the steps in order and stop at the first failure. Returns (steps, selection)."""
    steps: list[Step] = []
    backend = Backend(port)

    running = premiere_running()
    steps.append(Step("Premiere Pro is running", running,
                      "found the process" if running else "start Premiere Pro and open a project"))
    if not running:
        return steps, None

    label = f"CutDeck helper answers on 127.0.0.1:{port}"
    try:
        status = asyncio.run(backend.premiere_status())
    except Exception as exc:
        steps.append(Step(label, False, f"{exc} (or double-click Start CutDeck.cmd)"))
        return steps, None
    steps.append(Step(label, True, "reachable"))

    connected = bool(status.get("connected"))
    steps.append(Step("CutDeck panel is connected as the Premiere driver", connected,
                      "connected" if connected else "open the CutDeck panel in Premiere"))
    if not connected:
        return steps, None

    offered = set(status.get("commands", []))
    missing = [c for c in COMMANDS if c not in offered]
    steps.append(Step("panel offers every command the helper knows", not missing,
                      f"all {len(COMMANDS)} offered" if not missing else
                      f"panel is missing {missing}: it is an older build, reload the panel"))
    if missing:
        return steps, None

    try:
        seq = asyncio.run(backend.premiere("read_sequence"))
    except Exception as exc:
        steps.append(Step("a sequence can be read", False, f"{exc}. Open a sequence and set In and Out marks"))
        return steps, None
    steps.append(Step("a sequence can be read", True,
                      f"{seq.get('name')!r}, {seq.get('video_track_count')}V/{seq.get('audio_track_count')}A"))

    selection = asyncio.run(backend.premiere("inspect_selection"))
    # With nothing selected the panel lists every video clip, so selected_count is not the
    # selection: has_selection is.
    n = selection.get("selected_count", 0) if selection.get("has_selection") else 0
    steps.append(Step("selection", True,
                      "nothing selected: transform commands will only be refused" if n == 0 else
                      f"{n} clip(s) selected: transform, anchor, align and distribute WILL edit them"))
    return steps, selection


def main() -> int:
    steps, _ = check()
    for s in steps:
        print(("PASS  " if s.ok else "FAIL  ") + f"{s.name}: {s.detail}")
    return 0 if steps and all(s.ok for s in steps) else 1


if __name__ == "__main__":
    raise SystemExit(main())
