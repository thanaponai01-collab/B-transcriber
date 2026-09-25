"""tests/test_cutdeck_text_properties.py — tests for cutdeck/text_properties.py"""

import gzip
import json
from pathlib import Path

import pytest

from cutdeck.text_properties import (
    extract_project_text_properties,
    measure_text_bounds,
    resolve_font_file,
    tokenize_font,
)


_BLOB = json.loads((Path(__file__).parent / "fixtures" / "source_text_blobs.json").read_text())["T6_thai"]

PROJECT = f"""<?xml version="1.0" encoding="UTF-8" ?>
<PremiereData Version="3">
  <Sequence ObjectUID="s"><TrackGroups><TrackGroup Index="0"><First>v</First><Second ObjectRef="1"/></TrackGroup></TrackGroups><Name>Main</Name></Sequence>
  <VideoTrackGroup ObjectID="1"><TrackGroup><Tracks><Track Index="0" ObjectURef="t"/></Tracks></TrackGroup></VideoTrackGroup>
  <VideoClipTrack ObjectUID="t"><ClipTrack><Track><Index>0</Index></Track>
    <ClipItems><TrackItems><TrackItem Index="0" ObjectRef="2"/></TrackItems></ClipItems></ClipTrack></VideoClipTrack>
  <VideoClipTrackItem ObjectID="2"><ClipTrackItem><ComponentOwner><Components ObjectRef="3"/></ComponentOwner>
    <TrackItem><End>254016000000</End></TrackItem><SubClip ObjectRef="4"/></ClipTrackItem></VideoClipTrackItem>
  <VideoComponentChain ObjectID="3"><ComponentChain><Components><Component Index="0" ObjectRef="5"/></Components></ComponentChain></VideoComponentChain>
  <VideoFilterComponent ObjectID="5"><Component><DisplayName>Text</DisplayName><Params><Param Index="0" ObjectRef="6"/></Params></Component>
    <MatchName>AE.ADBE Text</MatchName></VideoFilterComponent>
  <ArbVideoComponentParam ObjectID="6"><Name>Source Text</Name><StartKeyframeValue Encoding="base64">{_BLOB}</StartKeyframeValue></ArbVideoComponentParam>
  <SubClip ObjectID="4"><Name>Graphic</Name></SubClip>
</PremiereData>"""


def test_extract_project_text_properties(tmp_path: Path):
    prproj_file = tmp_path / "test_project.prproj"
    prproj_file.write_bytes(gzip.compress(PROJECT.encode("utf-8")))

    (got,) = extract_project_text_properties(prproj_file)
    assert {k: got[k] for k in ("sequence", "track", "clip", "start", "end", "text", "font", "size")} == {
        "sequence": "Main", "track": 0, "clip": "Graphic", "start": 0.0, "end": 1.0,
        "text": "สวัสดี", "font": "Sarabun-Regular", "size": 100.0,
    }

    with pytest.raises(FileNotFoundError):
        extract_project_text_properties(tmp_path / "non_existent.prproj")


def test_tokenize_font():
    tokens = tokenize_font("LucidaCalligraphy-Italic")
    assert "lucida" in tokens
    assert "calligraphy" in tokens
    assert "italic" in tokens

    arial_tokens = tokenize_font("Arial-BoldMT")
    assert "arial" in tokens or "arial" in arial_tokens
    assert "bold" in arial_tokens


def test_measure_text_bounds_empty():
    bounds = measure_text_bounds("")
    assert bounds["width"] == 0.0
    assert bounds["height"] == 0.0
    assert bounds["advance"] == 0.0


def test_measure_text_bounds_default_and_scaling():
    bounds_100 = measure_text_bounds("Hello World", font_name_or_path="", font_size=100)
    assert bounds_100["width"] > 0
    assert bounds_100["height"] > 0
    assert bounds_100["advance"] > 0

    # Scaling scale_x by 200% should double the width and advance
    bounds_200 = measure_text_bounds("Hello World", font_name_or_path="", font_size=100, scale_x=200.0)
    assert abs(bounds_200["width"] - bounds_100["width"] * 2) < 0.1
    assert abs(bounds_200["advance"] - bounds_100["advance"] * 2) < 0.1
