"""prproj_donor: a donor copy changes exactly what it was asked to (issue #130)."""
import gzip
from pathlib import Path

import pytest

from cutdeck.prproj_donor import write_donor
from cutdeck.prproj_reader import read_project

SRC = Path(__file__).resolve().parent.parent / "test_projects" / "probe.prproj"
OLD_ID = "36af5782-02da-4b14-bc86-a877b412f4f1"  # "Sequence 04": Black Video with Motion on V2, V3
pytestmark = pytest.mark.skipif(not SRC.exists(), reason="probe.prproj is a committed fixture")


def _seq(path, name):
    return next(s for s in read_project(path)["sequences"] if s["name"] == name)


def _motion(seq, track):
    clip = seq["video_tracks"][track - 1]["clips"][0]
    return next(e for e in clip["effects"] if e["match_name"] == "AE.ADBE Motion")["params"]


def test_donor_changes_one_scale_the_name_and_the_guid_only(tmp_path):
    dst = tmp_path / "donor.prproj"
    out = write_donor(SRC, dst, sequence="Sequence 04", name="Donor & co", track=2, clip=1, param="scale", value=137.25)
    after, before = _seq(dst, "Donor & co"), _seq(SRC, "Sequence 04")
    assert _motion(after, 2)["scale"] == {"value": 137.25}
    _motion(after, 2)["scale"]["value"] = _motion(before, 2)["scale"]["value"]
    assert {**after, "name": "Sequence 04"} == before
    assert [s["name"] for s in read_project(dst)["sequences"]] == ["Sequence 01", "Sequence 02", "Sequence 03", "Donor & co"]
    src_text = gzip.decompress(SRC.read_bytes()).decode("utf-8")
    text = gzip.decompress(dst.read_bytes()).decode("utf-8")
    assert OLD_ID not in text and text.count(out["sequence_id"]) == src_text.count(OLD_ID)


def test_donor_without_a_param_only_renames(tmp_path):
    dst = tmp_path / "plain.prproj"
    write_donor(SRC, dst, sequence="Sequence 04", name="plain")
    assert {**_seq(dst, "plain"), "name": "Sequence 04"} == _seq(SRC, "Sequence 04")


@pytest.mark.parametrize("kwargs", [
    {"sequence": "nope", "name": "x"},
    {"sequence": "Sequence 04", "name": "x", "track": 2, "clip": 1, "param": "position", "value": 1},
    {"sequence": "Sequence 04", "name": "x", "param": "scale", "value": 1},
    {"sequence": "Sequence 04", "name": "x", "track": 0, "clip": 1, "param": "scale", "value": 1},
    {"sequence": "Sequence 04", "name": "x", "track": 9, "clip": 1, "param": "scale", "value": 1},
    {"sequence": "Sequence 04", "name": "x", "track": 3, "clip": 1, "param": "scale", "value": 1},  # keyframed
])
def test_donor_refuses_what_it_cannot_patch(tmp_path, kwargs):
    with pytest.raises(ValueError):
        write_donor(SRC, tmp_path / "x.prproj", **kwargs)
