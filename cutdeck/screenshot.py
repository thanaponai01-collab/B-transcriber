"""A picture of Premiere's main window, so an agent can see panels UXP cannot read.

Premiere's own UI is invisible to Windows UI Automation (docs/PREMIERE_FACTS.md, "Driving the
AI Assistant"), so the only way to see Effect Controls, the Program Monitor or the timeline as
drawn is pixels. Win32 only (user32/gdi32 through ctypes): PrintWindow with
PW_RENDERFULLCONTENT, which also draws GPU-composited content and windows behind others. A
minimised window has nothing to draw and is refused.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
import tempfile
import time

from PIL import Image

PROCESS_NAMES = ("adobe premiere pro.exe", "adobe premiere pro (beta).exe")
PW_RENDERFULLCONTENT = 2
KEEP = 20  # default-path screenshots kept in %TEMP%; older ones are deleted on each capture
_user32 = ctypes.WinDLL("user32", use_last_error=True) if hasattr(ctypes, "WinDLL") else None
_gdi32 = ctypes.WinDLL("gdi32") if hasattr(ctypes, "WinDLL") else None
_kernel32 = ctypes.WinDLL("kernel32") if hasattr(ctypes, "WinDLL") else None


def _process_name(pid: int) -> str:
    handle = _kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        ok = _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        return Path(buf.value).name.lower() if ok else ""
    finally:
        _kernel32.CloseHandle(handle)


def premiere_window() -> int:
    """The largest visible top-level window of a Premiere process (its main frame)."""
    found: list[tuple[int, int]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if _user32.IsWindowVisible(hwnd) and not _user32.GetWindow(hwnd, 4):  # GW_OWNER: top-level only
            pid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if _process_name(pid.value) in PROCESS_NAMES:
                rect = wintypes.RECT()
                _user32.GetWindowRect(hwnd, ctypes.byref(rect))
                found.append(((rect.right - rect.left) * (rect.bottom - rect.top), hwnd))
        return True

    _user32.EnumWindows(visit, 0)
    if not found:
        raise RuntimeError("Premiere is not running (no visible Premiere window)")
    return max(found)[1]


def capture(output: str | None = None) -> dict:
    """Save Premiere's main window as a PNG; returns its path and size."""
    image = window_pixels()
    path = Path(output) if output else Path(tempfile.gettempdir()) / f"cutdeck-premiere-{int(time.time() * 1000)}.png"
    image.save(path)
    if not output:
        for old in sorted(path.parent.glob("cutdeck-premiere-*.png"))[:-KEEP]:  # names carry the ms time
            old.unlink(missing_ok=True)
    return {"path": str(path), "width": image.width, "height": image.height}


def window_pixels() -> Image.Image:
    """Premiere's main window as an RGB image, kept in memory."""
    if _user32 is None:
        raise RuntimeError("Screenshots need Windows")
    hwnd = premiere_window()
    if _user32.IsIconic(hwnd):
        raise RuntimeError("Premiere is minimised; restore its window first")
    rect = wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    screen = _user32.GetDC(None)
    dc = _gdi32.CreateCompatibleDC(screen)
    bitmap = _gdi32.CreateCompatibleBitmap(screen, width, height)
    old = _gdi32.SelectObject(dc, bitmap)
    try:
        if not _user32.PrintWindow(hwnd, dc, PW_RENDERFULLCONTENT):
            raise RuntimeError("PrintWindow failed on Premiere's window")

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

        header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        pixels = ctypes.create_string_buffer(width * height * 4)
        if not _gdi32.GetDIBits(dc, bitmap, 0, height, pixels, ctypes.byref(header), 0):
            raise RuntimeError("GetDIBits failed")
    finally:
        _gdi32.SelectObject(dc, old)
        _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(dc)
        _user32.ReleaseDC(None, screen)
    return Image.frombuffer("RGB", (width, height), pixels.raw, "raw", "BGRX", 0, 1)
