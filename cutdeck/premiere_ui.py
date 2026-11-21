"""Drive Premiere's own UI as a person does, for what no API reaches: the Clip Speed/Duration and
Nest dialogs, and typing into a text layer in the Program Monitor. The user approved driving
dialogs and typing (2026-11-21). Live-proven on Premiere 27.0.0 (PREMIERE_FACTS "Premiere UI
route"):

- Both dialogs are real Win32 dialogs (class #32770, titles "Clip speed / duration" and "Nested
  Sequence Name") whose first field is a real Edit control, focused with its text selected.
  Everything else in them is drawn by Premiere, so the checkboxes are reached with Tab and read
  from pixels: the focus ring is RGB (64, 150, 243), and a ticked box is bright inside.
- With the Selection tool picked (clicked in the Tools panel), double-clicking a text layer in the
  Program Monitor enters text editing (red outline); Ctrl+A and typed text replace the layer's
  text, and clicking the Selection tool again leaves editing (Escape does not). One Edit > Undo
  reverts it.

Every key batch is gated: Premiere's dialog (or window) must be in front, or nothing is pressed.
Any failure closes a dialog this module opened with Escape. `premiere(command, args)` runs a
panel command (cutdeck/driver_commands.py `Premiere`).
"""
from __future__ import annotations

import asyncio
import ctypes
import time
from ctypes import wintypes
from pathlib import Path

import numpy as np
from PIL import Image, ImageGrab

from cutdeck import keys, menu, screenshot

SPEED_TITLE, NEST_TITLE = "Clip speed / duration", "Nested Sequence Name"
SPEED_SIZE = (488, 437)  # the dialog the offsets below were measured on (96 DPI)
REVERSE_BOX, RIPPLE_BOX = (313, 91), (277, 351)  # checkbox centres inside the dialog window
RING = (64, 150, 243)
TICKED_MEAN = 110  # mean grey inside a 9x9 box: ticked ~164, unticked ~50
VK_TAB, VK_SPACE, VK_RETURN, VK_ESCAPE, VK_CONTROL, VK_A = 0x09, 0x20, 0x0D, 0x1B, 0x11, 0x41


def _user32():
    return ctypes.windll.user32


# --- input ---------------------------------------------------------------------------------------

class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", keys._KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(events: list[_INPUT]) -> None:
    array = (_INPUT * len(events))(*events)
    if _user32().SendInput(len(events), array, ctypes.sizeof(_INPUT)) != len(events):
        raise RuntimeError("SendInput was blocked")


def type_text(text: str) -> None:
    """Type `text` as Unicode characters (any language, no keyboard layout involved)."""
    events = []
    for ch in text:
        for up in (0, 0x0002):
            event = _INPUT(type=1)
            event.ki = keys._KEYBDINPUT(0, ord(ch), 0x0004 | up, 0, 0)  # KEYEVENTF_UNICODE
            events.append(event)
    _send(events)


def press(*vks: int) -> None:
    keys._send(list(vks))


def _mouse(x: int, y: int, flags: int) -> _INPUT:
    user32 = _user32()
    vx, vy, vw, vh = (user32.GetSystemMetrics(i) for i in (76, 77, 78, 79))  # virtual desktop
    event = _INPUT(type=0)
    event.mi = _MOUSEINPUT(int((x - vx) * 65535 / (vw - 1)), int((y - vy) * 65535 / (vh - 1)), 0,
                           flags | 0x0001 | 0x8000 | 0x4000, 0, 0)  # move | absolute | virtual desk
    return event


def double_click(x: int, y: int) -> None:
    for dx in (-6, -3, 0):
        _send([_mouse(x + dx, y, 0)])
        time.sleep(0.04)
    for _ in range(2):
        _send([_mouse(x, y, 0x0002)])  # left down
        time.sleep(0.05)
        _send([_mouse(x, y, 0x0004)])  # left up
        time.sleep(0.06)


# --- windows and pixels --------------------------------------------------------------------------

def _rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    _user32().GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def _class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _user32().GetClassNameW(hwnd, buf, 256)
    return buf.value


def _pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    _user32().GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def dialog_in_front(title: str) -> int | None:
    """The foreground window if it is Premiere's #32770 dialog called `title`."""
    hwnd = _user32().GetForegroundWindow()
    if (hwnd and _class(hwnd) == "#32770" and keys.window_title(hwnd) == title
            and _pid(hwnd) == _pid(screenshot.premiere_window())):
        return hwnd
    return None


def require_front(hwnd: int, title: str) -> None:
    if dialog_in_front(title) != hwnd:
        raise RuntimeError(f'"{title}" is no longer in front; nothing more was pressed')


def grab(hwnd: int) -> Image.Image:
    """What the screen shows of `hwnd` now (PrintWindow can return a stale picture of a dialog)."""
    return ImageGrab.grab(bbox=_rect(hwnd), all_screens=True).convert("RGB")


def window_image() -> Image.Image:
    """Premiere's main window as drawn (PrintWindow: works even when something covers it)."""
    return Image.open(screenshot.capture()["path"]).convert("RGB")


def ring_at(image: Image.Image, x: int, y: int, r: int = 13) -> int:
    a = np.asarray(image).astype(int)[y - r:y + r, x - r:x + r]
    return int(((abs(a[..., 0] - RING[0]) < 10) & (abs(a[..., 1] - RING[1]) < 10) & (abs(a[..., 2] - RING[2]) < 10)).sum())


def ticked(image: Image.Image, x: int, y: int) -> bool:
    return float(np.asarray(image.convert("L")).astype(int)[y - 4:y + 5, x - 4:x + 5].mean()) > TICKED_MEAN


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD), ("hwndActive", wintypes.HWND),
                ("hwndFocus", wintypes.HWND), ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND), ("rcCaret", wintypes.RECT)]


def _thread_info(hwnd: int) -> _GUITHREADINFO | None:
    info = _GUITHREADINFO(cbSize=ctypes.sizeof(_GUITHREADINFO))
    thread = _user32().GetWindowThreadProcessId(hwnd, None)
    return info if _user32().GetGUIThreadInfo(thread, ctypes.byref(info)) else None


def _in_menu_mode(hwnd: int) -> bool:
    info = _thread_info(hwnd)
    return bool(info and info.flags & (0x0004 | 0x0010))  # GUI_INMENUMODE | GUI_POPUPMENUMODE


def _focused_class(hwnd: int) -> str:
    info = _thread_info(hwnd)
    return _class(info.hwndFocus) if info and info.hwndFocus else ""


def open_dialog(path: str, title: str, timeout_s: float = 5.0) -> int:
    """Post a dialog menu item (menu.find refuses "..." items for menu_command, so the id is
    looked up here) and wait for its dialog to come to the front."""
    item = next((it for it in menu.items() if it["path"] == path), None)
    if item is None:
        raise RuntimeError(f"Premiere has no menu item {path}")
    if not _user32().PostMessageW(screenshot.premiere_window(), menu.WM_COMMAND, item["id"], 0):
        raise RuntimeError("PostMessage to Premiere failed")
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        hwnd = dialog_in_front(title)
        if hwnd:
            time.sleep(0.3)
            return hwnd
        time.sleep(0.1)
    raise RuntimeError(f'"{title}" did not open (is a clip selected and the item enabled?)')


def close_dialog(hwnd: int, title: str) -> None:
    """Escape, only if the dialog is still in front."""
    if dialog_in_front(title) == hwnd:
        press(VK_ESCAPE)
        time.sleep(0.4)


def _confirm(hwnd: int, title: str) -> None:
    require_front(hwnd, title)
    press(VK_RETURN)
    end = time.monotonic() + 5
    while time.monotonic() < end:
        if not _user32().IsWindow(hwnd) or not _user32().IsWindowVisible(hwnd):
            return
        time.sleep(0.1)
    raise RuntimeError(f'"{title}" did not close after Enter')


def _replace_field(hwnd: int, title: str, text: str) -> None:
    require_front(hwnd, title)
    if _focused_class(hwnd) != "Edit":
        raise RuntimeError(f'"{title}" opened without its text field focused; nothing was typed')
    press(VK_CONTROL, VK_A)
    type_text(text)
    time.sleep(0.2)


# --- Speed / Duration ----------------------------------------------------------------------------

def _set_checkbox(hwnd: int, box: tuple[int, int], want: bool, name: str) -> None:
    for _ in range(16):
        require_front(hwnd, SPEED_TITLE)
        press(VK_TAB)
        time.sleep(0.3)
        image = grab(hwnd)
        if ring_at(image, *box) > 30:
            if ticked(image, *box) != want:
                press(VK_SPACE)
                time.sleep(0.3)
                if ticked(grab(hwnd), *box) != want:
                    raise RuntimeError(f"{name} did not change when pressed")
            return
    raise RuntimeError(f"Tab never reached {name}")


def speed_dialog(speed: float, reverse: bool, ripple: bool) -> None:
    """Fill Clip > Speed/Duration... for the selected clips and press OK (blocking)."""
    hwnd = open_dialog("Clip > Speed/Duration...", SPEED_TITLE)
    try:
        left, top, right, bottom = _rect(hwnd)
        if (right - left, bottom - top) != SPEED_SIZE or _user32().GetDpiForWindow(hwnd) != 96:
            raise RuntimeError(f"the Speed/Duration dialog is {right - left}x{bottom - top} at "
                               f"{_user32().GetDpiForWindow(hwnd)} DPI, not the measured {SPEED_SIZE} at 96")
        _replace_field(hwnd, SPEED_TITLE, f"{speed:g}")
        _set_checkbox(hwnd, REVERSE_BOX, reverse, "Reverse speed")  # Tab order: Reverse comes before Ripple
        _set_checkbox(hwnd, RIPPLE_BOX, ripple, "Ripple edit")
        _confirm(hwnd, SPEED_TITLE)
    except Exception:
        close_dialog(hwnd, SPEED_TITLE)
        raise


async def set_speed(premiere, args: dict) -> dict:
    sequence = args.get("sequence")
    await premiere("select_clips", {"sequence": sequence, "clips": args["clips"]})
    result = await keys.run_focused(premiere, "timeline", sequence,
                                    lambda: speed_dialog(args["speed"], args["reverse"], args["ripple"]) or {})
    after = await premiere("read_timeline", {"sequence": result["sequence"]})
    clips = [c for t in after.get("tracks", []) for c in t.get("clips", []) if c.get("selected")]
    return {"sequence": result["sequence"], "speed_percent": args["speed"], "reverse": args["reverse"],
            "ripple": args["ripple"], "selected_after": clips,
            "note": "Clip ids change when a clip's length changes; read_timeline has the new ones. One Edit > Undo reverts it."}


# --- Nest ----------------------------------------------------------------------------------------

def nest_dialog(name: str) -> None:
    hwnd = open_dialog("Clip > Nest...", NEST_TITLE)
    try:
        _replace_field(hwnd, NEST_TITLE, name)
        _confirm(hwnd, NEST_TITLE)
    except Exception:
        close_dialog(hwnd, NEST_TITLE)
        raise


async def nest_clips(premiere, args: dict) -> dict:
    sequence = args.get("sequence")
    await premiere("select_clips", {"sequence": sequence, "clips": args["clips"]})
    result = await keys.run_focused(premiere, "timeline", sequence, lambda: nest_dialog(args["name"]) or {})
    after = await premiere("read_timeline", {"sequence": result["sequence"]})
    nested = [c for t in after.get("tracks", []) for c in t.get("clips", []) if c.get("name") == args["name"]]
    if not nested:
        raise RuntimeError(f'Nest ran but no clip named "{args["name"]}" is on the timeline; read it back')
    return {"sequence": result["sequence"], "name": args["name"], "nested": nested,
            "note": "One Edit > Undo removes the nest and its new sequence."}


# --- text in the Program Monitor -----------------------------------------------------------------

def _changed(a: Image.Image, b: Image.Image, threshold: int) -> np.ndarray:
    return np.abs(np.asarray(a.convert("L")).astype(int) - np.asarray(b.convert("L")).astype(int)) > threshold


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(mask)
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1) if len(xs) else None


def locate_in_window(frame_on: Image.Image, frame_off: Image.Image, win_on: Image.Image,
                     win_off: Image.Image) -> dict:
    """Where the Program Monitor draws the text: the frame-space text box (frames with the clip on
    and off) matched to one changed blob of the window, accepted only if the window there shows
    the frame itself at that scale. No panel layout is assumed."""
    from scipy import ndimage
    text = _bbox(_changed(frame_on, frame_off, 16))
    if text is None:
        raise RuntimeError("The clip draws nothing at this time; pick a time where its text shows")
    tw, th = text[2] - text[0], text[3] - text[1]
    mask = ndimage.binary_dilation(_changed(win_on, win_off, 24), iterations=4)
    labels, count = ndimage.label(mask)
    best = None
    gray_on = np.asarray(win_on.convert("L")).astype(int)
    for blob in ndimage.find_objects(labels):
        y0, x0, y1, x1 = blob[0].start + 4, blob[1].start + 4, blob[0].stop - 4, blob[1].stop - 4  # undo dilation
        if x1 <= x0 or y1 <= y0:
            continue
        sx, sy = (x1 - x0) / tw, (y1 - y0) / th
        scale = (sx + sy) / 2
        if scale <= 0 or abs(sx - sy) / scale > 0.4:
            continue
        ox, oy = x0 - scale * text[0], y0 - scale * text[1]
        w, h = round(scale * frame_on.width), round(scale * frame_on.height)
        X, Y = round(ox), round(oy)
        if w < 40 or h < 40 or X < 0 or Y < 0 or X + w > win_on.width or Y + h > win_on.height:
            continue
        shown = gray_on[Y:Y + h, X:X + w]
        expected = np.asarray(frame_on.convert("L").resize((w, h))).astype(int)
        score = float(np.abs(shown - expected).mean())
        if score < 30 and (best is None or score < best["score"]):
            best = {"score": score, "scale": scale, "origin": (ox, oy)}
    if best is None:
        raise RuntimeError("Could not find the text in the Program Monitor: show the Program Monitor "
                           "with the sequence in view (Fit), and nothing covering it")
    cx, cy = (text[0] + text[2]) / 2, (text[1] + text[3]) / 2
    return {"text_box": text, "scale": best["scale"], "match": best["score"],
            "point": (round(best["origin"][0] + best["scale"] * cx), round(best["origin"][1] + best["scale"] * cy))}


def _red(image: Image.Image) -> np.ndarray:
    a = np.asarray(image).astype(int)
    return (a[..., 0] > 180) & (a[..., 1] < 90) & (a[..., 2] < 90)


def click(x: int, y: int) -> None:
    _send([_mouse(x, y, 0)])
    time.sleep(0.05)
    _send([_mouse(x, y, 0x0002)])
    time.sleep(0.06)
    _send([_mouse(x, y, 0x0004)])
    time.sleep(0.4)


def find_selection_tool(window: Image.Image) -> tuple[int, int]:
    """Centre of the Tools panel's Selection tool (the arrow), in window pixels, found by its
    glyph (ui_templates/selection_tool.png; scores 0.905 selected or not, nothing else above 0.85)."""
    from scipy.signal import fftconvolve
    template = Image.open(Path(__file__).with_name("ui_templates") / "selection_tool.png").convert("L")
    t = np.where(np.asarray(template) > 170, 1.0, -1.0)
    w = np.where(np.asarray(window.convert("L")) > 170, 1.0, -1.0)
    score = fftconvolve(w, t[::-1, ::-1], mode="valid") / t.size
    y, x = np.unravel_index(int(score.argmax()), score.shape)
    if score[y, x] < 0.85:
        raise RuntimeError("The Tools panel's Selection tool is not visible; open Window > Tools")
    return int(x + t.shape[1] // 2), int(y + t.shape[0] // 2)


def type_into_text(point: tuple[int, int], text: str) -> dict:
    """Double-click the text at `point` (window pixels) and replace it with `text` (blocking).
    The Selection tool is clicked first: its V shortcut can switch on Object Selection instead,
    and then a double-click selects the clip rather than its text (live 2026-11-21). Escape does
    not leave text editing; clicking the Selection tool again does."""
    hwnd = screenshot.premiere_window()
    if not keys._bring_to_front(hwnd):
        raise RuntimeError("Premiere could not be brought to the front; nothing was pressed")
    time.sleep(0.2)
    if _in_menu_mode(hwnd):  # _bring_to_front taps Alt, which can leave the menu bar active
        press(VK_ESCAPE)
        time.sleep(0.2)
    left, top, _, _ = _rect(hwnd)
    tool = find_selection_tool(window_image())
    click(left + tool[0], top + tool[1])
    before = window_image()
    double_click(left + point[0], top + point[1])
    time.sleep(0.8)
    after = window_image()
    x, y, r = point[0], point[1], 120
    near = (slice(max(0, y - r), y + r), slice(max(0, x - r), x + r))
    outline = int((_red(after)[near] & ~_red(before)[near]).sum())
    if outline < 20:
        click(left + tool[0], top + tool[1])
        raise RuntimeError("Double-clicking did not open the text for editing (no red text box); nothing was typed")
    if _user32().GetForegroundWindow() != hwnd:
        raise RuntimeError("Premiere lost the front while editing text; nothing was typed")
    press(VK_CONTROL, VK_A)
    time.sleep(0.2)
    type_text(text)
    time.sleep(0.4)
    click(left + tool[0], top + tool[1])  # leaves text editing
    time.sleep(0.5)
    still = int((_red(window_image())[near] & ~_red(before)[near]).sum())
    return {"edit_outline_px": outline, "left_editing": still < 20}


async def _frame(premiere, sequence: str, ticks: str) -> Image.Image:
    shot = await premiere("export_frame", {"sequence": sequence, "ticks": ticks})
    return Image.open(shot["path"]).convert("RGB")


async def edit_text(premiere, args: dict) -> dict:
    sequence, clip_id, text = args.get("sequence"), args["clip"], args["text"]
    seq = (await premiere("open_sequence", {"sequence": sequence}))["name"] if sequence else (await premiere("read_sequence"))["name"]
    track = clip_id.split("@")[0]
    found = [c for t in (await premiere("read_timeline", {"sequence": seq, "tracks": [track], "effects": "names"}))["tracks"]
             for c in t.get("clips", []) if c["id"] == clip_id]
    if not found:
        raise ValueError(f"No clip {clip_id} in {seq} (see premiere_read_timeline)")
    clip = found[0]
    if clip.get("disabled"):
        raise ValueError(f"{clip_id} is disabled; enable it first so its text shows")
    # The click lands on the centre of everything the clip draws, so only a one-text-layer Graphic
    # is safe; an After Effects template keeps its text in AE.ADBE Capsule, not editable here.
    layers = sum(1 for e in clip.get("effects", []) if e.get("match_name") == "AE.ADBE Text")
    if layers == 0:
        raise ValueError(f"{clip_id} has no Premiere text layer (an After Effects template or not a Graphic); "
                         "change its text with premiere_place_text instead")
    if layers > 1:
        raise ValueError(f"{clip_id} has {layers} text layers; edit_text handles a Graphic with one text layer")
    at = args.get("at_ticks") or str((int(clip["start_ticks"]) + int(clip["end_ticks"])) // 2)
    if not int(clip["start_ticks"]) <= int(at) < int(clip["end_ticks"]):
        raise ValueError(f"at_ticks {at} is outside {clip_id}")
    await premiere("set_playhead", {"sequence": seq, "ticks": at})
    await asyncio.sleep(0.8)
    frame_on, win_on = await _frame(premiere, seq, at), await asyncio.to_thread(window_image)
    await premiere("edit_clips", {"sequence": seq, "edits": [{"clip": clip_id, "op": "disable"}]})
    try:
        await asyncio.sleep(0.8)
        frame_off, win_off = await _frame(premiere, seq, at), await asyncio.to_thread(window_image)
    finally:
        await premiere("edit_clips", {"sequence": seq, "edits": [{"clip": clip_id, "op": "enable"}]})
    await asyncio.sleep(0.8)
    where = locate_in_window(frame_on, frame_off, win_on, win_off)
    typed = await asyncio.to_thread(type_into_text, where["point"], text)
    frame_after = await _frame(premiere, seq, at)
    changed = _changed(frame_on, frame_after, 16)
    x0, y0, x1, y1 = where["text_box"]
    pad = max(x1 - x0, y1 - y0)  # new text can be wider than the old
    inside = np.zeros_like(changed)
    inside[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad] = True
    if not changed[inside].any():
        raise RuntimeError("The frame did not change after typing; the text was not replaced (check premiere_export_frame)")
    return {"sequence": seq, "clip": clip_id, "text": text, "at_ticks": at, "monitor_scale": round(where["scale"], 4),
            "changed_px_near_text": int(changed[inside].sum()), "changed_px_elsewhere": int(changed[~inside].sum()),
            **typed, "note": "History: Disable, Enable, then the text edit. One Edit > Undo reverts the text."}
