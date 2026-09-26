"""prproj_reader.py — read-only summary of a saved Premiere project (.prproj).

A .prproj is gzip-compressed XML: a flat list of objects that point at each other by
``ObjectID``/``ObjectRef`` (numeric) or ``ObjectUID``/``ObjectURef`` (GUID). The format is
undocumented; every path walked here was mapped against real projects on 2026-09-25
(a 651-clip audio project and a small video project with effects). Anything not seen in a
real file is left out rather than guessed.

This module only reads. It never writes a project.

    python -m cutdeck.prproj_reader project.prproj [--sequence NAME]
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import struct
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

from cutdeck.xml_sequence import PPRO_TICKS_PER_SECOND


def load_root(path: str | Path) -> ET.Element:
    data = Path(path).read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return ET.fromstring(data)


class _Objects:
    """Index of top-level objects by ObjectID / ObjectUID."""

    def __init__(self, root: ET.Element):
        self.by_id: dict[str, ET.Element] = {}
        for el in root:
            key = el.get("ObjectID") or el.get("ObjectUID")
            if key:
                self.by_id[key] = el
        # Premiere writes an identical binary once; later copies are empty, keyed by BinaryHash.
        self.blobs: dict[str, str] = {
            el.get("BinaryHash"): el.text
            for el in root.iter("StartKeyframeValue") if el.text and el.text.strip()
        }

    def ref(self, el: ET.Element | None) -> ET.Element | None:
        """Follow an element's ObjectRef/ObjectURef to its object."""
        if el is None:
            return None
        key = el.get("ObjectRef") or el.get("ObjectURef")
        return self.by_id.get(key) if key else None


def _text(el: ET.Element | None, path: str) -> str | None:
    found = el.find(path) if el is not None else None
    return found.text if found is not None else None


def _seconds(ticks: str | int | None) -> float | None:
    return None if ticks is None else int(ticks) / PPRO_TICKS_PER_SECOND


def _bool(value: str | None) -> bool:
    # Premiere 26 omits a flag at its default (false); older saves write it out.
    return value == "true"


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def _fb_table(b: bytes, pos: int) -> dict[int, int]:
    """FlatBuffer table at ``pos`` -> {field index: absolute position of the field}."""
    vt = pos - struct.unpack_from("<i", b, pos)[0]
    size = struct.unpack_from("<H", b, vt)[0]
    fields = {}
    for k in range((size - 4) // 2):
        off = struct.unpack_from("<H", b, vt + 4 + 2 * k)[0]
        if off:
            fields[k] = pos + off
    return fields


def _fb_target(b: bytes, slot: int) -> int:
    return slot + _u32(b, slot)


def _fb_string(b: bytes, slot: int) -> str:
    t = _fb_target(b, slot)
    return b[t + 4:t + 4 + _u32(b, t)].decode("utf-8")


def _fb_vector(b: bytes, slot: int) -> list[int]:
    v = _fb_target(b, slot)
    return [v + 4 + 4 * i for i in range(_u32(b, v))]


# Premiere leaves a field out at its default; 100 is the default font size (T1/T6, 2026-09-25).
_DEFAULT_TEXT_SIZE = 100.0


def _fb_float(b: bytes, fields: dict[int, int], index: int, default: float) -> float:
    return struct.unpack_from("<f", b, fields[index])[0] if index in fields else default


def _fb_rgb(b: bytes, slot: int) -> list[int]:
    """A colour table: one byte per channel (f0 R, f1 G, f2 B); a channel left out is 255."""
    ch = _fb_table(b, _fb_target(b, slot))
    return [b[ch[i]] if i in ch else 255 for i in range(3)]


# Document f4 (omitted = left). 2 = centre was confirmed; 1 = right is inferred: it is the only other
# alignment that was set (left is the omitted default).
_ALIGNMENT = {0: "left", 1: "right", 2: "center"}


def parse_source_text(blob: bytes) -> dict:
    """Decode an ``ArbVideoComponentParam`` "Source Text" blob (a FlatBuffer, layout mapped
    from real Premiere 26 saves): root f0 -> document; document f0 = runs, f1 = font names;
    a run's f0 = its text, f1 = its style table. In the style table f0 is the index into the
    font names (omitted = 0), f1 the size (float, omitted = 100), f8 the tracking (float),
    f14 the faux-bold flag, f2 the fill colour, f4 the stroke colour (colour tables) with f5 its
    on flag and f6 the stroke width (float, default 4), f15 faux italic, f16 underline. Document
    f4 is the alignment, f6 the leading (float) and f11 the shadow flag.

    ``runs`` has one entry per style change; ``font`` and ``size`` are the first run's."""
    doc = _fb_table(blob, _fb_target(blob, _fb_table(blob, _fb_target(blob, 12))[0]))
    fonts = [_fb_string(blob, slot) for slot in _fb_vector(blob, doc[1])]
    runs = []
    for slot in _fb_vector(blob, doc[0]):
        run = _fb_table(blob, _fb_target(blob, slot))
        style = _fb_table(blob, _fb_target(blob, run[1]))
        runs.append({
            "text": _fb_string(blob, run[0]),
            "font": fonts[_u32(blob, style[0]) if 0 in style else 0],
            "size": _fb_float(blob, style, 1, _DEFAULT_TEXT_SIZE),
            "tracking": _fb_float(blob, style, 8, 0.0),
            "bold": 14 in style and blob[style[14]] == 1,
            "italic": 15 in style and blob[style[15]] == 1,
            "underline": 16 in style and blob[style[16]] == 1,
            "fill": _fb_rgb(blob, style[2]) if 2 in style else [255, 255, 255],
            # Style f4 keeps a stroke colour even when the stroke is off; f5 is the on flag.
            "stroke": _fb_rgb(blob, style[4]) if 4 in style and 5 in style and blob[style[5]] == 1 else None,
            "stroke_width": _fb_float(blob, style, 6, 4.0),
        })
    return {"text": "".join(r["text"] for r in runs), "font": runs[0]["font"],
            "size": runs[0]["size"], "leading": _fb_float(blob, doc, 6, 0.0),
            "alignment": _ALIGNMENT.get(_u32(blob, doc[4]) if 4 in doc else 0),
            "shadow": 11 in doc and blob[doc[11]] == 1, "runs": runs}


def _b64(text: str) -> bytes:
    return base64.b64decode(text)  # tolerates the stray non-base64 byte Premiere writes


def _text_of(objs: _Objects, comp: ET.Element) -> dict | None:
    """The Source Text of an ``AE.ADBE Text`` component, plus its keyframes if it has any."""
    for p in comp.findall("Component/Params/Param"):
        param = objs.ref(p)
        if param is None or param.tag != "ArbVideoComponentParam" or _text(param, "Name") != "Source Text":
            continue
        start = param.find("StartKeyframeValue")
        out = parse_source_text(_b64(start.text or objs.blobs[start.get("BinaryHash")]))
        stamps = [e.split(",", 1) for e in (_text(param, "Keyframes") or "").split(";") if e]
        if stamps:
            out["keyframes"] = [
                {"time": _seconds(t), "text": parse_source_text(_b64(v))["text"]} for t, v in stamps
            ]
        return out
    return None


# Param index -> name, per component, as saved by Premiere 26 (probe.prproj, Sequence 04).
# Motion matches the panel's PARAM_INDEX (uxp/cutdeck/transform/params.js); Text carries its
# own transform group. Position/Anchor are normalized (Position to the sequence frame, Anchor
# to the clip's source frame); the rest are plain numbers (percent / degrees).
_TRANSFORM_PARAMS = {
    "AE.ADBE Motion": {0: "position", 1: "scale", 2: "scale_width", 3: "uniform", 4: "rotation", 5: "anchor",
                       7: "crop_left", 8: "crop_top", 9: "crop_right", 10: "crop_bottom"},
    "AE.ADBE Opacity": {0: "opacity"},
    "AE.ADBE Text": {2: "position", 3: "scale", 4: "scale_width", 6: "rotation", 7: "opacity",
                     8: "anchor"},
}


def _key(raw: str) -> dict:
    """One keyframe record ``time,value,...`` -> {time, value}; a point value is ``x:y``."""
    time, value = raw.split(",")[:2]
    if value in ("true", "false"):
        return {"time": _seconds(time), "value": value == "true"}
    number = [float(v) for v in value.split(":")]
    return {"time": _seconds(time), "value": number if ":" in value else number[0]}


def _transform_params(objs: _Objects, comp: ET.Element, names: dict[int, str]) -> dict:
    """Named params of a component. A value lives in ``StartKeyframe`` (``CurrentValue`` is
    empty for points and rotation, and stale on a default Text clip: 92 beside a saved 100).
    Animated params also list ``Keyframes``, ``;``-separated."""
    out = {}
    for p in comp.findall("Component/Params/Param"):
        name = names.get(int(p.get("Index")))
        param = objs.ref(p)
        start = _text(param, "StartKeyframe")
        if name is None or not start:
            continue
        entry = {"value": _key(start)["value"]}
        keys = (_text(param, "Keyframes") or "").split(";")
        if any(keys):
            entry["keyframes"] = [_key(k) for k in keys if k]
        out[name] = entry
    return out


def _effects(objs: _Objects, track_item: ET.Element) -> list[dict]:
    chain = objs.ref(track_item.find("ClipTrackItem/ComponentOwner/Components"))
    out = []
    for comp_ref in chain.findall("ComponentChain/Components/Component") if chain is not None else []:
        comp = objs.ref(comp_ref)
        if comp is None:
            continue
        # Video filters hold <Component> directly; audio filters wrap it in <AudioComponent>.
        body = comp.find("Component")
        if body is None:
            body = comp.find("AudioComponent/Component")
        effect = {
            "name": _text(body, "DisplayName"),
            "match_name": _text(comp, "MatchName"),
            "bypass": _bool(_text(body, "Bypass")),
        }
        if effect["match_name"] == "AE.ADBE Text":
            effect["text"] = _text_of(objs, comp)
        if effect["match_name"] in _TRANSFORM_PARAMS:
            effect["params"] = _transform_params(objs, comp, _TRANSFORM_PARAMS[effect["match_name"]])
        out.append(effect)
    return out


def _frame(rect: str | None) -> list[int] | None:
    """``FrameRect`` text ``0,0,w,h`` -> [w, h]."""
    return [int(v) for v in rect.split(",")[2:4]] if rect else None


def _source(objs: _Objects, clip: ET.Element) -> dict:
    src = objs.ref(clip.find("Clip/Source"))
    if src is None:
        return {}
    media = objs.ref(src.find("MediaSource/Media"))
    if media is not None:
        out = {"media_path": _text(media, "ActualMediaFilePath") or _text(media, "FilePath")}
        # Anchor Point is normalized to this frame, not the sequence's (probe.prproj).
        frame = _frame(_text(objs.ref(media.find("VideoStream")), "FrameRect"))
        if frame:
            out["source_frame"] = frame
        return out
    nested = objs.ref(src.find("SequenceSource/Sequence"))
    if nested is not None:
        return {"nested_sequence": _text(nested, "Name")}
    return {}


def _track_item(objs: _Objects, item: ET.Element) -> dict:
    ti = item.find("ClipTrackItem/TrackItem")
    sub = objs.ref(item.find("ClipTrackItem/SubClip"))
    clip = objs.ref(sub.find("Clip")) if sub is not None else None
    out = {
        "name": _text(sub, "Name"),
        # Premiere 26 omits <Start> for a clip at 0.
        "start": _seconds(_text(ti, "Start") or 0),
        "end": _seconds(_text(ti, "End")),
        "source_in": _seconds(_text(clip, "Clip/InPoint") or 0),
        "source_out": _seconds(_text(clip, "Clip/OutPoint")),
        # Clip > Enable unticked is saved as the clip's own IsMuted (proven, probe.prproj).
        "disabled": _bool(_text(item, "ClipTrackItem/IsMuted")),
    }
    if clip is not None:
        out.update(_source(objs, clip))
    out["effects"] = _effects(objs, item)
    for effect in out["effects"]:
        # Source Text keyframe times are source time: seconds into an untrimmed clip = time - source_in.
        for key in (effect.get("text") or {}).get("keyframes", []):
            key["clip_time"] = key["time"] - out["source_in"]
        for param in effect.get("params", {}).values():
            for key in param.get("keyframes", []):
                key["clip_time"] = key["time"] - out["source_in"]
    return out


def _fader_muted(objs: _Objects, track: ET.Element) -> bool:
    """An audio track's M button is saved as the ``Mute`` param of its AudioFader
    component, not as the track's IsMuted (proven, probe.prproj, Premiere 26)."""
    chain = objs.ref(track.find("AudioTrack/ComponentOwner/Components"))
    for comp_ref in chain.findall("ComponentChain/Components/Component") if chain is not None else []:
        comp = objs.ref(comp_ref)
        if comp is None or comp.tag != "AudioFader":
            continue
        for p in comp.findall("AudioComponent/Component/Params/Param"):
            param = objs.ref(p)
            if _text(param, "Name") == "Mute" and _bool(_text(param, "CurrentValue")):
                return True
    return False


def _track(objs: _Objects, track: ET.Element) -> dict:
    t = track.find("ClipTrack/Track")
    items = [objs.ref(r) for r in track.findall("ClipTrack/ClipItems/TrackItems/TrackItem")]
    return {
        "index": int(_text(t, "Index") or 0),
        "muted": _bool(_text(t, "IsMuted")) or _fader_muted(objs, track),
        "locked": _bool(_text(t, "IsLocked")),
        "clips": [_track_item(objs, i) for i in items if i is not None],
    }


def _markers(objs: _Objects, owner: ET.Element) -> list[dict]:
    container = objs.ref(owner.find("MarkerOwner/Markers"))
    out = []
    for entry in container.findall("Markers/Marker") if container is not None else []:
        marker = objs.ref(entry.find("Second"))
        raw = _text(marker, "DVAMarker")
        if not raw:
            continue
        m = json.loads(raw).get("DVAMarker", {})
        out.append({
            "time": _seconds(m.get("mStartTime", {}).get("ticks")),
            "type": m.get("mType"),
            "name": m.get("mName"),
            "comment": m.get("mComment"),
        })
    return sorted(out, key=lambda m: m["time"] or 0)


_GROUP_KIND = {"VideoTrackGroup": "video", "AudioTrackGroup": "audio"}


def _sequence(objs: _Objects, seq: ET.Element) -> dict:
    out: dict = {"name": _text(seq, "Name"), "video_tracks": [], "audio_tracks": []}
    for group_ref in seq.findall("TrackGroups/TrackGroup/Second"):
        group = objs.ref(group_ref)
        kind = _GROUP_KIND.get(group.tag) if group is not None else None
        if kind is None:
            continue
        tracks = [objs.ref(t) for t in group.findall("TrackGroup/Tracks/Track")]
        out[f"{kind}_tracks"] = [_track(objs, t) for t in tracks if t is not None]
        if kind == "video":
            out["frame"] = _frame(_text(group, "FrameRect"))
    out["markers"] = _markers(objs, seq)
    return out


def read_project(path: str | Path) -> dict:
    root = load_root(path)
    objs = _Objects(root)
    sequences = [_sequence(objs, el) for el in root if el.tag == "Sequence"]
    return {"path": str(path), "sequences": sequences}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Print a read-only JSON summary of a .prproj.")
    p.add_argument("project")
    p.add_argument("--sequence", help="only the sequence with this name")
    args = p.parse_args(argv)
    summary = read_project(args.project)
    if args.sequence:
        summary["sequences"] = [s for s in summary["sequences"] if s["name"] == args.sequence]
    sys.stdout.reconfigure(encoding="utf-8")
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
