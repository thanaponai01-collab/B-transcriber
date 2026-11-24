"""Bake text into a copy of a Motion Graphics Template (.mogrt) for `place_text`.

Why: Premiere 27.0's UXP text write (`MogrtText.setText` -> `createKeyframe` ->
`createSetValueAction`) stores an EMPTY value and the layer renders blank, and a plain string is
"Illegal Parameter type" (PREMIERE_FACTS "MogrtText write, 27.0"). Inserting a template works,
so the text goes into the template before Premiere sees it.

A .mogrt is a zip. Each editable text is a `clientControls` entry of type 6 in definition.json,
whose `value.strDB[].str` is the text per locale. After Effects templates also carry it as
`sourceInfoLocalized.<locale>.capsuleparams.capParams[].capPropDefault`. Premiere caches a template
by `capsuleID`, so a baked copy gets a new one, or Premiere re-places the cached original.
Live-proven 2026-11-21 on Premiere 27.0.0 with Premiere's own "Basic Title" and an AE template.
"""
from __future__ import annotations

import json
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

TEXT_CONTROL = 6
MAX_AGE_S = 7 * 24 * 3600  # baked copies older than this are deleted on the next bake


def _name(control: dict) -> str:
    names = control.get("uiName", {}).get("strDB", [])
    english = [n["str"] for n in names if n.get("localeString") == "en_US"]
    return (english or [n["str"] for n in names] or [""])[0]


def text_controls(template: str | Path) -> list[dict]:
    """Every editable text of a template: index (0-based, among texts), name and default text."""
    with zipfile.ZipFile(template) as z:
        definition = json.loads(z.read("definition.json"))
    texts = [c for c in definition.get("clientControls", []) if c.get("type") == TEXT_CONTROL]
    return [{"index": i, "name": _name(c), "text": ((c.get("value") or {}).get("strDB") or [{}])[0].get("str", "")}
            for i, c in enumerate(texts)]


def bake(template: str | Path, texts: dict[str, str]) -> Path:
    """Copy `template` with each text set. Keys are a text's name or its index as a string.
    Returns the new .mogrt path. Raises ValueError naming the template's texts on a bad key."""
    template = Path(template)
    controls = text_controls(template)
    by_key = {**{c["name"]: c["index"] for c in controls}, **{str(c["index"]): c["index"] for c in controls}}
    unknown = [k for k in texts if k not in by_key]
    if unknown or not texts:
        known = ", ".join(f'{c["index"]} "{c["name"]}"' for c in controls) or "none"
        raise ValueError(f"unknown text {unknown} for {template.name}; its texts are: {known}")
    wanted = {by_key[k]: v for k, v in texts.items()}

    bake_dir = Path(tempfile.gettempdir()) / "cutdeck-mogrt"
    bake_dir.mkdir(exist_ok=True)
    for old in bake_dir.glob("*.mogrt"):
        try:
            if time.time() - old.stat().st_mtime > MAX_AGE_S:
                old.unlink(missing_ok=True)
        except FileNotFoundError:  # another bake removed it first
            pass
    out = bake_dir / f"{template.stem}-{uuid.uuid4().hex[:8]}.mogrt"
    with zipfile.ZipFile(template) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename == "definition.json":
                definition = json.loads(data)
                text_index = -1
                for control in definition.get("clientControls", []):
                    if control.get("type") != TEXT_CONTROL:
                        continue
                    text_index += 1
                    if text_index not in wanted:
                        continue
                    for entry in control.get("value", {}).get("strDB", []):
                        entry["str"] = wanted[text_index]
                    for locale in (definition.get("sourceInfoLocalized") or {}).values():
                        for param in (locale.get("capsuleparams") or {}).get("capParams", []):
                            if param.get("capPropUIName") == _name(control):
                                param["capPropDefault"] = wanted[text_index]
                definition["capsuleID"] = str(uuid.uuid4())
                data = json.dumps(definition, ensure_ascii=False).encode("utf-8")
            dst.writestr(info, data)
    return out
