"""prproj_reader walks the object graph shapes seen in real .prproj files (2026-09-25)."""

import gzip

from cutdeck.prproj_reader import read_project

T = 254016000000  # Premiere ticks per second

PROJECT = f"""<?xml version="1.0" encoding="UTF-8" ?>
<PremiereData Version="3">
  <Sequence ObjectUID="seq-1">
    <MarkerOwner><Markers ObjectRef="10"/></MarkerOwner>
    <TrackGroups>
      <TrackGroup Index="0"><First>v</First><Second ObjectRef="20"/></TrackGroup>
      <TrackGroup Index="1"><First>a</First><Second ObjectRef="21"/></TrackGroup>
    </TrackGroups>
    <Name>Main</Name>
  </Sequence>
  <Markers ObjectID="10">
    <Markers><Marker Index="0"><First>g</First><Second ObjectRef="11"/></Marker></Markers>
  </Markers>
  <Marker ObjectID="11">
    <DVAMarker>{{"DVAMarker":{{"mStartTime":{{"ticks":{2 * T}}},"mType":"Comment","mName":"hi"}}}}</DVAMarker>
  </Marker>
  <VideoTrackGroup ObjectID="20"><TrackGroup><Tracks><Track Index="0" ObjectURef="vt"/></Tracks></TrackGroup></VideoTrackGroup>
  <AudioTrackGroup ObjectID="21"><TrackGroup><Tracks><Track Index="0" ObjectURef="at"/></Tracks></TrackGroup></AudioTrackGroup>
  <VideoClipTrack ObjectUID="vt"><ClipTrack><Track><Index>0</Index><IsLocked>false</IsLocked><IsMuted>false</IsMuted></Track>
    <ClipItems><TrackItems><TrackItem Index="0" ObjectRef="30"/></TrackItems></ClipItems></ClipTrack></VideoClipTrack>
  <AudioClipTrack ObjectUID="at"><ClipTrack><Track><Index>0</Index><IsLocked>true</IsLocked></Track>
    <ClipItems><TrackItems><TrackItem Index="0" ObjectRef="40"/></TrackItems></ClipItems></ClipTrack>
    <AudioTrack><ComponentOwner><Components ObjectRef="50"/></ComponentOwner></AudioTrack></AudioClipTrack>
  <AudioComponentChain ObjectID="50"><ComponentChain><Components><Component Index="0" ObjectRef="51"/></Components></ComponentChain></AudioComponentChain>
  <AudioFader ObjectID="51"><AudioComponent><Component><Params><Param Index="0" ObjectRef="52"/></Params></Component></AudioComponent></AudioFader>
  <AudioComponentParam ObjectID="52"><CurrentValue>true</CurrentValue><Name>Mute</Name></AudioComponentParam>
  <VideoClipTrackItem ObjectID="30"><ClipTrackItem>
    <ComponentOwner><Components ObjectRef="31"/></ComponentOwner>
    <TrackItem><End>{3 * T}</End></TrackItem><SubClip ObjectRef="32"/></ClipTrackItem></VideoClipTrackItem>
  <VideoComponentChain ObjectID="31"><ComponentChain><Components><Component Index="0" ObjectRef="33"/></Components></ComponentChain></VideoComponentChain>
  <VideoFilterComponent ObjectID="33"><Component><DisplayName>Tint</DisplayName><Bypass>true</Bypass></Component>
    <MatchName>AE.ADBE Tint</MatchName></VideoFilterComponent>
  <SubClip ObjectID="32"><Clip ObjectRef="34"/><Name>shot.mp4</Name></SubClip>
  <VideoClip ObjectID="34"><Clip><Source ObjectRef="35"/><InPoint>{T}</InPoint><OutPoint>{4 * T}</OutPoint></Clip></VideoClip>
  <VideoMediaSource ObjectID="35"><MediaSource><Media ObjectURef="m1"/></MediaSource></VideoMediaSource>
  <Media ObjectUID="m1"><ActualMediaFilePath>C:\\shot.mp4</ActualMediaFilePath></Media>
  <AudioClipTrackItem ObjectID="40"><ClipTrackItem>
    <ComponentOwner><Components ObjectRef="41"/></ComponentOwner>
    <TrackItem><Start>{T}</Start><End>{2 * T}</End></TrackItem><SubClip ObjectRef="42"/><IsMuted>true</IsMuted></ClipTrackItem></AudioClipTrackItem>
  <AudioComponentChain ObjectID="41"><ComponentChain><Components><Component Index="0" ObjectRef="43"/></Components></ComponentChain></AudioComponentChain>
  <AudioFilterComponent ObjectID="43"><AudioComponent><Component><DisplayName>Hard Limiter</DisplayName><Bypass>false</Bypass></Component></AudioComponent></AudioFilterComponent>
  <SubClip ObjectID="42"><Clip ObjectRef="44"/><Name>Nested</Name></SubClip>
  <AudioClip ObjectID="44"><Clip><Source ObjectRef="45"/><InPoint>0</InPoint><OutPoint>{T}</OutPoint></Clip></AudioClip>
  <AudioSequenceSource ObjectID="45"><SequenceSource><Sequence ObjectURef="seq-1"/></SequenceSource></AudioSequenceSource>
</PremiereData>"""


def test_reads_tracks_clips_effects_and_markers(tmp_path):
    path = tmp_path / "p.prproj"
    path.write_bytes(gzip.compress(PROJECT.encode()))

    (seq,) = read_project(path)["sequences"]

    assert seq["name"] == "Main"
    assert seq["markers"] == [{"time": 2.0, "type": "Comment", "name": "hi", "comment": None}]

    (vt,) = seq["video_tracks"]
    assert (vt["muted"], vt["locked"]) == (False, False)
    assert vt["clips"] == [{
        "name": "shot.mp4", "start": 0.0, "end": 3.0, "source_in": 1.0, "source_out": 4.0,
        "disabled": False, "media_path": "C:\\shot.mp4",
        "effects": [{"name": "Tint", "match_name": "AE.ADBE Tint", "bypass": True}],
    }]

    (at,) = seq["audio_tracks"]
    assert (at["muted"], at["locked"]) == (True, True)
    (clip,) = at["clips"]
    assert clip["nested_sequence"] == "Main"
    assert clip["disabled"] is True
    assert clip["effects"] == [{"name": "Hard Limiter", "match_name": None, "bypass": False}]


def test_reads_uncompressed_xml(tmp_path):
    path = tmp_path / "p.prproj"
    path.write_text(PROJECT, encoding="utf-8")
    assert read_project(path)["sequences"][0]["name"] == "Main"


# --- Source Text (real blobs pulled from a Premiere 26 project, 2026-09-25) ---

import base64
import json
from pathlib import Path

import pytest

from cutdeck.prproj_reader import parse_source_text

_BLOBS = json.loads((Path(__file__).parent / "fixtures" / "source_text_blobs.json").read_text())


def _blob(name):
    return base64.b64decode(_BLOBS[name])


@pytest.mark.parametrize("name, text, font, size", [
    ("T1_hello_arial_100", "Hello", "ArialMT", 100.0),
    ("T2_size150", "Hello", "ArialMT", 150.0),
    ("T6_thai", "สวัสดี", "Sarabun-Regular", 100.0),
    ("T7_two_lines", "AB\rCD", "ArialMT", 150.0),
    ("T8_mixed_runs", "Hello World", "ArialMT", 150.0),
    ("T10_thai_latin_two_lines", "สวัสดี Hello\rสวัสดี Hello", "Sarabun-Regular", 100.0),
])
def test_parse_source_text(name, text, font, size):
    got = parse_source_text(_blob(name))
    assert (got["text"], got["font"], got["size"]) == (text, font, size)


def test_parse_source_text_runs_carry_their_own_font():
    # Thai + Arial + Arial Italic in one layer: each run's style names its font by index.
    runs = parse_source_text(_blob("T10_thai_latin_two_lines"))["runs"]
    assert [(r["text"], r["font"]) for r in runs] == [
        ("สวัสดี ", "Sarabun-Regular"), ("Hello", "ArialMT"),
        ("\rสวัสดี ", "Sarabun-Regular"), ("Hello", "Arial-ItalicMT")]


SOURCE_TEXT_PROJECT = """<?xml version="1.0" encoding="UTF-8" ?>
<PremiereData Version="3">
  <VideoFilterComponent ObjectID="5"><Component><DisplayName>Text</DisplayName>
    <Params><Param Index="0" ObjectRef="6"/></Params></Component><MatchName>AE.ADBE Text</MatchName></VideoFilterComponent>
  <ArbVideoComponentParam ObjectID="6"><Name>Source Text</Name>
    <Keyframes>KF</Keyframes>
    <StartKeyframeValue Encoding="base64">START</StartKeyframeValue></ArbVideoComponentParam>
</PremiereData>"""


def test_effects_carry_source_text_and_keyframes(tmp_path):
    from cutdeck.prproj_reader import _Objects, _text_of
    from xml.etree import ElementTree as ET

    kf = _BLOBS["T9_keyframes"]
    xml = SOURCE_TEXT_PROJECT.replace("START", _BLOBS["T1_hello_arial_100"]).replace("KF", kf)
    objs = _Objects(ET.fromstring(xml))
    got = _text_of(objs, objs.by_id["5"])
    assert (got["text"], got["font"], got["size"]) == ("Hello", "ArialMT", 100.0)
    assert [k["text"] for k in got["keyframes"]] == ["Hello", "BYE"]
    assert got["keyframes"][1]["time"] > got["keyframes"][0]["time"]


REAL = Path(__file__).parent.parent / "test_projects" / "probe.prproj"


@pytest.mark.skipif(not REAL.exists(), reason="probe.prproj is gitignored")
def test_real_probe_project_text_layers():
    seq = next(s for s in read_project(REAL)["sequences"] if s["name"] == "Sequence 01")
    texts = [e["text"]["text"] for t in seq["video_tracks"] for c in t["clips"]
             for e in c["effects"] if e.get("text")]
    assert "Hello" in texts and "สวัสดี" in texts and "AB\rCD" in texts


@pytest.mark.parametrize("name, fill, stroke", [
    ("T1_hello_arial_100", [255, 255, 255], None),
    ("C1_red", [255, 0, 0], None),
    ("C2_green", [0, 255, 0], None),
    ("C3_200_100_50", [200, 100, 50], None),
    ("C4_red_blue_stroke", [255, 0, 0], [0, 0, 255]),
])
def test_run_fill_and_stroke_colour(name, fill, stroke):
    run = parse_source_text(_blob(name))["runs"][0]
    assert (run["fill"], run["stroke"]) == (fill, stroke)


def test_run_tracking_and_bold():
    plain, world = parse_source_text(_blob("T8_mixed_runs"))["runs"]
    assert (plain["bold"], world["bold"]) == (False, True)
    assert plain["tracking"] == 200.0
    assert parse_source_text(_blob("T1_hello_arial_100"))["runs"][0]["tracking"] == 0.0


@pytest.mark.skipif(not REAL.exists(), reason="probe.prproj is gitignored")
def test_keyframe_clip_time_is_time_minus_source_in():
    # Sequence 02: clip at 10.01 s, keyframes set at 0 s, 1 s and 3 s into the clip.
    seq = next(s for s in read_project(REAL)["sequences"] if s["name"] == "Sequence 02")
    (clip,) = seq["video_tracks"][0]["clips"]
    (effect,) = [e for e in clip["effects"] if e.get("text")]
    stamps = [(k["text"], round(k["clip_time"], 2)) for k in effect["text"]["keyframes"]]
    assert stamps == [("a", 0.0), ("b", 1.0), ("c", 3.0)]


def test_run_colours_can_change_mid_word():
    # C3 was coloured per letter: "h" 200,100,50 then "i" 42,0,255 (B omitted = 255).
    h, i = parse_source_text(_blob("C3_200_100_50"))["runs"]
    assert (h["text"], h["fill"], i["text"], i["fill"]) == ("h", [200, 100, 50], "i", [42, 0, 255])


def test_repeated_source_text_blob_is_stored_once_by_hash():
    # Premiere writes an identical binary once; the later copies are empty, keyed by BinaryHash.
    from cutdeck.prproj_reader import _Objects, _text_of
    from xml.etree import ElementTree as ET

    def comp(cid, pid):
        return (f'<VideoFilterComponent ObjectID="{cid}"><Component><Params><Param Index="0" ObjectRef="{pid}"/></Params>'
                f'</Component><MatchName>AE.ADBE Text</MatchName></VideoFilterComponent>')

    xml = ("<PremiereData>" + comp(1, 11) + comp(2, 12)
           + f'<ArbVideoComponentParam ObjectID="11"><Name>Source Text</Name>'
             f'<StartKeyframeValue Encoding="base64" BinaryHash="h1">{_BLOBS["T1_hello_arial_100"]}</StartKeyframeValue></ArbVideoComponentParam>'
           + '<ArbVideoComponentParam ObjectID="12"><Name>Source Text</Name>'
             '<StartKeyframeValue Encoding="base64" BinaryHash="h1"></StartKeyframeValue></ArbVideoComponentParam>'
           + "</PremiereData>")
    objs = _Objects(ET.fromstring(xml))
    assert _text_of(objs, objs.by_id["2"])["text"] == "Hello"


def test_stroke_is_only_reported_when_switched_on():
    # The baseline keeps a stroke colour table but has the stroke flag off.
    (off,) = parse_source_text(_blob("S0_baseline_no_stroke"))["runs"]
    (on,) = parse_source_text(_blob("S1_stroke_w5"))["runs"]
    assert off["stroke"] is None
    assert on["stroke"] is not None


@pytest.mark.parametrize("name, width", [
    ("S0_baseline_no_stroke", 4.0), ("S1_stroke_w5", 5.0), ("S2_stroke_w20", 20.0)])
def test_stroke_width(name, width):
    assert parse_source_text(_blob(name))["runs"][0]["stroke_width"] == width


def test_leading():
    assert parse_source_text(_blob("S5_leading_150"))["leading"] == 150.0
    assert parse_source_text(_blob("S1_stroke_w5"))["leading"] == 0.0


def test_italic_and_underline_flags():
    # Layer set up as: "ab" italic, "cd" underline.
    ab, cd = parse_source_text(_blob("I1_italic_ab_underline_cd"))["runs"]
    assert (ab["italic"], ab["underline"], cd["underline"]) == (True, False, True)
    plain = parse_source_text(_blob("S1_stroke_w5"))["runs"][0]
    assert (plain["italic"], plain["underline"]) == (False, False)


def test_alignment_and_shadow():
    assert parse_source_text(_blob("A1_center"))["alignment"] == "center"   # confirmed by the user
    assert parse_source_text(_blob("S1_stroke_w5"))["alignment"] == "left"  # omitted = left
    assert parse_source_text(_blob("SH_shadow"))["shadow"] is True
    assert parse_source_text(_blob("A1_center"))["shadow"] is False
