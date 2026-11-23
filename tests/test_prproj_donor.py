"""prproj_donor: a donor copy changes exactly what it was asked to (issue #130)."""
import gzip
from pathlib import Path

import pytest

from cutdeck.prproj_donor import write_donor
from cutdeck.prproj_reader import read_project

SRC = Path(__file__).resolve().parent.parent / "test_projects" / "a5_start.prproj"
OLD_ID = "8e214d18-932a-4ad9-b6aa-663740045e4b"


def _scales(path):
    (seq,) = read_project(path)["sequences"]
    return seq["name"], [c["effects"][0]["params"]["scale"]["value"] for t in seq["video_tracks"] for c in t["clips"]]


def test_donor_changes_one_scale_the_name_and_the_guid_only(tmp_path):
    dst = tmp_path / "donor.prproj"
    out = write_donor(SRC, dst, sequence="Gate4", name="CutDeck donor", track=1, clip=1, param="scale", value=137.25)
    name, scales = _scales(dst)
    assert name == "CutDeck donor"
    assert scales == [137.25] + _scales(SRC)[1][1:]
    text = gzip.decompress(dst.read_bytes()).decode("utf-8")
    assert OLD_ID not in text and text.count(out["sequence_id"]) == 6
    before = read_project(SRC)["sequences"][0]
    after = read_project(dst)["sequences"][0]
    after["video_tracks"][0]["clips"][0]["effects"][0]["params"]["scale"]["value"] = 100.0
    assert {**after, "name": "Gate4"} == before


def test_donor_without_a_param_only_renames(tmp_path):
    dst = tmp_path / "plain.prproj"
    write_donor(SRC, dst, sequence="Gate4", name="plain")
    assert _scales(dst) == ("plain", _scales(SRC)[1])


@pytest.mark.parametrize("kwargs", [
    {"sequence": "nope", "name": "x"},
    {"sequence": "Gate4", "name": "x", "track": 1, "clip": 1, "param": "position", "value": 1},
    {"sequence": "Gate4", "name": "x", "param": "scale", "value": 1},
])
def test_donor_refuses_what_it_cannot_patch(tmp_path, kwargs):
    with pytest.raises(ValueError):
        write_donor(SRC, tmp_path / "x.prproj", **kwargs)
