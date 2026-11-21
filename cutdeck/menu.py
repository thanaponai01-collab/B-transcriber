"""Run any item of Premiere's menu bar (File, Edit, Clip, Sequence, Markers, ...) by its path.

Premiere's menu bar is a real Win32 menu (`GetMenu` on the main window: 9 menus, live 27.0.0,
2026-11-21). Posting WM_COMMAND with an item's ID runs it exactly as a click would, with no key
press: `Edit > Undo` / `Redo` worked this way when Ctrl+Z sent as keys did not, and
`Sequence > Add Edit to All Tracks` cut when its Ctrl+Alt+Z did nothing.

Timeline commands act on the FOCUSED panel, as with keys (Add Edit did nothing with the Project
panel focused), so `cutdeck.keys.run_focused` focuses and checks the sequence first. The enabled
flag read from the menu without opening it can be stale (Redo read disabled and then ran), so it
is reported as a hint only. Items ending in "..." open a dialog an agent cannot answer, and
quit/close/open/export/save-as items are never run.
"""
from __future__ import annotations

import ctypes
import re

from cutdeck import screenshot

WM_COMMAND, WM_INITMENUPOPUP = 0x0111, 0x0117
BLOCKED = re.compile(r"^file > (exit|close|open|new|export|save as|save a copy|revert|import)|^help >", re.I)


def _user32():
    return ctypes.windll.user32


def _clean(text: str) -> tuple[str, str]:
    label, _, keys = text.partition("\t")
    return label.replace("&&", "\0").replace("&", "").replace("\0", "&").strip(), keys.strip()


def items(window: int | None = None) -> list[dict]:
    """Every runnable menu item: path, shortcut text, command id, enabled hint."""
    u = _user32()
    hwnd = window or screenshot.premiere_window()
    buf = ctypes.create_unicode_buffer(512)
    out: list[dict] = []

    def walk(menu: int, path: list[str]) -> None:
        u.SendMessageW(hwnd, WM_INITMENUPOPUP, menu, 0)  # ask Premiere to refresh the states
        for i in range(u.GetMenuItemCount(menu)):
            u.GetMenuStringW(menu, i, buf, 512, 0x400)
            label, keys = _clean(buf.value)
            if not label:
                continue  # separator
            sub = u.GetSubMenu(menu, i)
            if sub:
                walk(sub, path + [label])
                continue
            item_id = u.GetMenuItemID(menu, i)
            out.append({"path": " > ".join(path + [label]), "keys": keys or None, "id": item_id,
                        "enabled_hint": not (u.GetMenuState(menu, i, 0x400) & 0x3)})

    bar = u.GetMenu(hwnd)
    if not bar:
        raise RuntimeError("Premiere's main window has no menu bar")
    for i in range(u.GetMenuItemCount(bar)):
        u.GetMenuStringW(bar, i, buf, 512, 0x400)
        walk(u.GetSubMenu(bar, i), [_clean(buf.value)[0]])
    return out


def runnable(item: dict) -> bool:
    return not BLOCKED.search(item["path"]) and not item["path"].endswith("...")


def list_items(query: str = "") -> list[dict]:
    q = query.lower()
    return [{**it, "runnable": runnable(it)} for it in items() if q in it["path"].lower()]


def find(path: str) -> dict:
    want = " > ".join(part.strip().lower() for part in path.split(">"))
    matches = [it for it in items() if it["path"].lower() == want]
    if not matches:
        raise ValueError(f'No menu item "{path}" (see premiere_list_menu)')
    item = matches[0]
    if BLOCKED.search(item["path"]):
        raise ValueError(f'{item["path"]} is never run for an agent (quit, close, open, import, export, save-as, help)')
    if item["path"].endswith("..."):
        raise ValueError(f'{item["path"]} opens a dialog; run its effect through a CutDeck tool instead')
    return item


def invoke(path: str, front: bool = False) -> dict:
    """Post the item's WM_COMMAND to Premiere (asynchronous, like a click). `front`: bring
    Premiere to the foreground first (panel focus only sticks in the active window)."""
    item = find(path)
    hwnd = screenshot.premiere_window()
    if front:
        from cutdeck import keys
        keys._bring_to_front(hwnd)
    if not _user32().PostMessageW(hwnd, WM_COMMAND, item["id"], 0):
        raise RuntimeError("PostMessage to Premiere failed")
    return {"menu": item["path"], "id": item["id"], "keys": item["keys"], "enabled_hint": item["enabled_hint"],
            "note": "A posted menu command is not proof: read the result back (premiere_read_timeline)."}
