"""Run any Premiere command that has a keyboard shortcut, by pressing that shortcut.

The UXP panel cannot razor, link, ripple-trim, target tracks or undo
(docs/PREMIERE_CONTROL_MAP.md). Premiere's shortcut file (.kys) names every bindable command
(`cmd.sequence.razorateditline`, `cmd.edit.undo`, ...) with its key, so pressing the key is a
route to those commands that needs no plugin. Commands act on the FOCUSED panel, so a command is
sent after the shortcut that focuses its panel (`uif.window.Timelines`, Shift+3 by default).
Pressing keys proves nothing: read the result back (premiere_read_timeline).

Live rules (Premiere 27.0, 2026-11-21, docs/PREMIERE_FACTS.md "Keyboard route"):
- The Timelines shortcut pressed while a timeline already has focus switches to the NEXT open
  sequence. So the timeline is focused through the menu instead (Window > Timelines > <name>,
  cutdeck/menu.py), which names the sequence; focus_panel's Project-then-Timelines keys are the
  fallback for other panels.
- `Project.openSequence` from the panel takes focus away from the timeline.
- A Ctrl+Alt binding (the user's Ctrl+Alt+Z for Add Edit to All Tracks) did nothing when sent,
  while the same command's Ctrl+Shift+K cut exactly at the playhead. Ctrl+Alt bindings are
  picked last.

.kys key codes (inferred from Premiere 27.0's defaults, 2026-11-21): a value with bit 31 set is a
character (`0x8000004B` = "K"); smaller values are Premiere's own codes for special keys
(KEY_CODES). A code not in that table is refused, never guessed.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
import os
import re
import time
import xml.etree.ElementTree as ET

from cutdeck import screenshot

DEFAULTS = Path(r"C:\Program Files\Adobe\Adobe Premiere Pro 2027\Keyboard Shortcuts\en\Adobe Premiere Pro Defaults.kys")
PROFILE_ROOT = Path(os.path.expanduser(r"~\Documents\Adobe\Premiere Pro"))

# Premiere special-key code -> Windows virtual key. Each inferred from a well-known default binding.
KEY_CODES = {
    0x01: 0x20,  # Space       cmd.transport.toggleplay
    0x02: 0x08,  # Backspace   cmd.edit.clear (timeline)
    0x03: 0x09,  # Tab         cmd.project.nextcolumnfield
    0x04: 0x0D,  # Enter       cmd.sequence.preview
    0x07: 0x70,  # F1          cmd.help.contents
    0x23: 0x2E,  # Delete      cmd.edit.clear, Shift = cmd.edit.rippledelete
    0x24: 0x24,  # Home        cmd.transport.sequence.start
    0x25: 0x23,  # End         cmd.transport.sequence.end
    0x26: 0x21,  # Page Up     cmd.timeline.show.previous.screen
    0x27: 0x22,  # Page Down   cmd.timeline.show.next.screen
    0x2A: 0x25,  # Left        cmd.capture.step.back
    0x2B: 0x27,  # Right       cmd.capture.step.forward
    0x2C: 0x26,  # Up          nudge up
    0x2D: 0x28,  # Down        nudge down
}
FOCUS = {  # panel -> the command that focuses it (Window menu shortcuts)
    "timeline": "uif.window.Timelines",
    "program": "uif.window.Program Monitors",
    "source": "uif.window.Source Monitors",
    "project": "uif.window.Projects",
    "effect_controls": "uif.window.Effect Controls",
}
# Never pressed for an agent: quitting/closing loses work, and exports are the user's (memory rule).
BLOCKED = re.compile(r"exit|quit|close|export|saveas|save\.as|file\.new|file\.open|revert|render\.(all|inout)|cmd\.file\.save$", re.I)


@dataclass(frozen=True)
class Shortcut:
    command: str
    context: str
    ctrl: bool
    shift: bool
    alt: bool
    code: int

    def keys(self) -> str:
        return "+".join([m for m, on in (("Ctrl", self.ctrl), ("Shift", self.shift), ("Alt", self.alt)) if on] + [key_name(self.code)])


def key_name(code: int) -> str:
    if code & 0x80000000 and not code & 0x40000000:
        return chr(code & 0xFFFF)
    names = {0x01: "Space", 0x02: "Backspace", 0x03: "Tab", 0x04: "Enter", 0x07: "F1", 0x23: "Delete", 0x24: "Home",
             0x25: "End", 0x26: "PageUp", 0x27: "PageDown", 0x2A: "Left", 0x2B: "Right", 0x2C: "Up", 0x2D: "Down"}
    return names.get(code, f"code {code:#x}")


def active_kys() -> Path:
    """The user's newest .kys in the newest Premiere profile, else Premiere's defaults."""
    found = sorted(PROFILE_ROOT.glob("*/Profile-*/Win/*.kys"), key=lambda p: (p.parts[-4], p.stat().st_mtime))
    return found[-1] if found else DEFAULTS


def load(path: Path | None = None, mode: str = "Edit") -> dict[str, list[Shortcut]]:
    """command -> its shortcuts in workspace mode `mode` (Edit or Color), in file order."""
    root = ET.parse(path or active_kys()).getroot()
    table: dict[str, list[Shortcut]] = {}
    for mode_el in root.find("shortcuts"):
        if mode_el.tag != f"mode.{mode}":
            continue
        for ctx in mode_el:
            for item in ctx:
                code = item.findtext("virtualkey")
                if not item.tag.startswith("item") or code is None:
                    continue
                flag = lambda name: item.findtext(f"modifier.{name}") == "true"
                table.setdefault(item.findtext("commandname"), []).append(
                    Shortcut(item.findtext("commandname"), ctx.tag.removeprefix("context."), flag("ctrl"), flag("shift"), flag("alt"), int(code)))
    return table


def pressable(sc: Shortcut) -> bool:
    return (sc.code & 0x80000000 and not sc.code & 0x40000000) or sc.code in KEY_CODES


def pick(table: dict[str, list[Shortcut]], command: str) -> Shortcut:
    if BLOCKED.search(command):
        raise ValueError(f"{command} is never pressed for an agent (quit, close, open, export or save-as)")
    options = [s for s in table.get(command, []) if pressable(s)]
    if not options:
        bound = table.get(command)
        raise ValueError(f"{command} has no shortcut in {active_kys().name}" if not bound
                         else f"{command} is bound only to keys CutDeck cannot press yet ({', '.join(s.keys() for s in bound)})")
    # Global context first; Ctrl+Alt bindings last (one did nothing live); then fewer modifiers.
    return sorted(options, key=lambda s: (s.context != "global", s.ctrl and s.alt, s.ctrl + s.shift + s.alt))[0]


def list_commands(query: str = "", path: Path | None = None) -> list[dict]:
    q = query.lower()
    return [{"command": c, "keys": [s.keys() for s in shortcuts], "context": shortcuts[0].context,
             "pressable": any(pressable(s) for s in shortcuts) and not BLOCKED.search(c)}
            for c, shortcuts in sorted(load(path).items()) if q in c.lower()]


# --- pressing keys (Windows) ---------------------------------------------------------------------

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


_EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2E}


def _vk_for(code: int) -> tuple[int, bool]:
    """Windows virtual key for a .kys code, and whether the character itself needs Shift."""
    if code in KEY_CODES:
        return KEY_CODES[code], False
    scan = ctypes.windll.user32.VkKeyScanW(ctypes.c_wchar(chr(code & 0xFFFF)))
    if scan == -1 or scan & 0xFF == 0xFF:
        raise ValueError(f"no key on this keyboard types {chr(code & 0xFFFF)!r}")
    return scan & 0xFF, bool(scan & 0x100)


def _send(vks_down: list[int]) -> None:
    user32 = ctypes.windll.user32
    events = []
    for vk in vks_down + vks_down[::-1]:
        up = len(events) >= len(vks_down)
        flags = (0x0002 if up else 0) | (0x0001 if vk in _EXTENDED else 0)
        events.append(_INPUT(type=1, ki=_KEYBDINPUT(vk, user32.MapVirtualKeyW(vk, 0), flags, 0, 0)))
    array = (_INPUT * len(events))(*events)
    if user32.SendInput(len(events), array, ctypes.sizeof(_INPUT)) != len(events):
        raise RuntimeError("SendInput was blocked")


def press(sc: Shortcut) -> None:
    vk, char_shift = _vk_for(sc.code)
    mods = [m for m, on in ((0x11, sc.ctrl), (0x10, sc.shift or char_shift), (0x12, sc.alt)) if on]
    _send(mods + [vk])


def _bring_to_front(hwnd: int) -> bool:
    user32 = ctypes.windll.user32
    if user32.GetForegroundWindow() == hwnd:
        return True
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    _send([0x12])  # a lone Alt press lets this process set the foreground window
    user32.SetForegroundWindow(hwnd)
    for _ in range(20):
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.05)
    return False


def window_title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def focus_panel(panel: str) -> dict:
    """Bring Premiere forward and focus `panel`. The timeline is reached through the Project panel
    so the press never switches to another open sequence."""
    if panel not in FOCUS:
        raise ValueError(f"focus must be one of {', '.join(FOCUS)}")
    table = load()
    hwnd = screenshot.premiere_window()
    if not _bring_to_front(hwnd):
        raise RuntimeError("Premiere could not be brought to the front; nothing was pressed")
    steps = (["project"] if panel == "timeline" else []) + [panel]
    for step in steps:
        press(pick(table, FOCUS[step]))
        time.sleep(0.3)
    return {"focused": panel, "keys": [pick(table, FOCUS[step]).keys() for step in steps]}


def press_command(command: str, settle_s: float = 0.5) -> dict:
    """Press `command`'s shortcut in the foreground Premiere window (call focus() first)."""
    table = load()
    target = pick(table, command)
    hwnd = screenshot.premiere_window()
    if ctypes.windll.user32.GetForegroundWindow() != hwnd and not _bring_to_front(hwnd):
        raise RuntimeError("Premiere is not in front; the command was not pressed")
    before = window_title(hwnd)
    press(target)
    time.sleep(settle_s)
    after = window_title(hwnd)
    return {"command": command, "keys": target.keys(), "context": target.context,
            "shortcuts_file": active_kys().name,
            # The title gains " *" when the project changes: a quick no-op signal, never proof.
            "project_marked_changed": after.endswith("*") and not before.endswith("*"),
            "already_unsaved": before.endswith("*"),
            "note": "A pressed key is not proof: read the result back (premiere_read_timeline)."}


async def run_focused(premiere, focus: str | None, sequence: str | None, action) -> dict:
    """Run `action()` (a blocking call that presses or posts the command) on the right sequence:
    open `sequence` (or keep the active one), focus the panel, check the active sequence did not
    move, and only then act. Shared by the key route and the menu route (cutdeck/menu.py).
    `premiere(command, args)` runs a panel command (cutdeck/driver_commands.py `Premiere`)."""
    import asyncio
    expected = None
    if focus == "timeline":
        if sequence is not None:
            await premiere("open_sequence", {"sequence": sequence})
        expected = (await premiere("read_sequence"))["name"]
    if expected is not None:
        # Window > Timelines > <name> focuses exactly that timeline, no key press (live 2026-11-21).
        from cutdeck import menu
        await asyncio.to_thread(menu.invoke, f"Window > Timelines > {expected}", True)
        await asyncio.sleep(0.4)
        focused = {"focused": "timeline", "via": f"Window > Timelines > {expected}"}
    else:
        focused = await asyncio.to_thread(focus_panel, focus) if focus else None
    if expected is not None:
        now = (await premiere("read_sequence"))["name"]
        if now != expected:
            await premiere("open_sequence", {"sequence": expected})
            raise RuntimeError(f"Focusing the timeline switched to '{now}'; '{expected}' was reopened and nothing was run. Try again.")
    result = await asyncio.to_thread(action)
    return {**result, "sequence": expected, "focus": focused}


async def run_command(premiere, command: str, focus: str | None = "timeline", sequence: str | None = None) -> dict:
    """Press `command`'s shortcut on the right sequence (see run_focused)."""
    pick(load(), command)  # refuse a blocked or unbound command before touching anything
    return await run_focused(premiere, focus, sequence, lambda: press_command(command))
