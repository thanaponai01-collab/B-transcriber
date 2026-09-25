"""cutdeck/text_properties.py — text layers from a saved Premiere project, and text measuring.

Premiere Pro's UXP and ExtendScript APIs do not expose the 'Source Text' parameter
(AE.ADBE Text param 0): getStartValue() resolves empty (see docs/PREMIERE_FACTS.md). The saved
.prproj holds it, and cutdeck.prproj_reader decodes it; this module lists those text layers and
measures text with the real font outlines.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

from PIL import ImageFont

from cutdeck.prproj_reader import read_project


def extract_project_text_properties(prproj_path: str | Path) -> list[dict[str, Any]]:
    """One entry per text clip in a saved .prproj: where it is, its string, font and size."""
    path = Path(prproj_path)
    if not path.is_file():
        raise FileNotFoundError(f"Project file not found: {path}")
    out = []
    for seq in read_project(path)["sequences"]:
        for track in seq["video_tracks"]:
            for clip in track["clips"]:
                for effect in clip["effects"]:
                    if effect.get("text"):
                        out.append({
                            "sequence": seq["name"], "track": track["index"],
                            "clip": clip["name"], "start": clip["start"], "end": clip["end"],
                            **effect["text"],
                        })
    return out


def tokenize_font(name: str) -> set[str]:
    """Tokenizes a font name or PostScript name into normalized tokens."""
    name_clean = re.sub(r"(?:MT|PS|Pro)?$", "", name)
    return {t.lower() for t in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|\d+", name_clean)}


def resolve_font_file(font_name: str | None) -> Path | None:
    """Attempts to find a local font file (.ttf / .otf) matching the given font or PostScript name.

    Searches:
    1. Direct file path if given.
    2. OS font directory (e.g. C:\\Windows\\Fonts).
    3. OS font registry (Windows HKLM Fonts).
    """
    if not font_name:
        return None
    font_path = Path(font_name)
    if font_path.is_file():
        return font_path

    font_dirs: list[Path] = []
    if sys.platform == "win32":
        font_dirs.append(Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts")
    elif sys.platform == "darwin":
        font_dirs.extend([Path("/Library/Fonts"), Path("/System/Library/Fonts"), Path.home() / "Library/Fonts"])
    else:
        font_dirs.extend([Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts"])

    for fd in font_dirs:
        if not fd.is_dir():
            continue
        for ext in (".ttf", ".otf", ".ttc"):
            cand = fd / f"{font_name}{ext}"
            if cand.is_file():
                return cand

    target_tokens = tokenize_font(font_name)
    if sys.platform == "win32" and font_dirs:
        try:
            import winreg
            font_dir = font_dirs[0]
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts") as key:
                count = winreg.QueryInfoKey(key)[1]
                best_match = None
                best_score = 0.0
                for i in range(count):
                    reg_name, reg_val, _ = winreg.EnumValue(key, i)
                    clean_name = reg_name.split("(")[0]
                    tokens = tokenize_font(clean_name)
                    if not tokens:
                        continue
                    intersection = target_tokens.intersection(tokens)
                    score = len(intersection) / max(len(target_tokens), len(tokens))
                    if score > best_score:
                        cand = Path(reg_val) if Path(reg_val).is_absolute() else font_dir / reg_val
                        if cand.is_file():
                            best_score = score
                            best_match = cand
                if best_score >= 0.5:
                    return best_match
        except Exception:
            pass

    return None


def measure_text_bounds(
    text: str,
    font_name_or_path: str = "",
    font_size: float = 100.0,
    scale_x: float = 100.0,
    scale_y: float = 100.0,
) -> dict[str, Any]:
    """Calculates text bounding box and advance geometry mathematically in <1 ms with 0 undo steps.

    Uses the actual font glyph outlines via FreeType / PIL ImageFont.
    Returns:
        width, height, advance, left, top, right, bottom (relative to origin/baseline).
    """
    font_file = resolve_font_file(font_name_or_path)
    try:
        if font_file:
            font = ImageFont.truetype(str(font_file), size=max(1, int(round(font_size))))
        else:
            font = ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    if not text:
        return {
            "width": 0.0, "height": 0.0, "advance": 0.0,
            "left": 0.0, "top": 0.0, "right": 0.0, "bottom": 0.0,
            "font_resolved": str(font_file) if font_file else None,
        }

    bbox = font.getbbox(text)
    advance = font.getlength(text) if hasattr(font, "getlength") else float(bbox[2] - bbox[0])

    sx = scale_x / 100.0
    sy = scale_y / 100.0

    return {
        "width": round((bbox[2] - bbox[0]) * sx, 2),
        "height": round((bbox[3] - bbox[1]) * sy, 2),
        "advance": round(advance * sx, 2),
        "left": round(bbox[0] * sx, 2),
        "top": round(bbox[1] * sy, 2),
        "right": round(bbox[2] * sx, 2),
        "bottom": round(bbox[3] * sy, 2),
        "font_resolved": str(font_file) if font_file else None,
    }
