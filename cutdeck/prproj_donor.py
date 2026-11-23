"""prproj_donor.py — write a donor copy of a saved .prproj for ``import_sequences``.

The donor keeps one sequence's clips, effects and masks as Premiere saved them, gives that
sequence a fresh GUID and a new name (so it never collides with what the open project already
has), can change one static Motion value on one clip, and can copy one effect (a Lumetri, a
blur with its mask) from a clip in the same file onto a clip of that sequence. Everything is
patched as text on the decompressed XML (the value exactly once; the name and GUID wherever they
occur; a copied effect appended under fresh ObjectIDs), so the rest of the file stays byte for
byte what Premiere wrote. The reader's object index (``prproj_reader``)
only finds what to patch. Proven live: docs/PREMIERE_FACTS.md, ``Project.importSequences``.

    python -m cutdeck.prproj_donor SRC.prproj DST.prproj --sequence NAME --name NEW
        [--track 1 --clip 1 --param scale --value 137.25]
        [--track 1 --clip 1 --effect "AE.ADBE Lumetri" --from-sequence S --from-track 4 --from-clip 1]
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import uuid
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from cutdeck.prproj_reader import _TRANSFORM_PARAMS, _Objects

_MOTION = {name: index for index, name in _TRANSFORM_PARAMS["AE.ADBE Motion"].items()}
_NUMERIC = {"scale", "scale_width", "rotation", "crop_left", "crop_top", "crop_right", "crop_bottom"}


def _replace_once(xml: str, old: str, new: str, what: str) -> str:
    count = xml.count(old)
    if count != 1:
        raise ValueError(f"expected exactly one {what}, found {count}")
    return xml.replace(old, new)


def _video_clip(objs: _Objects, seq: ET.Element, track: int, clip: int) -> ET.Element:
    """The ``clip``-th clip (1-based) on video ``track`` (1-based) of ``seq``."""
    for group_ref in seq.findall("TrackGroups/TrackGroup/Second"):
        group = objs.ref(group_ref)
        if group is None or group.tag != "VideoTrackGroup":
            continue
        tracks = [objs.ref(t) for t in group.findall("TrackGroup/Tracks/Track")]
        if track > len(tracks):
            break
        items = [objs.ref(r) for r in tracks[track - 1].findall("ClipTrack/ClipItems/TrackItems/TrackItem")]
        if clip > len(items):
            break
        return items[clip - 1]
    raise ValueError(f"no clip {clip} on V{track}")


def _chain(objs: _Objects, item: ET.Element) -> ET.Element:
    return objs.ref(item.find("ClipTrackItem/ComponentOwner/Components"))


def _motion_param_id(objs: _Objects, seq: ET.Element, track: int, clip: int, param: str) -> str:
    """ObjectID of the Motion ``param`` of the ``clip``-th clip (1-based) on video ``track``."""
    for comp_ref in _chain(objs, _video_clip(objs, seq, track, clip)).findall("ComponentChain/Components/Component"):
        comp = objs.ref(comp_ref)
        if comp is not None and comp.findtext("MatchName") == "AE.ADBE Motion":
            for p in comp.findall("Component/Params/Param"):
                if int(p.get("Index")) == _MOTION[param]:
                    return p.get("ObjectRef")
    raise ValueError(f"no Motion {param} on V{track} clip {clip}")


def _object_text(xml: str, el: ET.Element) -> str:
    """The raw text of top-level object ``el``, exactly as saved."""
    tag, oid = el.tag, el.get("ObjectID")
    found = re.findall(rf'<{tag} ObjectID="{oid}"(?:[^>]*/>|[^>]*>[\s\S]*?</{tag}>)', xml)
    if len(found) != 1:
        raise ValueError(f"expected one <{tag} ObjectID={oid}>, found {len(found)}")
    return found[0]


def _graft(xml: str, objs: _Objects, source: ET.Element, effect: str, target: ET.Element) -> str:
    """Copy the ``effect`` component of clip ``source`` (its params, masks and every object they
    reach, under fresh ObjectIDs) onto the end of clip ``target``'s chain. Same file only: an
    identical binary is saved once (BinaryHash), so copies may point at the first one."""
    comps = [objs.ref(r) for r in _chain(objs, source).findall("ComponentChain/Components/Component")]
    comps = [c for c in comps if c is not None and c.findtext("MatchName") == effect]
    if len(comps) != 1:
        raise ValueError(f"expected one {effect} on the source clip, found {len(comps)}")
    order, todo = [], [comps[0]]
    while todo:
        el = todo.pop()
        if el.get("ObjectID") is None:
            raise ValueError(f"{effect} reaches <{el.tag}> by GUID; only ObjectID objects can be copied")
        if el in order:
            continue
        order.append(el)
        for d in el.iter():
            if d.get("ObjectURef"):
                raise ValueError(f"{effect} reaches an object by GUID; only ObjectID objects can be copied")
            if d.get("ObjectRef"):
                todo.append(objs.by_id[d.get("ObjectRef")])
    next_id = max(int(k) for k in objs.by_id if k.isdigit()) + 1
    new_ids = {el.get("ObjectID"): str(next_id + i) for i, el in enumerate(order)}
    swap = lambda m: f'{m.group(1)}="{new_ids.get(m.group(2), m.group(2))}"'
    copies = [re.sub(r'(ObjectID|ObjectRef)="(\d+)"', swap, _object_text(xml, el)) for el in order]

    chain = _chain(objs, target)
    used = [int(t) for t in [chain.findtext("DefaultMotionComponentID"), chain.findtext("DefaultOpacityComponentID")] if t]
    present = chain.findall("ComponentChain/Components/Component")
    used += [int(objs.ref(r).findtext("Component/ID")) for r in present]
    copies[0] = _replace_once(copies[0], f"<ID>{comps[0].findtext('Component/ID')}</ID>",
                              f"<ID>{max(used, default=0) + 1}</ID>", "component ID")
    entry = f'<Component Index="{len(present)}" ObjectRef="{new_ids[comps[0].get("ObjectID")]}"/>'
    body = _object_text(xml, chain)
    if present:
        patched = _replace_once(body, "</Components>", f"\t{entry}\n\t\t\t</Components>", "</Components>")
    else:
        patched = _replace_once(body, "</ComponentChain>", f'\t<Components Version="1">\n\t\t\t\t{entry}\n'
                                "\t\t\t</Components>\n\t\t</ComponentChain>", "</ComponentChain>")
    xml = _replace_once(xml, body, patched, f"chain object {chain.get('ObjectID')}")
    return _replace_once(xml, "</PremiereData>", "".join(f"\t{c}\n" for c in copies) + "</PremiereData>", "</PremiereData>")


def write_donor(src: str | Path, dst: str | Path, *, sequence: str, name: str,
                track: int | None = None, clip: int | None = None,
                param: str | None = None, value: float | None = None, effect: str | None = None,
                from_sequence: str | None = None, from_track: int | None = None,
                from_clip: int | None = None) -> dict:
    """Write ``dst`` and return ``{"sequence_id", "name"}`` for ``import_sequences``. With
    ``effect`` (a match name), clip ``from_clip`` on V``from_track`` of ``from_sequence`` (default:
    ``sequence``) gives its copy of that effect, masks included, to V``track`` clip ``clip``."""
    xml = gzip.decompress(Path(src).read_bytes()).decode("utf-8")
    root = ET.fromstring(xml)
    objs = _Objects(root)
    matches = [el for el in root if el.tag == "Sequence" and el.findtext("Name") == sequence]
    if len(matches) != 1:
        raise ValueError(f"expected one sequence named {sequence!r}, found {len(matches)}")
    seq = matches[0]
    old_id = seq.get("ObjectUID")

    if param is not None:
        if param not in _NUMERIC or not (isinstance(track, int) and track >= 1 and isinstance(clip, int) and clip >= 1) or value is None:
            raise ValueError(f"param must be one of {sorted(_NUMERIC)}, with track and clip from 1, and a value")
        param_id = _motion_param_id(objs, seq, track, clip, param)
        if objs.by_id[param_id].findtext("Keyframes"):
            raise ValueError(f"Motion {param} on V{track} clip {clip} is keyframed; only a static value can be patched")
        start = objs.by_id[param_id].findtext("StartKeyframe")
        fields = start.split(",")
        fields[1] = repr(float(value))
        body = re.search(rf'<VideoComponentParam ObjectID="{param_id}"[\s\S]*?</VideoComponentParam>', xml).group(0)
        patched = _replace_once(body, f"<StartKeyframe>{start}</StartKeyframe>",
                                f"<StartKeyframe>{','.join(fields)}</StartKeyframe>", "StartKeyframe")
        xml = _replace_once(xml, body, patched, f"Motion param object {param_id}")

    if effect is not None:
        if not all(isinstance(n, int) and n >= 1 for n in (track, clip, from_track, from_clip)):
            raise ValueError("effect needs track, clip, from_track and from_clip, each from 1")
        sources = [el for el in root if el.tag == "Sequence" and el.findtext("Name") == (from_sequence or sequence)]
        if len(sources) != 1:
            raise ValueError(f"expected one sequence named {from_sequence or sequence!r}, found {len(sources)}")
        xml = _graft(xml, objs, _video_clip(objs, sources[0], from_track, from_clip), effect,
                     _video_clip(objs, seq, track, clip))

    # The sequence's own <Name> and its project item's <Name> both carry the name.
    old_tag, new_tag = f"<Name>{escape(sequence)}</Name>", f"<Name>{escape(name)}</Name>"
    if old_tag not in xml:
        raise ValueError(f"no {old_tag} to rename")
    xml = xml.replace(old_tag, new_tag)
    new_id = str(uuid.uuid4())
    xml = xml.replace(old_id, new_id)

    Path(dst).write_bytes(gzip.compress(xml.encode("utf-8")))
    return {"sequence_id": new_id, "name": name}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Write a donor .prproj for import_sequences.")
    p.add_argument("src")
    p.add_argument("dst")
    p.add_argument("--sequence", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--track", type=int)
    p.add_argument("--clip", type=int)
    p.add_argument("--param")
    p.add_argument("--value", type=float)
    p.add_argument("--effect")
    p.add_argument("--from-sequence")
    p.add_argument("--from-track", type=int)
    p.add_argument("--from-clip", type=int)
    a = p.parse_args(argv)
    print(json.dumps(write_donor(a.src, a.dst, sequence=a.sequence, name=a.name, track=a.track,
                                 clip=a.clip, param=a.param, value=a.value, effect=a.effect,
                                 from_sequence=a.from_sequence, from_track=a.from_track,
                                 from_clip=a.from_clip)))


if __name__ == "__main__":
    main()
