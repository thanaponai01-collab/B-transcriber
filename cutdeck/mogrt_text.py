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

A template the user exports from Premiere keeps each layer's text as a FlatBuffer "Source Text"
blob in `project.prgraphic` (a zip holding a gzipped .prproj), and Premiere draws that text, not
definition.json's (PREMIERE_FACTS "Baked template text", live 2026-11-27). So the bake rewrites
those blobs too. Basic Title's blobs are the UTF-16 JSON form and Basic Title honours
definition.json (one template of each kind seen), so JSON-form blobs are left alone.
"""
from __future__ import annotations

import base64
import gzip
import io
import json
import re
import struct
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

from cutdeck import text_document
from cutdeck.prproj_reader import _Table, _deref, parse_source_text

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


_SOURCE_TEXT = re.compile(
    r'(<ArbVideoComponentParam\b(?:(?!</ArbVideoComponentParam>).)*?<Name>Source Text</Name>'
    r'(?:(?!</ArbVideoComponentParam>).)*?<StartKeyframeValue Encoding="base64" BinaryHash=")'
    r'([^"]+)"(?:/>|>([^<]*)</StartKeyframeValue>)', re.S)


def _set_flat_text(blob: bytes, text: str) -> bytes:
    """A FlatBuffer Source Text blob with its one run's text replaced, style kept. Layout as
    `prproj_reader.parse_source_text` reads it: a u64 length (= blob size - 12), a 4-byte tag, then
    the buffer, whose root f0 is the document and the document's f0 the runs. The new string is
    appended at the end and the run's text field repointed to it, so no other offset moves."""
    if struct.unpack_from("<Q", blob, 0)[0] != len(blob) - 12:
        raise ValueError("Source Text blob: length prefix is not size - 12; layout not mapped")
    doc = _Table(blob, _deref(blob, 12)).table(0)
    runs = doc._slots(0)
    if len(runs) != 1:
        raise ValueError(f"Source Text layer has {len(runs)} style runs; only one is supported")
    run = _Table(blob, _deref(blob, runs[0]))
    slot = run._fields[0]
    data = text.encode("utf-8")
    out = bytearray(blob) + b"\0" * (-len(blob) % 4)
    target = len(out)
    out += struct.pack("<I", len(data)) + data + b"\0"
    out += b"\0" * (-len(out) % 4)
    struct.pack_into("<I", out, slot, target - slot)
    struct.pack_into("<Q", out, 0, len(out) - 12)
    return bytes(out)


def _new_hash(size: int) -> str:
    """A BinaryHash in Premiere's shape; its last 8 hex digits are the blob size + 12."""
    h = uuid.uuid4().hex
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:24]}{size + 12:08x}"


def _restyled(blob: bytes, text: str | None, changes: dict) -> bytes:
    """The blob re-encoded with `changes` (`text_document.restyle`) and, if given, the new text."""
    try:
        doc = text_document.decode(blob)
    except text_document.UnmappedField as e:
        raise ValueError(f"can't restyle this template's text: {e}") from None
    if text is not None:
        if len(doc["runs"]) != 1:
            raise ValueError(f"Source Text layer has {len(doc['runs'])} style runs; only one is supported")
        doc["runs"][0]["text"] = text
    return text_document.encode(text_document.restyle(doc, changes))


def _rewrite_prproj(xml: str, wanted: dict[int, str], defaults: list[str], styles: dict[int, dict] | None = None) -> str:
    """Set the Source Text of text control i (`wanted`, i -> text; `styles`, i -> style changes)
    in a Premiere project. Control i is the n-th FlatBuffer text layer whose text equals its
    default, where n counts the earlier controls with that same default. Raises when a wanted
    or styled control has no layer. A text-only change keeps the blob's bytes and appends the
    string; a style change re-encodes the blob (`text_document`)."""
    styles = styles or {}
    found = list(_SOURCE_TEXT.finditer(xml))
    # Premiere writes a repeated blob once; later copies are empty, keyed by the same BinaryHash.
    blobs = {m[2]: m[3].strip() for m in reversed(found) if (m[3] or "").strip()}
    layers = []  # (match, blob as written or None for an empty twin, decoded text), FlatBuffer only
    for m in found:
        body = (m[3] or "").strip() or None
        raw = base64.b64decode(body or blobs.get(m[2], ""))
        if raw and raw[8:10] != b"{\0":  # the JSON form (Basic Title) honours definition.json
            layers.append((m, body, raw))
    if not layers and not styles:
        return xml
    pick = {}  # control index -> layer index
    for i, default in enumerate(defaults):
        k = next((k for k, (_, _, raw) in enumerate(layers)
                  if k not in pick.values() and parse_source_text(raw)["text"] == default), None)
        if k is not None:
            pick[i] = k
    missing = sorted(i for i in {**wanted, **styles} if i not in pick)
    if missing:
        raise ValueError(f"text {missing}: no text layer in project.prgraphic holds its default text")
    edits = {}  # layer index -> (BinaryHash, base64 body)
    for i in {**wanted, **styles}:
        raw = layers[pick[i]][2]
        blob = (_restyled(raw, wanted.get(i), styles[i]) if i in styles else _set_flat_text(raw, wanted[i]))
        edits[pick[i]] = (_new_hash(len(blob)), base64.b64encode(blob).decode("ascii"))
    moved = {layers[k][0][2] for k in edits if layers[k][1]}  # carriers that lose their blob
    for k, (m, body, _) in enumerate(layers):
        if k not in edits and body is None and m[2] in moved:
            edits[k] = (m[2], blobs[m[2]])  # the empty twin carries the original itself now
    out, last = [], 0
    for k in sorted(edits):
        m, (hash_, body) = layers[k][0], edits[k]
        out += [xml[last:m.start(2)], f'{hash_}">{body}\n\t\t</StartKeyframeValue>']
        last = m.end()
    return "".join(out) + xml[last:]


def _rewrite_prgraphic(data: bytes, wanted: dict[int, str], defaults: list[str], styles: dict[int, dict]) -> bytes:
    """`_rewrite_prproj` on the gzipped .prproj inside a .prgraphic zip; other members kept.
    Returns `data` itself when no text changed (Basic Title's JSON-form layers)."""
    out, changed = io.BytesIO(), False
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            member = src.read(info)
            if info.filename.lower().endswith(".prproj"):
                packed = member[:2] == b"\x1f\x8b"
                xml = (gzip.decompress(member) if packed else member).decode("utf-8")
                new = _rewrite_prproj(xml, wanted, defaults, styles)
                if new != xml:
                    changed = True
                    member = gzip.compress(new.encode("utf-8")) if packed else new.encode("utf-8")
            dst.writestr(info, member)
    return out.getvalue() if changed else data


def bake(template: str | Path, texts: dict[str, str], styles: dict[str, dict] | None = None) -> Path:
    """Copy `template` with each text set and each style change made (`text_document.restyle`;
    Premiere-made templates only). Keys are a text's name or its index as a string.
    Returns the new .mogrt path. Raises ValueError naming the template's texts on a bad key."""
    template = Path(template)
    controls = text_controls(template)
    by_key = {**{c["name"]: c["index"] for c in controls}, **{str(c["index"]): c["index"] for c in controls}}
    styles = styles or {}
    unknown = [k for k in {**texts, **styles} if k not in by_key]
    if unknown or not (texts or styles):
        known = ", ".join(f'{c["index"]} "{c["name"]}"' for c in controls) or "none"
        raise ValueError(f"unknown text {unknown} for {template.name}; its texts are: {known}")
    wanted = {by_key[k]: v for k, v in texts.items()}
    restyle = {by_key[k]: v for k, v in styles.items()}
    defaults = [c["text"] for c in controls]

    bake_dir = Path(tempfile.gettempdir()) / "cutdeck-mogrt"
    bake_dir.mkdir(exist_ok=True)
    for old in bake_dir.glob("*.mogrt"):
        try:
            if time.time() - old.stat().st_mtime > MAX_AGE_S:
                old.unlink(missing_ok=True)
        except FileNotFoundError:  # another bake removed it first
            pass
    out = bake_dir / f"{template.stem}-{uuid.uuid4().hex[:8]}.mogrt"
    if restyle:
        with zipfile.ZipFile(template) as z:
            if not any(n.lower().endswith(".prgraphic") for n in z.namelist()):
                raise ValueError(f"styles: {template.name} has no text layer Premiere made (no project.prgraphic)")
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
            elif info.filename.lower().endswith(".prgraphic"):
                data = _rewrite_prgraphic(data, wanted, defaults, restyle)
            dst.writestr(info, data)
    return out
