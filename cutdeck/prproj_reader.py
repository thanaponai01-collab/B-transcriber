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
import gzip
import json
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
        out.append({
            "name": _text(body, "DisplayName"),
            "match_name": _text(comp, "MatchName"),
            "bypass": _bool(_text(body, "Bypass")),
        })
    return out


def _source(objs: _Objects, clip: ET.Element) -> dict:
    src = objs.ref(clip.find("Clip/Source"))
    if src is None:
        return {}
    media = objs.ref(src.find("MediaSource/Media"))
    if media is not None:
        return {"media_path": _text(media, "ActualMediaFilePath") or _text(media, "FilePath")}
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
