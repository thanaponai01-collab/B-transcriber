"""Restyle a text layer already on the timeline the way Premiere does it: through a text style.

Premiere has no API to change a placed Graphic's text style (PREMIERE_FACTS, "UXP set_param on
layers"). What it does have is a text style project item (`.prtextstyle`), which the Properties
panel's Linked style dropdown applies to the selected layer. So a restyle reads the layer's Source
Text from the saved project, changes the asked fields (`text_document.restyle`), writes that as a
style file, and the UI route applies it.

A `.prtextstyle` is a small Premiere project: a root bin holding one `StyleProjectItem` whose
component is an `AE.ADBE Text` with the Source Text blob. The skeleton in `ui_templates/` was saved
by Premiere 26; only its two item UIDs, the style name and the blob change here.
"""
from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path

from cutdeck import text_document
from cutdeck.mogrt_text import _new_hash
from cutdeck.prproj_reader import _Objects, _text, load_root

SKELETON = Path(__file__).parent / "ui_templates" / "text_style.prtextstyle"
STYLE_UID = "00000000-0000-0000-0000-000000000001"  # the StyleProjectItem in the skeleton
ROOT_UID = "00000000-0000-0000-0000-000000000002"  # its root bin
_BLOB = re.compile(r'BinaryHash="[^"]+">[^<]+<')
_CLIP = re.compile(r"V(\d+)@(\d+)")


def write_style(document: dict, name: str, path: str | Path) -> Path:
    """Write `document` (`text_document.decode` shape, one run) as a style named `name` at `path`.
    Its text is "Aa", as in every style Premiere saves: a style carries the look, never the words."""
    if len(document["runs"]) != 1:
        raise ValueError(f"a style has one style run, not {len(document['runs'])}")
    document = {**document, "runs": [{**document["runs"][0], "text": "Aa"}]}
    xml = SKELETON.read_text(encoding="utf-8")
    blob = text_document.encode(document)
    body = base64.b64encode(blob).decode("ascii")
    xml, n = _BLOB.subn(lambda _: f'BinaryHash="{_new_hash(len(blob))}">{body}<', xml)
    if n != 1:
        raise RuntimeError(f"style skeleton holds {n} Source Text blobs, not 1")
    xml = xml.replace(STYLE_UID, str(uuid.uuid4())).replace(ROOT_UID, str(uuid.uuid4()))
    xml = xml.replace("<Name>CutDeck style</Name>", f"<Name>{_escape(name)}</Name>")
    path = Path(path)
    path.write_text(xml, encoding="utf-8")
    return path


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def layer_blob(prproj: str | Path, sequence: str, clip: str, layer: int) -> bytes:
    """The Source Text blob of text layer `layer` (0-based, in effect chain order, as Effect
    Controls lists the "Text (...)" rows) of clip `V<track>@<start ticks>` in a saved project."""
    found = _CLIP.fullmatch(clip)
    if not found:
        raise ValueError(f"clip {clip!r} is not V<track>@<start ticks>")
    track, start = int(found[1]) - 1, int(found[2])
    root = load_root(prproj)
    objs = _Objects(root)
    named = [s for s in root.iter("Sequence") if _text(s, "Name") == sequence]
    if len(named) != 1:
        raise ValueError(f"no sequence {sequence!r} in the saved project" if not named
                         else f"{len(named)} sequences are named {sequence!r}; rename one first")
    seq = named[0]
    item = _video_clip(objs, seq, track, start)
    if item is None:
        raise ValueError(f"no clip {clip} in {sequence!r}")
    params = list(_source_texts(objs, item))
    if not params:
        raise ValueError(f"clip {clip} has no text layer")
    if not 0 <= layer < len(params):
        raise ValueError(f"clip {clip} has {len(params)} text layers; layer {layer} is not one")
    param = params[layer]
    if (_text(param, "Keyframes") or "").strip(";"):
        raise ValueError(f"text layer {layer} of {clip} has keyframed Source Text; a style would flatten it")
    start_value = param.find("StartKeyframeValue")
    return base64.b64decode(start_value.text or objs.blobs[start_value.get("BinaryHash")])


def _video_clip(objs: _Objects, seq, track: int, start: int):
    for group_ref in seq.findall("TrackGroups/TrackGroup/Second"):
        group = objs.ref(group_ref)
        if group is None or group.tag != "VideoTrackGroup":
            continue
        tracks = [objs.ref(t) for t in group.findall("TrackGroup/Tracks/Track")]
        for t in tracks:
            if t is None or int(_text(t, "ClipTrack/Track/Index") or 0) != track:
                continue
            for ref in t.findall("ClipTrack/ClipItems/TrackItems/TrackItem"):
                item = objs.ref(ref)
                if item is not None and int(_text(item, "ClipTrackItem/TrackItem/Start") or 0) == start:
                    return item
    return None


def _source_texts(objs: _Objects, item):
    """Each text layer's Source Text param, in chain order."""
    chain = objs.ref(item.find("ClipTrackItem/ComponentOwner/Components"))
    for comp_ref in chain.findall("ComponentChain/Components/Component") if chain is not None else []:
        comp = objs.ref(comp_ref)
        if comp is None or _text(comp, "MatchName") != "AE.ADBE Text":
            continue
        for p in comp.findall("Component/Params/Param"):
            param = objs.ref(p)
            if param is not None and param.tag == "ArbVideoComponentParam" and _text(param, "Name") == "Source Text":
                yield param
                break


def restyled_layer(blob: bytes, changes: dict) -> dict:
    """The layer's document with `changes` applied; one style run only, since a style is one look."""
    try:
        doc = text_document.decode(blob)
    except text_document.UnmappedField as e:
        raise ValueError(f"can't restyle this layer: {e}") from None
    if len(doc["runs"]) != 1:
        raise ValueError(f"text layer has {len(doc['runs'])} style runs; a style would make them one")
    return text_document.restyle(doc, changes)


# What Premiere means by a field it leaves out of a saved blob (text_document's SCHEMA notes);
# any other number or switch left out is 0 / off, and a colour channel left out is 255.
OMITTED = {"size": 100.0, "fill_on": 1, "tab_width": 400.0, "shadow_opacity": 75.0, "shadow_angle": 135.0,
           "shadow_distance": 7.0, "background_opacity": 75.0}


def _field(doc: dict, name: str):
    where = doc["runs"][0]["style"] if name in text_document.STYLE_FIELDS else doc
    value = where.get(name)
    if isinstance(value, dict) or (value is None and name in ("fill", "stroke", "shadow", "background")):
        return tuple((value or {}).get(c, 255) for c in "rgb")
    return OMITTED.get(name, 0) if value is None else value


# Written by Premiere whenever it re-saves a layer it changed, with no look of their own (live
# 2026-11-27, restyle of a template-made layer): empty gradient tables, and the unnamed f44 = 1
# that every panel save carries.
REWRITE_NOISE = ("f44",)


def _canonical(value):
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items() if v != {} and k not in REWRITE_NOISE}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    return value


def mismatches(got: dict, want: dict, changes: dict) -> list[str]:
    """The fields where a layer read back from a saved project (`got`) is not the asked look (`want`,
    from `restyled_layer`): asked fields compared by meaning, every other field exactly, apart from
    what Premiere writes on any re-save (REWRITE_NOISE, empty tables)."""
    got, want = _canonical(got), _canonical(want)
    wrong = [n for n in changes if _field(got, n) != _field(want, n)]
    strip = lambda d: {**{k: v for k, v in d.items() if k not in changes and k != "runs"},  # noqa: E731
                       "runs": [{**r, "style": {k: v for k, v in r["style"].items() if k not in changes}} for r in d["runs"]]}
    a, b = strip(got), strip(want)
    wrong += sorted(k for k in set(a) | set(b) if k != "runs" and a.get(k) != b.get(k))
    if a["runs"] != b["runs"]:
        wrong.append("runs (text or other run styles)")
    return wrong
