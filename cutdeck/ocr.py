"""Read the words Premiere draws, with Windows' own OCR (`ocr.ps1`, Windows.Media.Ocr), for UI routes
that must find a panel row or a dropdown entry by its label. Premiere's panels are drawn by Premiere,
not Win32 controls, so their text is only in pixels. The image is upscaled 2x first: small panel
text read reliably only then (live 2026-11-27)."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

SCRIPT = Path(__file__).with_name("ocr.ps1")
UPSCALE = 2


def parse(out: str, scale: float = 1.0, offset: tuple[int, int] = (0, 0)) -> list[dict]:
    """ocr.ps1's output -> lines [{text, box (x0, y0, x1, y1), words [{text, box}]}], boxes divided by
    `scale` and shifted by `offset` (where the read image sits in the bigger one)."""
    lines, words = [], []
    for row in out.splitlines():
        if row.strip() == "--":
            if words:
                boxes = [w["box"] for w in words]
                lines.append({"text": " ".join(w["text"] for w in words), "words": words,
                              "box": (min(b[0] for b in boxes), min(b[1] for b in boxes),
                                      max(b[2] for b in boxes), max(b[3] for b in boxes))})
            words = []
            continue
        parts = row.split("\t")
        if len(parts) != 5:
            continue
        x, y, w, h = (int(v) for v in parts[1:])
        ox, oy = offset
        words.append({"text": parts[0], "box": (round(x / scale) + ox, round(y / scale) + oy,
                                                round((x + w) / scale) + ox, round((y + h) / scale) + oy)})
    return lines


def read(image: Image.Image, offset: tuple[int, int] = (0, 0)) -> list[dict]:
    """Every line of text in `image` (boxes in its pixels, plus `offset`)."""
    big = image.convert("RGB").resize((image.width * UPSCALE, image.height * UPSCALE), Image.LANCZOS)
    fd, path = tempfile.mkstemp(suffix=".png", prefix="cutdeck-ocr-")
    os.close(fd)
    try:
        big.save(path)
        done = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), "-Path", path],
                              capture_output=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    finally:
        os.unlink(path)
    if done.returncode:
        raise RuntimeError(f"Windows OCR failed: {done.stderr.decode('utf-8', 'replace')[-300:]}")
    return parse(done.stdout.decode("utf-8", "replace"), UPSCALE, offset)
