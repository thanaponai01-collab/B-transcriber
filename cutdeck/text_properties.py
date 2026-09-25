"""cutdeck/text_properties.py — extracts text and typography properties from Premiere Pro projects.

Premiere Pro's UXP and ExtendScript APIs do not expose the 'Source Text' parameter
(AE.ADBE Text param 0) to scripts or plugins (getStartValue() resolves empty and
ExtendScript returns a binary U+0164 char; see docs/research/cutdeck-text-graphic-properties.md).

However, the saved .prproj file stores complete text properties inside gzip-compressed XML:
    <Component ...>
      <MatchName>AE.ADBE Text</MatchName>
      <ComponentParams>
        <ArbVideoComponentParam>
          <ParamName>Source Text</ParamName>
          <StartKeyframeValue>...base64...</StartKeyframeValue>
        </ArbVideoComponentParam>
      </ComponentParams>
    </Component>

This module decodes the base64-encoded binary stream from ArbVideoComponentParam
to extract the text string, PostScript font name, and typography metadata.
"""

from __future__ import annotations

import base64
import gzip
import io
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from PIL import ImageFont


def decompress_prproj(data: bytes) -> str:
    """Decompresses .prproj gzip bytes into an XML string.
    If the data is already plain XML, decodes as utf-8 directly."""
    if data[:2] == b"\x1f\x8b":
        return gzip.decompress(data).decode("utf-8", errors="replace")
    return data.decode("utf-8", errors="replace")


def parse_source_text_blob(blob: bytes) -> dict[str, Any]:
    """Parses Premiere's ArbVideoComponentParam binary blob for Source Text.

    The binary stream contains:
    - Text content (ASCII / UTF-8 / UTF-16 runs)
    - PostScript font identifier (e.g. 'LucidaCalligraphy-Italic', 'Arial-BoldMT')
    - Font size and style attributes
    """
    result: dict[str, Any] = {
        "text": "",
        "font_name": None,
        "font_size": None,
        "raw_length": len(blob),
    }
    if not blob:
        return result

    # 1. Look for PostScript font names: typically alphanumeric + hyphens (e.g. Arial-BoldMT, LucidaCalligraphy-Italic)
    # They often appear with length prefix or null-termination in ASCII.
    font_pattern = re.compile(rb"([A-Za-z0-9]+(?:-[A-Za-z0-9]+)+)")
    font_matches = font_pattern.findall(blob)
    if font_matches:
        # Longest match or first typical PostScript name
        result["font_name"] = font_matches[0].decode("ascii", errors="ignore")

    # 2. Extract printable text strings (UTF-16 LE and UTF-8 / ASCII)
    # UTF-16LE: ASCII (byte + 0x00) or Thai (byte + 0x0e)
    utf16_pattern = re.compile(rb"(?:(?:[\x20-\x7e]\x00)|(?:[\x00-\xff]\x0e)){2,}")
    utf16_matches = utf16_pattern.findall(blob)
    extracted_texts = []
    for m in utf16_matches:
        try:
            decoded = m.decode("utf-16le", errors="ignore").strip()
            if len(decoded) > 1 and decoded != result["font_name"]:
                extracted_texts.append(decoded)
        except Exception:
            pass

    # Fallback to UTF-8 / ASCII text runs
    if not extracted_texts:
        ascii_matches = re.findall(rb"(?:[\x20-\x7e]|\xe0[\xb8-\xb9][\x80-\xbf]){2,}", blob)
        for m in ascii_matches:
            try:
                decoded = m.decode("utf-8", errors="ignore").strip()
                if len(decoded) > 1 and decoded != result["font_name"]:
                    extracted_texts.append(decoded)
            except Exception:
                pass

    if extracted_texts:
        # Choose the most plausible text content (non-font string)
        result["text"] = max(extracted_texts, key=len)

    return result


def extract_graphic_texts_from_xml(xml_content: str) -> list[dict[str, Any]]:
    """Extracts all text graphic layers from a decompressed .prproj XML string."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        raise ValueError(f"Invalid Premiere project XML: {e}") from e

    texts = []
    # Search for all Component elements with MatchName == 'AE.ADBE Text'
    for comp in root.iter("Component"):
        match_name_el = comp.find("MatchName")
        if match_name_el is None or match_name_el.text != "AE.ADBE Text":
            continue

        comp_name_el = comp.find("DisplayName")
        comp_name = comp_name_el.text if comp_name_el is not None else "Text"

        # Search for ArbVideoComponentParam with ParamName == 'Source Text'
        for arb in comp.iter("ArbVideoComponentParam"):
            param_name_el = arb.find("ParamName")
            if param_name_el is None or param_name_el.text != "Source Text":
                continue

            val_el = arb.find("StartKeyframeValue")
            if val_el is None or not val_el.text:
                continue

            raw_b64 = val_el.text.strip()
            try:
                blob = base64.b64decode(raw_b64)
            except Exception:
                continue

            parsed = parse_source_text_blob(blob)
            texts.append({
                "component_name": comp_name,
                "text": parsed["text"],
                "font_name": parsed["font_name"],
                "raw_length": parsed["raw_length"],
            })

    return texts


def extract_project_text_properties(prproj_path: str | Path) -> list[dict[str, Any]]:
    """Reads a .prproj file directly and extracts all text graphic properties."""
    path = Path(prproj_path)
    if not path.is_file():
        raise FileNotFoundError(f"Project file not found: {path}")

    raw_bytes = path.read_bytes()
    xml_str = decompress_prproj(raw_bytes)
    return extract_graphic_texts_from_xml(xml_str)


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
