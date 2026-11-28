"""Win32 keyboard input and bringing Premiere to the front: the pieces the key route (keys.py)
and the menu route (menu.py) share, kept below both so neither imports the other."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import time


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


_EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2E}


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
