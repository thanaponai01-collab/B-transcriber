"""Drive Premiere's own UI as a person does, for what no API reaches: the Clip Speed/Duration,
Nest and Paste Attributes dialogs, and typing into a text layer in the Program Monitor. The user approved driving
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
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path

import numpy as np
from PIL import Image, ImageGrab

from cutdeck import keys, menu, ocr, screenshot

SPEED_TITLE, NEST_TITLE, PASTE_TITLE = "Clip speed / duration", "Nested Sequence Name", "Paste Attributes"
SPEED_SIZE = (488, 437)  # the dialog the offsets below were measured on (96 DPI)
REVERSE_BOX, RIPPLE_BOX = (313, 91), (277, 351)  # checkbox centres inside the dialog window
PASTE_SIZE = (402, 811)  # Paste Attributes at 96 DPI; its boxes are drawn by Premiere, read from pixels
PASTE_BOXES = {"Motion": (44, 125), "Opacity": (44, 173), "Effects": (44, 249)}  # box centres in the dialog
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
    return screenshot.window_pixels()


def window_when(ready: Callable[[Image.Image, Image.Image], bool], timeout_s: float = 3.0) -> Image.Image:
    """Grab the window until `ready(previous grab, this grab)` holds and return that grab. After
    `timeout_s` it returns the last grab anyway: the check that reads it says what is wrong."""
    previous, end = window_image(), time.monotonic() + timeout_s
    while True:
        current = window_image()
        if ready(previous, current) or time.monotonic() > end:
            return current
        previous = current


def _moved(a: Image.Image, b: Image.Image) -> int:
    """Pixels whose grey level differs by more than 24 between two window grabs."""
    return int(_changed(a, b, 24).sum())


def _steady(a: Image.Image, b: Image.Image) -> bool:
    return _moved(a, b) <= 50


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


# --- Paste Attributes ----------------------------------------------------------------------------

def paste_dialog() -> None:
    """Open Edit > Paste Attributes... on the selected clips and press OK, after checking from
    pixels that Motion, Opacity and Effects are ticked (Premiere remembers the last choice)."""
    hwnd = open_dialog("Edit > Paste Attributes...", PASTE_TITLE)
    try:
        left, top, right, bottom = _rect(hwnd)
        if (right - left, bottom - top) != PASTE_SIZE or _user32().GetDpiForWindow(hwnd) != 96:
            raise RuntimeError(f"the Paste Attributes dialog is {right - left}x{bottom - top} at "
                               f"{_user32().GetDpiForWindow(hwnd)} DPI, not the measured {PASTE_SIZE} at 96")
        image = grab(hwnd)
        off = [name for name, box in PASTE_BOXES.items() if not ticked(image, *box)]
        if off:
            raise RuntimeError(f"Paste Attributes has {', '.join(off)} unticked; tick them once in the "
                               "dialog by hand (Premiere remembers) and run again. Nothing was pasted")
        _confirm(hwnd, PASTE_TITLE)
    except Exception:
        close_dialog(hwnd, PASTE_TITLE)
        raise


def _chain(clip: dict) -> list:
    return [(e["match_name"], [(p["index"], p["value"]) for p in e.get("params", [])]) for e in clip.get("effects", [])]


async def paste_attributes(premiere, args: dict) -> dict:
    """Copy `source`, select `clips`, Paste Attributes, then read every clip back: each one's
    effect chain and values must equal the source's."""
    sequence, source, clips = args.get("sequence"), args["source"], args["clips"]
    await premiere("select_clips", {"sequence": sequence, "clips": [source]})
    await keys.run_focused(premiere, "timeline", sequence, lambda: menu.invoke("Edit > Copy", True))
    await asyncio.sleep(0.5)
    await premiere("select_clips", {"sequence": sequence, "clips": clips})
    result = await keys.run_focused(premiere, "timeline", sequence, lambda: paste_dialog() or {})
    tracks = sorted({c.split("@")[0] for c in [source, *clips]})
    after = await premiere("read_timeline", {"sequence": result["sequence"], "tracks": tracks, "effects": "params"})
    by_id = {c["id"]: c for t in after.get("tracks", []) for c in t.get("clips", [])}
    if source not in by_id:
        raise RuntimeError(f"{source} is not on the timeline after the paste; read it back")
    want = _chain(by_id[source])
    differ = [c for c in clips if c not in by_id or _chain(by_id[c]) != want]
    return {"sequence": result["sequence"], "source": source, "effects": [name for name, _ in want],
            "matching": len(clips) - len(differ), "differ": differ,
            "note": "Each clip's effects and values were read back against the source. One Edit > Undo reverts the paste."}


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
    boxes = [(b[0].start + 4, b[1].start + 4, b[0].stop - 4, b[1].stop - 4) for b in ndimage.find_objects(labels)]  # undo dilation
    # A word gap wider than the dilation splits one line of text into blobs ("RUS ชนกำแพง", live
    # 2026-11-22): also try each group of blobs whose rows overlap, as one box.
    groups = [[b] for b in boxes]
    for b in boxes:
        hit = [g for g in groups if b not in g and any(b[0] < o[2] and o[0] < b[2] for o in g)]
        for g in hit:
            g.append(b)
    unions = {(min(b[0] for b in g), min(b[1] for b in g), max(b[2] for b in g), max(b[3] for b in g)) for g in groups if len(g) > 1}
    for y0, x0, y1, x1 in boxes + sorted(unions):
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
    x, y, r = point[0], point[1], 120
    near = (slice(max(0, y - r), y + r), slice(max(0, x - r), x + r))
    new_red = lambda image: _red(image)[near] & ~_red(before)[near]  # noqa: E731
    double_click(left + point[0], top + point[1])
    box = new_red(window_when(lambda _, now: int(new_red(now).sum()) >= 20, 2.0))
    outline = int(box.sum())
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
    # Most of the box gone, not all: the new text's selection box moves, and footage that the old one
    # covered can be red (a red couch behind Thai text, live 2026-11-23).
    on_box = lambda image: int((_red(image)[near] & box).sum())  # noqa: E731
    still = on_box(window_when(lambda _, now: on_box(now) * 2 < outline, 1.5))
    return {"edit_outline_px": outline, "left_editing": still * 2 < outline}


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
    frame_on = await _frame(premiere, seq, at)
    win_on = await asyncio.to_thread(window_when, _steady)
    await premiere("edit_clips", {"sequence": seq, "edits": [{"clip": clip_id, "op": "disable"}]})
    try:
        frame_off = await _frame(premiere, seq, at)
        win_off = await asyncio.to_thread(window_when, lambda a, b: _steady(a, b) and _moved(win_on, b) > 50)
    finally:
        await premiere("edit_clips", {"sequence": seq, "edits": [{"clip": clip_id, "op": "enable"}]})
    await asyncio.to_thread(window_when, lambda _, now: _moved(win_on, now) <= 50)
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


# --- text style by the Properties panel's Linked style ---------------------------------------------
# Live 2026-11-27 (PREMIERE_FACTS "Linked style"): clicking a "Text (...)" row in Effect Controls
# picks that layer; the Properties panel's Linked style dropdown then applies a style item to that
# layer only, and setting it back to None unlinks it, keeping the look. The dropdown opens a popup
# window of its own (class "DroverLord - Window Class", title "OS_PopupWindow"), which PrintWindow of the main
# window does not show; it is read through its own handle. All text is found by OCR (cutdeck/ocr.py).

SELECTED_ROW_GREY = 40  # Effect Controls row band: picked ~47, others ~29


def _words(lines: list[dict]):
    for line in lines:
        yield from ((line, w) for w in line["words"])


def effect_text_rows(lines: list[dict], layers: int) -> list[tuple[int, int]]:
    """The centres of the "Text" words of the Effect Controls' text layer rows, top first (chain
    order): the "Text" words between its "Graphics" and "Video" headers, just right of them (not the
    Properties panel's "Mask with Text" beside them), at one x."""
    graphics = [line for line in lines if line["text"] == "Graphics"]
    video = [line for line in lines if line["text"] == "Video"]
    pairs = [(g, v) for g in graphics for v in video if abs(g["box"][0] - v["box"][0]) <= 10 and v["box"][1] > g["box"][3]]
    found = []
    for g, v in pairs:
        words = [w["box"] for line, w in _words(lines) if w["text"] == "Text"
                 and g["box"][3] < w["box"][1] < v["box"][1] and 0 < w["box"][0] - g["box"][0] < 120]
        if words and all(abs(b[0] - words[0][0]) <= 6 for b in words):
            found = sorted((((b[0] + b[2]) // 2, (b[1] + b[3]) // 2) for b in words), key=lambda p: p[1])
            break
    if len(found) != layers:
        raise RuntimeError(f"Effect Controls shows {len(found)} text layer rows, not the clip's {layers}: show "
                           "Effect Controls with every text layer row in view and folded; nothing was clicked")
    return found


def panel_edges(image: Image.Image, x0: int, x1: int) -> list[int]:
    """The rows where a panel ends between x0 and x1: Premiere draws the gap between panels black
    (0), the panels 29 and a dropdown box 14 (live 2026-11-27)."""
    grey = np.asarray(image.convert("L"))[:, x0:x1]
    return [int(y) for y in np.nonzero(grey.max(axis=1) < 6)[0]]


def dropdown_under(lines: list[dict], heading: str, edges: list[int]) -> tuple[int, int] | None:
    """The centre of the line under `heading` (a dropdown's current value) if no panel edge lies
    between them, else None: with the heading at a panel's bottom, the line under it is another
    panel's (live 2026-11-27: the Libraries tab)."""
    top = next((line for line in lines if line["text"].endswith(heading)), None)
    if top is None:
        return None
    x0, _, _, y1 = top["box"]
    below = [line for line in lines if 0 < line["box"][1] - y1 < 60 and line["box"][0] >= x0]
    if not below:
        return None
    b = min(below, key=lambda line: line["box"][1])["box"]
    if any(y1 < y < b[3] for y in edges):
        return None
    return (b[0] + b[2]) // 2, (b[1] + b[3]) // 2


def _dropdown(image: Image.Image, lines: list[dict], heading: str = "Linked style") -> tuple[int, int] | None:
    top = next((line for line in lines if line["text"].endswith(heading)), None)
    return top and dropdown_under(lines, heading, panel_edges(image, top["box"][0], top["box"][0] + 300))


def _plain(s: str) -> str:
    return " ".join("".join(c for c in s.lower() if c.isalnum() or c == " ").split())


def popup_row(lines: list[dict], name: str, least: float = 85) -> tuple[int, int]:
    """The centre of the popup row that reads `name` (an icon before it reads as junk like "n:")."""
    from rapidfuzz import fuzz
    scored = []
    for line in lines:
        texts = [line["text"], " ".join(w["text"] for w in line["words"][1:])]
        score = max(fuzz.ratio(_plain(name), _plain(t)) for t in texts)
        b = line["box"]
        scored.append((score, ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)))
    good = [s for s in scored if s[0] >= least]
    if len(good) != 1:
        raise RuntimeError(f'the Linked style list has no row reading "{name}"' if not good
                           else f'the Linked style list has {len(good)} rows like "{name}"')
    return good[0][1]


def wheel(x: int, y: int, clicks: int) -> None:
    """Turn the mouse wheel at (x, y) screen pixels; a negative `clicks` scrolls down. The pointer
    moves there first: a wheel sent with the move did not scroll Premiere's panel (live 2026-11-27)."""
    _send([_mouse(x, y, 0)])
    time.sleep(0.3)
    event = _mouse(x, y, 0x0800)  # MOUSEEVENTF_WHEEL
    event.mi.mouseData = (120 * clicks) & 0xFFFFFFFF
    _send([event])
    time.sleep(0.3)


def _front(hwnd: int) -> None:
    """Premiere's own window must be in front (a hover tooltip of Premiere's counts)."""
    front = _user32().GetForegroundWindow()
    if not front or _pid(front) != _pid(hwnd):
        raise RuntimeError("Premiere is no longer in front; nothing more was clicked")


def _popup(hwnd: int, timeout_s: float = 2.0) -> int:
    """The dropdown popup that a click opened: Premiere's own foreground window other than its main one."""
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        front = _user32().GetForegroundWindow()
        if front and front != hwnd and _pid(front) == _pid(hwnd) and keys.window_title(front) == "OS_PopupWindow":
            time.sleep(0.3)
            return front
        time.sleep(0.1)
    raise RuntimeError("the Linked style dropdown did not open")


def _linked_style(hwnd: int) -> tuple[tuple[int, int], list[dict]]:
    """The Linked style dropdown in window pixels, scrolling the Properties panel down to it. The
    panel goes back to its top when a layer is picked (live 2026-11-27)."""
    margin = None
    for _ in range(12):
        image = window_when(_steady, 2.0)  # the panel redraws after a layer is picked
        lines = ocr.read(image)
        at = _dropdown(image, lines)
        if at:
            return at, lines
        if margin is None:
            # The wheel turns on the panel's left margin, at a section heading's chevron: over a
            # slider or number it would change the value.
            heading = next((line for line in lines if line["text"].endswith(("Linked style", "Align and Transform", "Appearance"))), None)
            if heading is None:
                time.sleep(0.5)
                continue
            margin = (heading["box"][0] + 2, (heading["box"][1] + heading["box"][3]) // 2)
        left, top, _, _ = _rect(hwnd)
        _front(hwnd)
        wheel(left + margin[0], top + margin[1], -10)
    raise RuntimeError("the Properties panel shows no Linked style: open Window > Properties")


def _choose(hwnd: int, at: tuple[int, int], name: str) -> None:
    """Open the Linked style dropdown at `at` (window pixels) and pick the row reading `name`."""
    left, top, _, _ = _rect(hwnd)
    _front(hwnd)
    click(left + at[0], top + at[1])
    popup = _popup(hwnd)
    try:
        row = popup_row(ocr.read(screenshot.window_pixels(popup)), name)
    except Exception:
        if _user32().GetForegroundWindow() == popup:
            press(VK_ESCAPE)
        raise
    if _user32().GetForegroundWindow() != popup:
        raise RuntimeError("the Linked style list closed before its row was clicked")
    pleft, ptop, _, _ = _rect(popup)
    click(pleft + row[0], ptop + row[1])
    time.sleep(0.8)


def _reads(hwnd: int, name: str) -> bool:
    from rapidfuzz import fuzz
    image = window_image()
    lines = ocr.read(image)
    at = _dropdown(image, lines)
    shown = next((line for line in lines if at and line["box"][0] <= at[0] <= line["box"][2]
                  and line["box"][1] <= at[1] <= line["box"][3]), None)
    return bool(shown) and max(fuzz.ratio(_plain(name), _plain(t)) for t in
                               (shown["text"], " ".join(w["text"] for w in shown["words"][1:]))) >= 85


def link_style(layer: int, layers: int, name: str) -> dict:
    """Pick text layer `layer` (0-based, chain order) in Effect Controls and set its Linked style to
    the style item `name` (blocking). The clip must be the selected one."""
    hwnd = screenshot.premiere_window()
    if not keys._bring_to_front(hwnd):
        raise RuntimeError("Premiere could not be brought to the front; nothing was clicked")
    time.sleep(0.2)
    if _in_menu_mode(hwnd):
        press(VK_ESCAPE)
        time.sleep(0.2)
    left, top, _, _ = _rect(hwnd)
    rows = effect_text_rows(ocr.read(window_image()), layers)
    x, y = rows[layer]
    _front(hwnd)
    click(left + x, top + y)
    grey = np.asarray(window_image().convert("L")).astype(int)
    band = lambda p: float(grey[p[1] - 6:p[1] + 6, p[0] + 90:p[0] + 290].mean())  # noqa: E731
    if band(rows[layer]) < SELECTED_ROW_GREY or any(band(p) >= SELECTED_ROW_GREY for k, p in enumerate(rows) if k != layer):
        raise RuntimeError(f"text layer {layer}'s Effect Controls row did not become the picked one; nothing more was clicked")
    at, _ = _linked_style(hwnd)
    _choose(hwnd, at, name)
    if not _reads(hwnd, name):
        raise RuntimeError(f'Linked style does not read "{name}" after picking it')
    return {"row": rows[layer]}


def unlink_style(name: str) -> None:
    """Set the picked layer's Linked style back to None (blocking); the look stays."""
    hwnd = screenshot.premiere_window()
    if not keys._bring_to_front(hwnd):
        raise RuntimeError("Premiere could not be brought to the front; nothing was clicked")
    time.sleep(0.2)
    at, _ = _linked_style(hwnd)
    _choose(hwnd, at, "None")
    if not _reads(hwnd, "None"):
        raise RuntimeError(f'Linked style still reads "{name}"; the layer is linked to it')


def _decoded(blob: bytes):
    from cutdeck import text_document
    try:
        return text_document.decode(blob)
    except text_document.UnmappedField:
        return blob


async def restyle_text(premiere, args: dict) -> dict:
    """Restyle one text layer of a Graphic on the timeline as Premiere does: through a text style.
    The saved project gives the layer's Source Text; the asked changes are written as a style
    (cutdeck/text_style.py), imported, linked to the layer and unlinked again (the look stays), and
    the style's bin removed. The saved project is then read back: the layer must hold exactly the
    asked look, and every other layer what it held before."""
    import tempfile
    import uuid
    from cutdeck import text_style
    sequence, clip_id, layer, changes = args.get("sequence"), args["clip"], args["layer"], args["styles"]
    seq = (await premiere("open_sequence", {"sequence": sequence}))["name"] if sequence else (await premiere("read_sequence"))["name"]
    track = clip_id.split("@")[0]
    found = [c for t in (await premiere("read_timeline", {"sequence": seq, "tracks": [track], "effects": "names"}))["tracks"]
             for c in t.get("clips", []) if c["id"] == clip_id]
    if not found:
        raise ValueError(f"No clip {clip_id} in {seq} (see premiere_read_timeline)")
    layers = sum(1 for e in found[0].get("effects", []) if e.get("match_name") == "AE.ADBE Text")
    if layers == 0:
        raise ValueError(f"{clip_id} has no Premiere text layer (an After Effects template or not a Graphic)")
    if layer >= layers:
        raise ValueError(f"{clip_id} has {layers} text layers (0 to {layers - 1}); layer {layer} is not one")
    items = (await premiere("list_project", {"depth": 1})).get("items", [])
    stale = [it["name"] for it in items if it.get("name", "").startswith("CutDeck restyle ")]
    if stale:
        raise ValueError(f"the project still holds {stale} from an earlier restyle: set any layer linked to it back to "
                         "Linked style None, remove it with premiere_remove_style_bin, then run again")
    path = (await premiere("save_project", {}))["path"].removeprefix("\\?\\")
    before = [text_style.layer_blob(path, seq, clip_id, k) for k in range(layers)]
    want = text_style.restyled_layer(before[layer], changes)
    name = f"CutDeck restyle {uuid.uuid4().hex[:6]}"
    style = text_style.write_style(want, name, Path(tempfile.gettempdir()) / f"{name}.prtextstyle")
    await premiere("import_files", {"paths": [str(style)]})
    try:
        await premiere("select_clips", {"sequence": seq, "clips": [clip_id]})
    except Exception:
        await premiere("remove_style_bin", {"name": style.name})
        raise
    try:
        picked = await asyncio.to_thread(link_style, layer, layers, name)
        await asyncio.to_thread(unlink_style, name)
    except Exception as exc:
        raise RuntimeError(f"{exc}. The style {name!r} is still in the project (bin {style.name!r}): if text layer {layer}'s "
                           "Linked style shows it, set that to None (or Edit > Undo), then premiere_remove_style_bin") from exc
    removed = (await premiere("remove_style_bin", {"name": style.name}))["removed"]
    await premiere("save_project", {})
    after = [text_style.layer_blob(path, seq, clip_id, k) for k in range(layers)]
    got = _decoded(after[layer])
    wrong = text_style.mismatches(got, want, changes) if isinstance(got, dict) else ["the whole layer (no longer decodes)"]
    if wrong:
        raise RuntimeError(f"text layer {layer} does not hold the asked look after the restyle (differs in {wrong}); "
                           "four Edit > Undo steps revert it")
    moved = [k for k in range(layers) if k != layer and text_style._canonical(_decoded(after[k])) != text_style._canonical(_decoded(before[k]))]
    if moved:
        raise RuntimeError(f"text layers {moved} changed too; four Edit > Undo steps revert the restyle")
    return {"sequence": seq, "clip": clip_id, "layer": layer, "layers": layers, "styles": changes,
            "style_removed": removed, "effect_controls_row": picked["row"],
            "note": "Read back from the saved project: the layer holds exactly the asked look, its text and the other "
                    "layers unchanged. The project was saved before and after. Undo takes four Edit > Undo steps "
                    "(style removal, unlink, link, import)."}
