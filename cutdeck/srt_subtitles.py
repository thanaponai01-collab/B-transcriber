"""Turn an .srt into styled, editable subtitle Graphics on a sequence (`premiere_srt_subtitles`).

Route, each step live-proven on Premiere 27.0.0 (2026-11-22, PREMIERE_FACTS "SRT to subtitle
Graphics"):

1. The SRT is snapped to whole frames and written beside the project (CutDeck/Subtitles), then
   imported (`import_files`). Premiere floors SRT milliseconds to frames, so each time is written
   at the first millisecond of its frame and lands exactly there.
2. Placement is UI only: UXP overwrite/insert of an SRT item commit and place nothing. Premiere
   selects and scrolls to an item it just imported, so its Project panel row is found from pixels
   (the caption label yellow on the selected-row grey) and dragged onto the sequence's timeline
   (found by its track-lock icons). That opens the "New caption track" dialog (Win32 #32770); its
   Style dropdown picks a saved Style (a project item made with Create Style), Start Point must be
   Source timecode, Enter places the captions on a new caption track.
3. Edit > Select All, then Graphics and Titles > Upgrade Caption to Graphic: only captions are
   upgraded (other selected clips are untouched); the Graphics keep the Style and land on the top
   video track, or a new one above it when that track is in use.
4. `build_sequence` (into) clones them onto the chosen track (`v_offset`) and lifts the originals,
   and sets the Motion Position and Scale. Every step is read back against the snapped cues.

`premiere(command, args)` runs a panel command (cutdeck/driver_commands.py `Premiere`).
"""
from __future__ import annotations

import asyncio
import math
import re
import time
import uuid
from pathlib import Path

import numpy as np
from PIL import Image

from cutdeck import keys, premiere_ui as ui, screenshot

TICKS_PER_MS = 254016000
CAPTION_TITLE = "New caption track"
CAPTION_SIZE = (256, 457)  # the dialog at 96 DPI, live 2026-11-22
STYLE_FIELD = (128, 227)  # centre of the Style dropdown in the dialog
SOURCE_TIMECODE_RADIO = (44, 311)  # Start Point: Source timecode
POPUP_FIRST_ROW, POPUP_ROW = 23, 41  # dropdown list: "None" row centre, then one row per Style
LABEL_YELLOW = (249, 229, 101)  # Project panel label colour of a caption item
SELECTED_ROW = 47  # grey of the selected Project panel row (others 29)
SRT_TIME = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})")


# --- the SRT ---------------------------------------------------------------------------------------

def parse_srt(text: str) -> list[dict]:
    """Cues in order: {start_ms, end_ms, text} (text lines joined with newlines)."""
    cues = []
    for block in re.split(r"\r?\n\s*\r?\n", text.strip()):
        lines = [line.rstrip() for line in block.splitlines()]
        at = next((i for i, line in enumerate(lines) if SRT_TIME.search(line)), None)
        if at is None:
            continue
        g = SRT_TIME.search(lines[at]).groups()
        start, end = (((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(f.ljust(3, "0"))
                      for h, m, s, f in (g[0:4], g[4:8]))
        cues.append({"start_ms": start, "end_ms": end, "text": "\n".join(lines[at + 1:]).strip()})
    if not cues:
        raise ValueError("no cues in the SRT")
    return cues


def to_frames(cues: list[dict], tpf: int) -> tuple[list[dict], list[dict]]:
    """Snap each cue to the nearest frames. Returns (kept, dropped): a cue shorter than a frame
    after snapping is dropped (Premiere drops it too, PREMIERE_FACTS "Sub-frame SRT cue")."""
    kept, dropped = [], []
    for i, c in enumerate(cues, 1):
        start = round(c["start_ms"] * TICKS_PER_MS / tpf)
        end = round(c["end_ms"] * TICKS_PER_MS / tpf)
        if end <= start:
            dropped.append({"cue": i, "text": c["text"], "start_ms": c["start_ms"], "end_ms": c["end_ms"]})
            continue
        if kept and start < kept[-1]["end_frame"]:
            raise ValueError(f"cue {i} starts before cue {kept[-1]['cue']} ends; captions cannot overlap")
        kept.append({"cue": i, "text": c["text"], "start_frame": start, "end_frame": end})
    if not kept:
        raise ValueError("every cue is shorter than a frame")
    return kept, dropped


def _stamp(frame: int, tpf: int) -> str:
    ms = math.ceil(frame * tpf / TICKS_PER_MS)  # the first ms inside the frame: Premiere floors it back
    h, rest = divmod(ms, 3600000)
    m, rest = divmod(rest, 60000)
    s, ms = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt_text(frames: list[dict], tpf: int) -> str:
    return "".join(f"{n}\n{_stamp(c['start_frame'], tpf)} --> {_stamp(c['end_frame'], tpf)}\n{c['text']}\n\n"
                   for n, c in enumerate(frames, 1))


# --- pixels ----------------------------------------------------------------------------------------

def find_caption_row(window: Image.Image) -> tuple[int, int]:
    """A point on the selected Project panel row whose label is the caption yellow (window px).
    Exactly one such row must show, or nothing is dragged."""
    a = np.asarray(window.convert("RGB")).astype(int)
    yellow = (np.abs(a - LABEL_YELLOW).max(axis=2) <= 12)
    rows = []
    for y in np.unique(np.nonzero(yellow)[0]):
        xs = np.nonzero(yellow[y])[0]
        x = int(xs[0])
        span = a[y, x + 20:x + 220].mean(axis=1) if x + 220 < a.shape[1] else np.array([])
        if span.size and (np.abs(span - SELECTED_ROW) <= 3).mean() > 0.6:
            rows.append((x, int(y)))
    if not rows:
        raise RuntimeError("the imported SRT is not the selected row in a visible Project panel; "
                           "show the Project panel (list view) and run again. Nothing was dragged")
    xs = {x for x, _ in rows}
    ys = sorted(y for _, y in rows)
    if max(xs) - min(xs) > 3 or ys[-1] - ys[0] > 24:
        raise RuntimeError("more than one selected caption row in the Project panel; nothing was dragged")
    return min(xs) + 90, (ys[0] + ys[-1]) // 2


def find_timeline(window: Image.Image, caption_tracks: int) -> tuple[int, int]:
    """A drop point in the front timeline's track area, right of the column of track-lock icons,
    on the first row below the `caption_tracks` caption rows (the top video track). Dropped on a
    caption row, Premiere places the SRT onto that track with no dialog and its old style (live
    2026-11-22); on a video row it asks "New caption track"."""
    from scipy.signal import fftconvolve
    template = Image.open(Path(__file__).with_name("ui_templates") / "track_lock.png").convert("L")
    t = np.where(np.asarray(template) > 100, 1.0, -1.0)
    w = np.where(np.asarray(window.convert("L")) > 100, 1.0, -1.0)
    score = fftconvolve(w, t[::-1, ::-1], mode="valid") / t.size
    ys, xs = np.nonzero(score > 0.85)
    if not len(xs):
        raise RuntimeError("no timeline track headers are visible; nothing was dragged")
    column = np.bincount(xs).argmax()
    rows = sorted(set(int(y) for x, y in zip(xs, ys) if abs(int(x) - int(column)) <= 2))
    if len(rows) < caption_tracks + 3:
        raise RuntimeError("the timeline's track headers are not visible; nothing was dragged")
    return int(column) + t.shape[1] // 2 + 300, rows[caption_tracks] + t.shape[0] // 2


def selected(image: Image.Image, x: int, y: int) -> bool:
    a = np.asarray(image.convert("L")).astype(int)[y - 3:y + 4, x - 3:x + 4]
    return a.mean() > 60  # filled radio ~90, empty ~20


# --- mouse and the dialog --------------------------------------------------------------------------

def drag(start: tuple[int, int], end: tuple[int, int]) -> None:
    """Left-drag between two screen points, slowly enough for Premiere to see a drag."""
    (x0, y0), (x1, y1) = start, end
    ui._send([ui._mouse(x0, y0, 0)])
    time.sleep(0.15)
    ui._send([ui._mouse(x0, y0, 0x0002)])
    time.sleep(0.2)
    for i in range(1, 31):
        ui._send([ui._mouse(x0 + (x1 - x0) * i // 30, y0 + (y1 - y0) * i // 30, 0)])
        time.sleep(0.03)
    time.sleep(0.5)
    ui._send([ui._mouse(x1, y1, 0x0004)])


def _wait_dialog(timeout_s: float = 5.0) -> int:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        hwnd = ui.dialog_in_front(CAPTION_TITLE)
        if hwnd:
            time.sleep(0.3)
            return hwnd
        time.sleep(0.1)
    raise RuntimeError(f'the drop did not open "{CAPTION_TITLE}": it may have placed the captions on a '
                       "caption track or done something else. Read the timeline back before anything more")


def _pick_style(hwnd: int, style: int) -> None:
    left, top, _, _ = ui._rect(hwnd)
    field = (STYLE_FIELD[0] - 110, STYLE_FIELD[1] - 18, STYLE_FIELD[0] + 110, STYLE_FIELD[1] + 18)
    before = np.asarray(ui.grab(hwnd).crop(field)).astype(int)
    ui.click(left + STYLE_FIELD[0], top + STYLE_FIELD[1])
    popup = ui._user32().GetForegroundWindow()
    if popup == hwnd or ui._pid(popup) != ui._pid(screenshot.premiere_window()):
        raise RuntimeError("the Style list did not open")
    p_left, p_top, p_right, p_bottom = ui._rect(popup)
    y = p_top + POPUP_FIRST_ROW + POPUP_ROW * style
    if y > p_bottom - 8:
        ui.press(ui.VK_ESCAPE)
        time.sleep(0.4)
        raise RuntimeError(f"the Style list has {max(0, (p_bottom - p_top - POPUP_FIRST_ROW) // POPUP_ROW)} "
                           f"saved style(s), not {style}")
    ui.click((p_left + p_right) // 2, y)
    ui.require_front(hwnd, CAPTION_TITLE)
    after = np.asarray(ui.grab(hwnd).crop(field)).astype(int)
    if np.abs(after - before).mean() < 2:
        raise RuntimeError("the Style field did not change")


def caption_dialog(style: int) -> None:
    """Answer "New caption track": the `style`-th saved Style (0 = None), Source timecode, OK."""
    hwnd = _wait_dialog()
    try:
        left, top, right, bottom = ui._rect(hwnd)
        if (right - left, bottom - top) != CAPTION_SIZE or ui._user32().GetDpiForWindow(hwnd) != 96:
            raise RuntimeError(f'"{CAPTION_TITLE}" is {right - left}x{bottom - top} at '
                               f"{ui._user32().GetDpiForWindow(hwnd)} DPI, not the measured {CAPTION_SIZE} at 96")
        if not selected(ui.grab(hwnd), *SOURCE_TIMECODE_RADIO):
            raise RuntimeError("Start Point is not Source timecode; pick it once by hand (Premiere remembers)")
        if style:
            _pick_style(hwnd, style)
        ui._confirm(hwnd, CAPTION_TITLE)
    except Exception:
        ui.close_dialog(hwnd, CAPTION_TITLE)
        raise


def place_by_drag(style: int, caption_tracks: int) -> dict:
    """Drag the selected caption row onto the front timeline and answer the dialog (blocking)."""
    window = ui.window_image()
    row, drop = find_caption_row(window), find_timeline(window, caption_tracks)
    hwnd = screenshot.premiere_window()
    left, top, _, _ = ui._rect(hwnd)
    ui._user32().SetForegroundWindow(hwnd)
    time.sleep(0.3)
    drag((left + row[0], top + row[1]), (left + drop[0], top + drop[1]))
    caption_dialog(style)
    return {"row": row, "drop": drop}


# --- the command -----------------------------------------------------------------------------------

def _captions(report: dict) -> list[list[tuple[int, int]]]:
    return [[(int(i["start_ticks"]), int(i["end_ticks"])) for i in t.get("items", [])] for t in report["tracks"]]


async def _caption_report(premiere, sequence: str) -> list[list[tuple[int, int]]]:
    report = (await premiere("run_probe", {"probe": "captiontiming"}))["report"]
    if not report.get("complete") or report.get("sequence_name") != sequence:
        raise RuntimeError(f"could not read the captions of '{sequence}': {report.get('error') or report.get('sequence_name')}")
    return _captions(report)


def _video(timeline: dict) -> dict[str, dict]:
    return {c["id"]: {**c, "track": int(t["id"][1:])} for t in timeline["tracks"] if t["id"].startswith("V")
            for c in t.get("clips", [])}


def _off(got: list[tuple[int, int]], frames: list[dict], tpf: int) -> list[dict]:
    want = [(c["start_frame"] * tpf, c["end_frame"] * tpf) for c in frames]
    if len(got) != len(want):
        return [{"problem": f"{len(got)} items for {len(want)} cues"}]
    return [{"cue": c["cue"], "want_frames": [c["start_frame"], c["end_frame"]], "got_frames": [g[0] / tpf, g[1] / tpf]}
            for c, g, w in zip(frames, got, want) if g != w]


async def run(premiere, args: dict) -> dict:
    sequence, track, style, position = args["sequence"], args.get("track"), args.get("style", 1), args.get("position")
    scale = args.get("scale")
    source = Path(args["srt"])
    seq = (await premiere("open_sequence", {"sequence": sequence}))["name"]
    info = await premiere("read_sequence")
    tpf, project = int(info["ticks_per_frame"]), info["project_path"]
    frames, dropped = to_frames(parse_srt(source.read_text(encoding="utf-8-sig")), tpf)
    first, last = frames[0]["start_frame"] * tpf, frames[-1]["end_frame"] * tpf

    captions = await _caption_report(premiere, seq)
    if any(captions):
        raise ValueError(f"'{seq}' already has captions; Select All + Upgrade would turn them into Graphics too. "
                         "Nothing was done")
    before = _video(await premiere("read_timeline", {"sequence": seq}))
    if track is not None:
        if track > info["video_track_count"]:
            raise ValueError(f"'{seq}' has no V{track}")
        busy = [i for i, c in before.items() if c["track"] == track and int(c["start_ticks"]) < last and int(c["end_ticks"]) > first]
        if busy:
            raise ValueError(f"V{track} is not empty between the first and last subtitle: {busy[:5]}. Nothing was done")

    folder = Path(project.removeprefix("\\\\?\\")).parent / "CutDeck" / "Subtitles"
    folder.mkdir(parents=True, exist_ok=True)
    written = folder / f"{source.stem}-{uuid.uuid4().hex[:8]}.srt"
    written.write_text(srt_text(frames, tpf), encoding="utf-8")
    await premiere("import_files", {"paths": [str(written)]})
    await asyncio.sleep(1.0)
    drop = await keys.run_focused(premiere, "timeline", seq, lambda: place_by_drag(style, len(captions)))
    await asyncio.sleep(1.0)
    placed = [t for t in await _caption_report(premiere, seq) if t]
    if len(placed) != 1:
        raise RuntimeError(f"expected one caption track with the subtitles, found {len(placed)}; nothing was upgraded")
    caption_off = _off(placed[0], frames, tpf)
    if caption_off:
        raise RuntimeError(f"captions landed off the cues {caption_off[:5]}; nothing was upgraded")

    for path in ("Edit > Select All", "Graphics and Titles > Upgrade Caption to Graphic", "Edit > Deselect All"):
        await premiere("menu_command", {"path": path, "sequence": seq})
        await asyncio.sleep(1.0)
    upgraded = {i: c for i, c in _video(await premiere("read_timeline", {"sequence": seq})).items() if i not in before}
    landed = sorted({c["track"] for c in upgraded.values()})
    graphics = sorted(upgraded.values(), key=lambda c: int(c["start_ticks"]))
    off = _off([(int(c["start_ticks"]), int(c["end_ticks"])) for c in graphics], frames, tpf)
    if len(landed) != 1 or off:
        raise RuntimeError(f"Upgrade gave {len(graphics)} Graphics on V{landed}, off the cues: {off[:5]}")
    landed = landed[0]
    left_over = [t for t in await _caption_report(premiere, seq) if t]
    # The build picks clips by track and start, not by id, and Upgrade fills the gaps around clips
    # already on its track (live 2026-11-22: a title between two cues stayed in place on V3 with
    # the Graphics around it). So the span is split at every such clip: only Graphics are moved.
    others = sorted(int(c["start_ticks"]) for c in before.values() if c["track"] == landed)
    spans, run = [], [int(graphics[0]["start_ticks"])]
    for g in graphics[1:]:
        start = int(g["start_ticks"])
        if any(run[-1] < o < start for o in others):
            spans.append(run)
            run = []
        run.append(start)
    spans.append(run)
    spans = [{"from_ticks": str(r[0]), "to_ticks": str(r[-1] + 1)} for r in spans]

    target = track or landed
    steps, restyle = [], []
    if target != landed:
        steps = [{"op": op, **span, "tracks": {"video": [landed - 1]}, **extra} for span in spans
                 for op, extra in (("clone", {"dt_ticks": "0", "v_offset": target - landed}), ("lift", {}))]
    motion = {**({"position": list(position)} if position is not None else {}), **({"scale": scale} if scale is not None else {})}
    if motion:
        restyle = [{"kind": "video", "track": target - 1, **span, "motion": motion} for span in spans]
    if steps or restyle:
        await premiere("build_sequence", {"project": project, "base": seq, "name": seq, "into": True, "items": [],
                                          "steps": steps, "restyle": restyle})
    final = [c for c in _video(await premiere("read_timeline", {"sequence": seq, "tracks": [f"V{target}"]})).values()
             if first <= int(c["start_ticks"]) < last]
    final.sort(key=lambda c: int(c["start_ticks"]))
    final_off = _off([(int(c["start_ticks"]), int(c["end_ticks"])) for c in final], frames, tpf)
    return {
        "sequence": seq, "track": f"V{target}", "upgraded_on": f"V{landed}", "cues": len(frames) + len(dropped),
        "graphics": [c["id"] for c in final], "off_cues": final_off, "dropped_cues": dropped,
        "captions_left": sum(len(t) for t in left_over), "srt_imported": str(written), "drag": drop,
        "note": ("Each Graphic was read back against the SRT snapped to frames (off_cues lists any that differ). "
                 "Upgrade leaves an empty caption track; a later run on this sequence still works (drag route). "
                 + (f"V{landed} may now be an empty track. " if target != landed else "")
                 + "Undo takes several Edit > Undo steps (import, captions, upgrade, build)."),
    }
