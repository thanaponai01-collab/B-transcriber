"""Premiere's blue text box, predicted from the saved project and the font.

The Transform panel can measure where a Graphic's letters are drawn (frame_bounds.py), but
Premiere aligns text, and snaps its anchor, by a different box: the blue one in the Program
Monitor. UXP can't read a text layer's font, size or string (docs/PREMIERE_FACTS.md, Source
Text rows), so the helper reads them from the newest save of the project and computes the box.

The rule, from Premiere's own Align buttons (PREMIERE_FACTS, "Premiere's blue text box", live
2026-10-19 and 2026-11-27), in the text layer's own space (first baseline y = 0, y down): each
line is shaped on its own and starts at x = 0 (left), -advance / 2 (centre) or -advance (right
aligned); baselines are 1.2 x size + Leading apart. The box runs from the top of the first line
to the bottom of the last, each line one em tall and centred capHeight / 2 above its baseline;
from x = 0 (left aligned) or the leftmost line's first letter (centre, right) to the furthest
line end. Proven without tracking, faux styles or mixed runs; anything else gets a reason
instead of a box, and the panel keeps anchoring to the measured letters.

Each layer also carries its predicted letters (``ink``), so the panel can check the save still
matches what is drawn before trusting the box.
"""

import glob
import os
from functools import lru_cache
from pathlib import Path

from cutdeck.prproj_reader import read_project

TICKS_PER_SECOND = 254016000000
_FONT_DIRS = [r"C:\Windows\Fonts", os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts")]


def newest_save(project_path: str) -> Path:
    """The project file or one of its auto-saves (``<stem>--*.prproj`` in the sibling
    "Adobe Premiere Pro Auto-Save" folder), whichever was written last."""
    path = Path(project_path.removeprefix("\\\\?\\"))
    autos = path.parent / "Adobe Premiere Pro Auto-Save"
    candidates = [path, *autos.glob(f"{glob.escape(path.stem)}--*.prproj")]
    saved = [p for p in candidates if p.exists()]
    if not saved:
        raise LookupError("the project has not been saved yet")
    return max(saved, key=lambda p: p.stat().st_mtime)


@lru_cache(maxsize=1)
def _font_index() -> dict[str, str]:
    """PostScript name -> font file, for every font installed for all users or this user."""
    from fontTools.ttLib import TTFont

    index = {}
    for folder in _FONT_DIRS:
        for file in glob.glob(os.path.join(folder, "*")):
            if not file.lower().endswith((".ttf", ".otf")):
                continue
            try:
                name = TTFont(file, lazy=True)["name"].getDebugName(6)
            except Exception:
                continue
            if name:
                index.setdefault(name, file)
    return index


def installed_font(postscript_name: str) -> str | None:
    return _font_index().get(postscript_name)


@lru_cache(maxsize=16)
def _font(path: str):
    import uharfbuzz as hb
    from fontTools.ttLib import TTFont

    os2 = TTFont(path, lazy=True)["OS/2"]
    face = hb.Face(hb.Blob.from_file_path(path))
    return hb.Font(face), face.upem, getattr(os2, "sCapHeight", 0) or 0


def layer_box(text: dict, font_path) -> dict:
    """``{"box", "ink"}`` in the text layer's own pixels, or ``{"reason"}`` when the rule wasn't
    proven for this text. ``text`` is prproj_reader's decoded Source Text; ``font_path`` maps a
    PostScript name to its file (None when not installed)."""
    runs = text.get("runs") or []
    if not runs or not text["text"]:
        return {"reason": "the saved text has no runs"}
    alignment = text.get("alignment") or "left"
    lines = text["text"].replace("\n", "\r").split("\r")
    if text.get("box_width"):
        return {"reason": "the text is paragraph (area) text (only point text is proven)"}
    if any(not line.strip() for line in lines):
        return {"reason": "the text has a blank line (not proven)"}
    first = runs[0]
    if any(r["font"] != first["font"] or r["size"] != first["size"] for r in runs):
        return {"reason": "the text mixes fonts or sizes"}
    if any(r.get("tracking") for r in runs):
        return {"reason": "the text has tracking (not proven)"}
    if any(r.get("bold") or r.get("italic") for r in runs):
        return {"reason": "the text uses faux bold or italic (not proven)"}
    path = font_path(first["font"])
    if not path:
        return {"reason": f"font {first['font']} is not installed where the helper looks"}
    font, upem, cap = _font(str(path))
    if cap <= 0:
        return {"reason": f"font {first['font']} has no cap height"}

    s = first["size"] / upem
    step = _line_step(first["size"], text.get("leading") or 0.0) / s  # font units
    left = right = None
    ink = None  # (left, right, top, bottom), font units, y down
    for i, line in enumerate(lines):
        advance, line_ink = _shape(font, line)
        start = {"left": 0, "center": -advance / 2, "right": -advance}[alignment]
        if line_ink:
            glyph = (start + line_ink[0], start + line_ink[1], i * step - line_ink[2], i * step - line_ink[3])
            ink = glyph if ink is None else (min(ink[0], glyph[0]), max(ink[1], glyph[1]),
                                            min(ink[2], glyph[2]), max(ink[3], glyph[3]))
            # Left text's box starts at its origin; centred and right text's at the first letter.
            line_left = start if alignment == "left" else start + line_ink[0]
            left = line_left if left is None else min(left, line_left)
        right = start + advance if right is None else max(right, start + advance)
    centre = cap / 2
    return {
        "box": {"left": (left or 0.0) * s, "right": right * s, "top": -(centre + upem / 2) * s,
                "bottom": ((len(lines) - 1) * step + upem / 2 - centre) * s},
        "ink": None if ink is None else {"left": ink[0] * s, "right": ink[1] * s, "top": ink[2] * s, "bottom": ink[3] * s},
    }


def _line_step(size: float, leading: float) -> float:
    """Baseline to baseline, in layer pixels: Leading 0 is Premiere's auto, 120% of the size."""
    return 1.2 * size + leading


def _shape(font, line: str):
    """The shaped advance of one line and its letters' box (left, right, top, bottom; font
    units, y up, from the pen start), or None when it draws nothing."""
    import uharfbuzz as hb

    buf = hb.Buffer()
    buf.add_str(line)
    buf.guess_segment_properties()
    hb.shape(font, buf, {})
    pen = 0
    ink = None
    for info, pos in zip(buf.glyph_infos or [], buf.glyph_positions or []):
        e = font.get_glyph_extents(info.codepoint)
        if e and e.width and e.height:
            x = pen + pos.x_offset + e.x_bearing
            y_top = pos.y_offset + e.y_bearing  # y up
            glyph = (x, x + e.width, y_top, y_top + e.height)
            ink = glyph if ink is None else (min(ink[0], glyph[0]), max(ink[1], glyph[1]),
                                            max(ink[2], glyph[2]), min(ink[3], glyph[3]))
        pen += pos.x_advance
    return pen, ink


def clip_layers(project: dict, sequence: str, track: int, start_s: float, font_path) -> list[dict]:
    """One ``layer_box`` per text layer of the clip at ``start_s`` on video track ``track``
    (0-based, as UXP's getTrackIndex), in chain order."""
    for seq in project["sequences"]:
        if seq["name"] != sequence:
            continue
        for t in seq["video_tracks"]:
            if t["index"] != track:
                continue
            for clip in t["clips"]:
                if abs(clip["start"] - start_s) < 1e-3:
                    return [layer_box(e["text"], font_path) if not e["text"].get("keyframes")
                            else {"reason": "the Source Text is keyframed"}
                            for e in clip["effects"] if e.get("match_name") == "AE.ADBE Text" and e.get("text")]
    raise LookupError("the clip is not in the last save; save the project")


def request(req: dict) -> dict:
    """The helper's ``text_box`` request: ``{project, sequence, track, start_ticks}``."""
    save = newest_save(req["project"])
    layers = clip_layers(read_project(save), req["sequence"], int(req["track"]),
                         int(req["start_ticks"]) / TICKS_PER_SECOND, installed_font)
    return {"save": str(save), "layers": layers}
