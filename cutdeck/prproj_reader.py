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
import re
import struct
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

from cutdeck.sequence_timing import PPRO_TICKS_PER_SECOND


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


def _deref(b: bytes, slot: int) -> int:
    return slot + _u32(b, slot)


def _string(b: bytes, slot: int) -> str:
    t = _deref(b, slot)
    return b[t + 4:t + 4 + _u32(b, t)].decode("utf-8")


class _Table:
    """A FlatBuffer table. Premiere leaves any field out at its default, so a table has no
    indexing: every read says what an omitted field stands for."""

    def __init__(self, b: bytes, pos: int | None):
        self._b, self._fields = b, {}
        if pos is None:
            return
        vt = pos - struct.unpack_from("<i", b, pos)[0]
        for k in range((struct.unpack_from("<H", b, vt)[0] - 4) // 2):
            off = struct.unpack_from("<H", b, vt + 4 + 2 * k)[0]
            if off:
                self._fields[k] = pos + off

    def has(self, i: int) -> bool:
        return i in self._fields

    def _read(self, fmt: str, i: int, default):
        return struct.unpack_from(fmt, self._b, self._fields[i])[0] if i in self._fields else default

    def u32(self, i: int, default: int) -> int:
        return self._read("<I", i, default)

    def float(self, i: int, default: float) -> float:
        return self._read("<f", i, default)

    def flag(self, i: int) -> bool:
        return self._read("<B", i, 0) == 1

    def string(self, i: int) -> str:
        return _string(self._b, self._fields[i]) if i in self._fields else ""

    def table(self, i: int) -> _Table:
        return _Table(self._b, _deref(self._b, self._fields[i]) if i in self._fields else None)

    def _slots(self, i: int) -> list[int]:
        if i not in self._fields:
            return []
        v = _deref(self._b, self._fields[i])
        return [v + 4 + 4 * k for k in range(_u32(self._b, v))]

    def tables(self, i: int) -> list[_Table]:
        return [_Table(self._b, _deref(self._b, slot)) for slot in self._slots(i)]

    def strings(self, i: int) -> list[str]:
        return [_string(self._b, slot) for slot in self._slots(i)]


# Premiere leaves a field out at its default; 100 is the default font size (T1/T6, 2026-09-25).
_DEFAULT_TEXT_SIZE = 100.0


def _rgb(colour: _Table) -> list[int]:
    """A colour table: one byte per channel (f0 R, f1 G, f2 B); a channel left out is 255."""
    return [colour._read("<B", i, 255) for i in range(3)]


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

    ``runs`` has one entry per style change; ``font`` and ``size`` are the first run's. A layer
    with no text leaves out its runs and fonts: ``runs`` is empty and ``font`` None.

    Some layers (a third-party transition's, HKS 20261120) are UTF-16 JSON instead; see
    ``_parse_json_source_text``."""
    if blob[8:10] == b"{\x00":
        return _parse_json_source_text(blob)
    doc = _Table(blob, _deref(blob, 12)).table(0)
    fonts = doc.strings(1)
    runs = []
    for run in doc.tables(0):
        style = run.table(1)
        runs.append({
            "text": run.string(0),
            "font": fonts[style.u32(0, 0)],
            "size": style.float(1, _DEFAULT_TEXT_SIZE),
            "tracking": style.float(8, 0.0),
            "bold": style.flag(14),
            "italic": style.flag(15),
            "underline": style.flag(16),
            "fill": _rgb(style.table(2)),
            # Style f4 keeps a stroke colour even when the stroke is off; f5 is the on flag.
            "stroke": _rgb(style.table(4)) if style.has(4) and style.flag(5) else None,
            "stroke_width": style.float(6, 4.0),
        })
    first = runs[0] if runs else {"font": None, "size": _DEFAULT_TEXT_SIZE}
    return {"text": "".join(r["text"] for r in runs), "font": first["font"],
            "size": first["size"], "leading": doc.float(6, 0.0),
            "alignment": _ALIGNMENT.get(doc.u32(4, 0)), "shadow": doc.flag(11), "runs": runs}


def _first(style: dict, key: str, default):
    values = style.get(key, {}).get("mParamValues") or [[0, default]]
    return values[0][1]


def _parse_json_source_text(blob: bytes) -> dict:
    """The JSON form: a u64 byte length, then ``{"mTextParam": ...}`` in UTF-16-LE. Only
    the fields seen with their meaning are read; colours are left out because the saved
    samples (0x606060, 0xFFFFFF) don't show the channel order."""
    size = struct.unpack_from("<Q", blob, 0)[0]
    param = json.loads(blob[8:8 + size].decode("utf-16-le"))["mTextParam"]
    style = param["mStyleSheet"]
    run = {
        "text": style["mText"],
        "font": _first(style, "mFontName", None),
        "size": float(_first(style, "mFontSize", _DEFAULT_TEXT_SIZE)),
        "tracking": float(_first(style, "mTracking", 0.0)),
        "bold": _first(style, "mFauxBold", False),
        "italic": _first(style, "mFauxItalic", False),
    }
    return {"text": run["text"], "font": run["font"], "size": run["size"],
            "leading": float(param.get("mLeading", 0.0)),
            "alignment": _ALIGNMENT.get(param.get("mAlignment", 0)),
            "shadow": bool(param.get("mShadowVisible")), "runs": [run]}


def _b64(text: str) -> bytes:
    return base64.b64decode(text)  # tolerates the stray non-base64 byte Premiere writes


def _decode_source_text(encoded: str) -> dict:
    """``parse_source_text``, or ``{"text": None, "unreadable": why}`` for a layout not yet
    mapped, so one such layer doesn't stop the rest of the project being read."""
    try:
        return parse_source_text(_b64(encoded))
    except (struct.error, IndexError, KeyError, ValueError) as e:
        return {"text": None, "unreadable": f"{type(e).__name__}: {e}"}


def _text_of(objs: _Objects, comp: ET.Element) -> dict | None:
    """The Source Text of an ``AE.ADBE Text`` component, plus its keyframes if it has any."""
    for p in comp.findall("Component/Params/Param"):
        param = objs.ref(p)
        if param is None or param.tag != "ArbVideoComponentParam" or _text(param, "Name") != "Source Text":
            continue
        start = param.find("StartKeyframeValue")
        out = _decode_source_text(start.text or objs.blobs[start.get("BinaryHash")])
        stamps = [e.split(",", 1) for e in (_text(param, "Keyframes") or "").split(";") if e]
        if stamps:
            out["keyframes"] = [
                {"time": _seconds(t), **{k: v for k, v in _decode_source_text(raw).items() if k in ("text", "unreadable")}}
                for t, raw in stamps
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


def _named_params(objs: _Objects, body: ET.Element) -> dict:
    """Params of an audio component, keyed by their saved ``Name``; only those with a value."""
    out = {}
    for p in body.findall("Params/Param"):
        param = objs.ref(p)
        name, start = _text(param, "Name"), _text(param, "StartKeyframe")
        if name and start:
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
        elif body is not None and comp.find("AudioComponent") is not None and _named_params(objs, body):
            # Audio params carry their own <Name> (Volume: Mute, Level). Level is a linear gain:
            # dB = 20·log10(value) + 15 (the 22 BGM pieces of 20261120 read -33 / -24 / -12).
            effect["params"] = _named_params(objs, body)
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
    # Premiere's Frame Hold: the clip shows the one source frame at FrameHoldStart, which is not
    # always the in point. Only the value 4 occurs in the 11 HKS day projects (329 clips).
    if _text(clip, "FrameHold") not in (None, "0"):
        out["frame_hold"] = _seconds(_text(clip, "FrameHoldStart") or 0)
    # The clip's label colour: its Properties' asl.clip.label.name = "BE.Prefs.LabelColors.<n>"
    # (read from every HKS day's cuts, projects/hks/study/labels.md). UXP cannot read it live.
    label = clip.find(".//asl.clip.label.name") if clip is not None else None
    found = re.search(r"LabelColors\.(\d+)", label.text or "") if label is not None else None
    if found:
        out["label"] = int(found.group(1))
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


def _transition(item: ET.Element) -> dict:
    """A transition on a track (e.g. the Film Impact Glitch on a radio caption's head). Start/End are
    timeline seconds; incoming/outgoing say which side of the edit it touches (head only: incoming)."""
    tr = item.find("TransitionTrackItem")
    ti = tr.find("TrackItem")
    return {
        "name": _text(tr, "DisplayName"),
        "match_name": _text(tr, "MatchName"),
        "start": _seconds(_text(ti, "Start") or 0),
        "end": _seconds(_text(ti, "End")),
        "alignment": int(_text(tr, "Alignment") or 0),
        "outgoing": _bool(_text(tr, "HasOutgoingClip")),
        "incoming": _bool(_text(tr, "HasIncomingClip")),
    }


def _track(objs: _Objects, track: ET.Element) -> dict:
    t = track.find("ClipTrack/Track")
    items = [objs.ref(r) for r in track.findall("ClipTrack/ClipItems/TrackItems/TrackItem")]
    out = {
        "index": int(_text(t, "Index") or 0),
        "muted": _bool(_text(t, "IsMuted")) or _fader_muted(objs, track),
        "locked": _bool(_text(t, "IsLocked")),
        "clips": [_track_item(objs, i) for i in items if i is not None],
    }
    transitions = [objs.ref(r) for r in track.findall("ClipTrack/TransitionItems/TrackItems/TrackItem")]
    transitions = [_transition(i) for i in transitions if i is not None and i.find("TransitionTrackItem") is not None]
    if transitions:
        out["transitions"] = transitions
    return out


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
