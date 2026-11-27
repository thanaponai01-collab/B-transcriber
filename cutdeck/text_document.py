"""Read and write a Premiere Graphic text layer's "Source Text" blob (the FlatBuffer form).

Premiere 26/27 keeps every style of a text layer (font, size, fill, strokes, shadows, background,
alignment, ...) in the layer's `ArbVideoComponentParam` "Source Text" value: a u64 length
(= blob size - 12), the tag 0x11223344, then a FlatBuffer whose root f0 is the document.
UXP reads it as null and cannot write it (PREMIERE_FACTS "MogrtText write"), so CutDeck reads it
from a saved .prproj and writes it into a template copy before Premiere inserts it.

The layout below was mapped live on Premiere 27.0.0 (2026-11-27): one Properties-panel control
changed, the project saved, the blob diffed (PREMIERE_FACTS "Source Text field map").
`decode` refuses a slot that is not in SCHEMA, so nothing unmapped is ever re-encoded by guess.
"""
from __future__ import annotations

import re
import struct

# Field kinds: scalars (u8 = bool/byte, u32, f32), "str", "strs" (vector of strings), a table
# name (a nested table), or [table name] (a vector of tables).
COLOUR = {0: ("r", "u8"), 1: ("g", "u8"), 2: ("b", "u8")}  # an omitted channel is 255
STOP = {0: ("colour", "Colour"), 1: ("location", "f32"), 2: ("midpoint", "f32")}
GRADIENT = {0: ("type", "u32"), 1: ("colour_stops", ["Stop"]), 2: ("opacity_stops", ["Stop"])}
STROKE = {0: ("colour", "Colour"), 1: ("on", "u8"), 2: ("width", "f32"), 4: ("gradient", "Gradient"),
          5: ("type", "u32")}
SHADOW = {0: ("colour", "Colour"), 1: ("on", "u8"), 2: ("opacity", "f32"), 3: ("angle", "f32"),
          4: ("distance", "f32"), 5: ("size", "f32"), 6: ("blur", "f32"), 8: ("gradient", "Gradient")}
STYLE = {
    0: ("font", "u32"),              # index into the document's fonts
    1: ("size", "f32"),              # omitted = 100
    2: ("fill", "Colour"),
    3: ("fill_on", "u8"),            # omitted = on
    4: ("stroke", "Colour"),
    5: ("stroke_on", "u8"),
    6: ("stroke_width", "f32"),
    8: ("tracking", "f32"),
    9: ("tsume", "f32"),             # the panel's percent / 100
    10: ("baseline_shift", "f32"),
    12: ("caps", "u32"),             # 1 small caps, 2 all caps
    13: ("baseline", "u32"),         # 1 superscript, 2 subscript
    14: ("bold", "u8"),              # faux bold
    15: ("italic", "u8"),            # faux italic
    16: ("underline", "u8"),
    17: ("strokes", ["Stroke"]),     # strokes added with the panel's + after the first
    21: ("fill_gradient", "Gradient"),
    23: ("stroke_gradient", "Gradient"),
    24: ("stroke_type", "u32"),      # 0 centre, 1 inner, 2 outer
}
RUN = {0: ("text", "str"), 1: ("style", "Style")}
DOCUMENT = {
    0: ("runs", ["Run"]),
    1: ("fonts", "strs"),            # PostScript names
    2: ("box_width", "f32"),         # paragraph (area) text only
    3: ("box_height", "f32"),
    4: ("alignment", "u32"),         # 0 left, 1 right, 2 centre
    5: ("vertical_alignment", "u32"),  # 0 top, 1 centre, 2 bottom
    6: ("leading", "f32"),
    7: ("tab_width", "f32"),         # omitted = 400
    8: ("default_run", "Run"),       # seen in some saves; meaning not pinned
    10: ("shadow", "Colour"),
    11: ("shadow_on", "u8"),
    12: ("shadow_opacity", "f32"),   # omitted = 75
    13: ("shadow_angle", "f32"),     # omitted = 135
    14: ("shadow_distance", "f32"),  # omitted = 7
    15: ("shadow_size", "f32"),
    16: ("shadow_blur", "f32"),
    17: ("background", "Colour"),    # omitted = 3F3F3F in the panel
    18: ("background_on", "u8"),
    19: ("background_opacity", "f32"),  # omitted = 75
    20: ("background_size", "f32"),
    21: ("mask_with_text", "u8"),
    22: ("mask_invert", "u8"),
    26: ("f26", "u8"),               # unnamed: 1 in every save seen
    27: ("rtl", "u8"),
    30: ("f30", "u32"),              # unnamed: 2 appeared with an outer stroke
    32: ("f32_entries", ["Entry"]),  # e.g. {"key": "AnimationType"}; only key seen
    33: ("f33", "F33"),              # unnamed table
    34: ("background_corner", "f32"),
    37: ("shadows", ["Shadow"]),     # shadows added with the panel's + after the first
    40: ("f40_gradient", "Gradient"),  # a gradient, owner not pinned (likely the background)
    43: ("f43", "u8"),               # unnamed
    44: ("f44", "u8"),               # unnamed: 1 in every save seen
}
ENTRY = {0: ("key", "str")}
F33 = {2: ("f2", "f32"), 7: ("f7", "f32")}
ROOT = {0: ("document", "Document")}
SCHEMA = {"Root": ROOT, "Document": DOCUMENT, "Run": RUN, "Style": STYLE, "Colour": COLOUR,
          "Stop": STOP, "Gradient": GRADIENT, "Stroke": STROKE, "Shadow": SHADOW, "Entry": ENTRY, "F33": F33}
_SCALAR = {"u8": "<B", "u32": "<I", "f32": "<f"}
TAG = 0x11223344


class UnmappedField(ValueError):
    """A slot the schema doesn't name: refuse rather than re-encode a guess."""


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def _string(b: bytes, at: int) -> str:
    return b[at + 4:at + 4 + _u32(b, at)].decode("utf-8")


def _table(b: bytes, pos: int, kind: str, path: str) -> dict:
    schema = SCHEMA[kind]
    vt = pos - struct.unpack_from("<i", b, pos)[0]
    out = {}
    for slot in range((struct.unpack_from("<H", b, vt)[0] - 4) // 2):
        off = struct.unpack_from("<H", b, vt + 4 + 2 * slot)[0]
        if not off:
            continue
        if slot not in schema:
            raise UnmappedField(f"{path}{kind}.f{slot} is not mapped")
        name, ftype = schema[slot]
        at = pos + off
        if isinstance(ftype, list):
            vec = at + _u32(b, at)
            out[name] = [_table(b, e + _u32(b, e), ftype[0], f"{path}{name}[{i}].")
                         for i, e in enumerate(vec + 4 + 4 * k for k in range(_u32(b, vec)))]
        elif ftype == "str":
            out[name] = _string(b, at + _u32(b, at))
        elif ftype == "strs":
            vec = at + _u32(b, at)
            out[name] = [_string(b, e + _u32(b, e)) for e in (vec + 4 + 4 * k for k in range(_u32(b, vec)))]
        elif ftype in ("u8", "u32", "f32"):
            out[name] = struct.unpack_from(_SCALAR[ftype], b, at)[0]
        else:
            out[name] = _table(b, at + _u32(b, at), ftype, f"{path}{name}.")
    return out


def decode(blob: bytes) -> dict:
    """The document of a FlatBuffer Source Text blob, as nested dicts keyed by SCHEMA names.
    A field Premiere left at its default is absent. Raises UnmappedField on an unknown slot."""
    if struct.unpack_from("<Q", blob, 0)[0] != len(blob) - 12 or _u32(blob, 8) != TAG:
        raise ValueError("not a FlatBuffer Source Text blob")
    buf = blob[12:]
    try:
        return _table(buf, _u32(buf, 0), "Root", "")["document"]
    except (struct.error, UnicodeDecodeError, RecursionError) as e:
        # seen on 212 of 1813 saved blobs: a slot typed differently there
        raise UnmappedField(f"Source Text layout not mapped ({e.__class__.__name__})") from None


class _Writer:
    """Forward FlatBuffer writer: a parent is laid out before its children, whose offsets are
    patched in once they land (a uoffset always points forward)."""

    def __init__(self):
        self.b = bytearray(b"\0\0\0\0")  # root uoffset, patched last
        self.todo = []                    # (slot address, kind, value)

    def _align(self, n: int):
        self.b += b"\0" * (-len(self.b) % n)

    def _patch(self, slot: int, target: int):
        struct.pack_into("<I", self.b, slot, target - slot)

    def _table(self, kind: str, value: dict) -> int:
        schema = {name: (slot, ftype) for slot, (name, ftype) in SCHEMA[kind].items()}
        unknown = set(value) - set(schema)
        if unknown:
            raise UnmappedField(f"{kind} has no field {sorted(unknown)}")
        fields = sorted(((schema[n][0], schema[n][1], v) for n, v in value.items()),
                        key=lambda f: 0 if f[1] != "u8" else 1)  # 4-byte fields first
        layout, size = [], 4
        for slot, ftype, v in fields:
            width = 1 if ftype == "u8" else 4
            size += -size % width
            layout.append((slot, ftype, v, size))
            size += width
        size += -size % 4
        nslots = max([s for s, *_ in layout], default=-1) + 1
        self._align(2)
        vt = len(self.b)
        offsets = [0] * nslots
        for slot, _, _, at in layout:
            offsets[slot] = at
        self.b += struct.pack(f"<HH{nslots}H", 4 + 2 * nslots, size, *offsets)
        self._align(4)
        pos = len(self.b)
        self.b += b"\0" * size
        struct.pack_into("<i", self.b, pos, pos - vt)
        for slot, ftype, v, at in layout:
            if ftype in ("u8", "u32", "f32"):
                struct.pack_into(_SCALAR[ftype], self.b, pos + at, v)
            else:
                self.todo.append((pos + at, ftype, v))
        return pos

    def _string(self, s: str) -> int:
        self._align(4)
        pos = len(self.b)
        data = s.encode("utf-8")
        self.b += struct.pack("<I", len(data)) + data + b"\0"
        return pos

    def _child(self, slot: int, ftype, v):
        if isinstance(ftype, list) or ftype == "strs":
            self._align(4)
            vec = len(self.b)
            self.b += struct.pack("<I", len(v)) + b"\0" * (4 * len(v))
            self._patch(slot, vec)
            for k, item in enumerate(v):
                if ftype == "strs":
                    self._patch(vec + 4 + 4 * k, self._string(item))
                else:
                    self.todo.append((vec + 4 + 4 * k, ftype[0], item))
        elif ftype == "str":
            self._patch(slot, self._string(v))
        else:
            self._patch(slot, self._table(ftype, v))

    def build(self, document: dict) -> bytes:
        self._patch(0, self._table("Root", {"document": document}))
        while self.todo:
            slot, ftype, v = self.todo.pop(0)
            self._child(slot, ftype, v)
        self._align(4)
        return bytes(self.b)


def encode(document: dict) -> bytes:
    """A Source Text blob for `document` (the shape `decode` returns)."""
    buf = _Writer().build(document)
    return struct.pack("<QI", len(buf), TAG) + buf


# What `restyle` may change: fields mapped by a change in the Properties panel and a save.
# Style fields apply to every run; the rest to the whole text layer. Fonts, gradients, the extra
# strokes and shadows, box size and the unnamed slots are not offered.
STYLE_FIELDS = ("size", "fill", "fill_on", "stroke", "stroke_on", "stroke_width", "stroke_type", "tracking",
                "tsume", "baseline_shift", "caps", "baseline", "bold", "italic", "underline")
DOCUMENT_FIELDS = ("alignment", "vertical_alignment", "leading", "tab_width", "shadow", "shadow_on",
                   "shadow_opacity", "shadow_angle", "shadow_distance", "shadow_size", "shadow_blur",
                   "background", "background_on", "background_opacity", "background_size", "background_corner",
                   "mask_with_text", "mask_invert", "rtl")
NAMES = {  # enum fields: the panel's words for each stored value
    "alignment": {"left": 0, "right": 1, "centre": 2, "center": 2},
    "vertical_alignment": {"top": 0, "centre": 1, "center": 1, "bottom": 2},
    "stroke_type": {"centre": 0, "center": 0, "inner": 1, "outer": 2},
    "caps": {"normal": 0, "small": 1, "all": 2},
    "baseline": {"normal": 0, "superscript": 1, "subscript": 2},
}


def _value(name: str, ftype: str, v):
    if ftype == "Colour":
        if not (isinstance(v, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", v)):
            raise ValueError(f"{name} must be a colour as #RRGGBB, not {v!r}")
        return {"r": int(v[1:3], 16), "g": int(v[3:5], 16), "b": int(v[5:7], 16)}  # all three, always
    if name in NAMES:
        if v not in NAMES[name]:
            raise ValueError(f"{name} must be one of {', '.join(NAMES[name])}, not {v!r}")
        return NAMES[name][v]
    if ftype == "u8":
        if not isinstance(v, bool):
            raise ValueError(f"{name} must be true or false, not {v!r}")
        return int(v)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"{name} must be a number, not {v!r}")
    return float(v)


def restyle(document: dict, changes: dict) -> dict:
    """`document` (as `decode` returns it) with `changes` applied: STYLE_FIELDS to every run,
    DOCUMENT_FIELDS to the layer. Colours are "#RRGGBB", enums their NAMES, switches true/false."""
    unknown = [k for k in changes if k not in STYLE_FIELDS + DOCUMENT_FIELDS]
    if unknown:
        raise ValueError(f"unknown style {unknown}; styles are: {', '.join(STYLE_FIELDS + DOCUMENT_FIELDS)}")
    types = dict([*STYLE.values(), *DOCUMENT.values()])
    out = {**document, "runs": [{**r, "style": dict(r.get("style", {}))} for r in document.get("runs", [])]}
    for name, v in changes.items():
        value = _value(name, types[name], v)
        for target in ([r["style"] for r in out["runs"]] if name in STYLE_FIELDS else [out]):
            target[name] = dict(value) if isinstance(value, dict) else value
    return out
