"""Premiere's blue text box, predicted from the saved project and the font.

The Transform panel can measure where a Graphic's letters are drawn (frame_bounds.py), but
Premiere aligns text, and snaps its anchor, by a different box: the blue one in the Program
Monitor. UXP can't read a text layer's font, size or string (docs/PREMIERE_FACTS.md, Source
Text rows), so the helper reads them from the newest save of the project and computes the box.

The rule, from Premiere's own Align buttons on two sizes (PREMIERE_FACTS, "Premiere's blue
text box", live 2026-10-19), in the text layer's own space (baseline y = 0, y down): the box is
one em tall, centred capHeight / 2 above the baseline, and runs from x = 0 to the shaped
advance. Proven for one line of left-aligned, untracked, non-faux text; anything else gets a
reason instead of a box, and the panel keeps anchoring to the measured letters.

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
    import uharfbuzz as hb

    runs = text.get("runs") or []
    if not runs:
        return {"reason": "the saved text has no runs"}
    if text.get("alignment") not in (None, "left"):
        return {"reason": f"the text is {text['alignment']} aligned (only left is proven)"}
    if "\r" in text["text"] or "\n" in text["text"]:
        return {"reason": "the text has more than one line (only one line is proven)"}
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

    buf = hb.Buffer()
    buf.add_str(text["text"])
    buf.guess_segment_properties()
    hb.shape(font, buf, {})
    s = first["size"] / upem
    pen = 0
    ink = None
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        e = font.get_glyph_extents(info.codepoint)
        if e and e.width and e.height:
            x = pen + pos.x_offset + e.x_bearing
            y_top = pos.y_offset + e.y_bearing  # y up
            glyph = (x, x + e.width, y_top, y_top + e.height)
            ink = glyph if ink is None else (min(ink[0], glyph[0]), max(ink[1], glyph[1]),
                                            max(ink[2], glyph[2]), min(ink[3], glyph[3]))
        pen += pos.x_advance
    centre = cap / 2
    return {
        "box": {"left": 0.0, "right": pen * s, "top": -(centre + upem / 2) * s, "bottom": (upem / 2 - centre) * s},
        "ink": None if ink is None else {"left": ink[0] * s, "right": ink[1] * s, "top": -ink[2] * s, "bottom": -ink[3] * s},
    }


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
