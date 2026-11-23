"""prproj_donor.py — write a donor copy of a saved .prproj for ``import_sequences``.

The donor keeps one sequence's clips, effects and masks as Premiere saved them, gives that
sequence a fresh GUID and a new name (so it never collides with what the open project already
has), and can change one static Motion value on one clip. Everything is patched as text on the
decompressed XML (the value exactly once; the name and GUID wherever they occur), so the rest of
the file stays byte for byte what Premiere wrote. The reader's object index (``prproj_reader``)
only finds what to patch. Proven live: docs/PREMIERE_FACTS.md, ``Project.importSequences``.

    python -m cutdeck.prproj_donor SRC.prproj DST.prproj --sequence NAME --name NEW
        [--track 1 --clip 1 --param scale --value 137.25]
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


def _motion_param_id(objs: _Objects, seq: ET.Element, track: int, clip: int, param: str) -> str:
    """ObjectID of the Motion ``param`` of the ``clip``-th clip (1-based) on video ``track``."""
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
        chain = objs.ref(items[clip - 1].find("ClipTrackItem/ComponentOwner/Components"))
        for comp_ref in chain.findall("ComponentChain/Components/Component"):
            comp = objs.ref(comp_ref)
            if comp is not None and comp.findtext("MatchName") == "AE.ADBE Motion":
                for p in comp.findall("Component/Params/Param"):
                    if int(p.get("Index")) == _MOTION[param]:
                        return p.get("ObjectRef")
    raise ValueError(f"no Motion {param} on V{track} clip {clip}")


def write_donor(src: str | Path, dst: str | Path, *, sequence: str, name: str,
                track: int | None = None, clip: int | None = None,
                param: str | None = None, value: float | None = None) -> dict:
    """Write ``dst`` and return ``{"sequence_id", "name"}`` for ``import_sequences``."""
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
    a = p.parse_args(argv)
    print(json.dumps(write_donor(a.src, a.dst, sequence=a.sequence, name=a.name, track=a.track,
                                 clip=a.clip, param=a.param, value=a.value)))


if __name__ == "__main__":
    main()
