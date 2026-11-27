"""Restyle a placed text layer through a Premiere text style: read the layer's Source Text from the
saved project, and write a .prtextstyle that Premiere imports as a style item."""
import base64
import gzip
import json
import re
from pathlib import Path

import pytest

from cutdeck import text_document as td, text_style

FIXTURES = Path(__file__).parent / "fixtures"
STYLED = json.loads((FIXTURES / "source_text_styled.json").read_text(encoding="utf-8"))
LINE = STYLED["P2_top_line_thai"]
QUOTE = STYLED["P3_quote_open_bg_shadows"]
T = 254016000000


def _project(tmp_path, keyframes=""):
    """One sequence "S": V1 empty clip at 0, V2 a Graphic at 2 s with Wiggle and two text layers
    (the second an empty twin of a blob written once, as Premiere saves repeats)."""
    def text(cid, pid, body, hash_):
        return (f'<VideoFilterComponent ObjectID="{cid}"><Component><Params><Param Index="0" ObjectRef="{pid}"/></Params>'
                f'</Component><MatchName>AE.ADBE Text</MatchName></VideoFilterComponent>'
                f'<ArbVideoComponentParam ObjectID="{pid}"><Name>Source Text</Name>{keyframes if cid == 41 else ""}'
                f'<StartKeyframeValue Encoding="base64" BinaryHash="{hash_}">{body}</StartKeyframeValue></ArbVideoComponentParam>')
    xml = f"""<?xml version="1.0" encoding="UTF-8" ?>
<PremiereData Version="3">
  <Sequence ObjectUID="seq"><TrackGroups><TrackGroup Index="0"><First>v</First><Second ObjectRef="20"/></TrackGroup></TrackGroups><Name>S</Name></Sequence>
  <VideoTrackGroup ObjectID="20"><TrackGroup><Tracks><Track Index="0" ObjectURef="v1"/><Track Index="1" ObjectURef="v2"/></Tracks></TrackGroup></VideoTrackGroup>
  <VideoClipTrack ObjectUID="v1"><ClipTrack><Track><Index>0</Index></Track><ClipItems><TrackItems><TrackItem Index="0" ObjectRef="30"/></TrackItems></ClipItems></ClipTrack></VideoClipTrack>
  <VideoClipTrack ObjectUID="v2"><ClipTrack><Track><Index>1</Index></Track><ClipItems><TrackItems><TrackItem Index="0" ObjectRef="31"/></TrackItems></ClipItems></ClipTrack></VideoClipTrack>
  <VideoClipTrackItem ObjectID="30"><ClipTrackItem><TrackItem><End>{T}</End></TrackItem></ClipTrackItem></VideoClipTrackItem>
  <VideoClipTrackItem ObjectID="31"><ClipTrackItem><ComponentOwner><Components ObjectRef="32"/></ComponentOwner>
    <TrackItem><Start>{2 * T}</Start><End>{5 * T}</End></TrackItem></ClipTrackItem></VideoClipTrackItem>
  <VideoComponentChain ObjectID="32"><ComponentChain><Components>
    <Component Index="0" ObjectRef="33"/><Component Index="1" ObjectRef="40"/><Component Index="2" ObjectRef="41"/><Component Index="3" ObjectRef="42"/>
  </Components></ComponentChain></VideoComponentChain>
  <VideoFilterComponent ObjectID="33"><Component/><MatchName>AE.Impact_Wiggle_FX</MatchName></VideoFilterComponent>
  {text(40, 50, LINE, "h-line")}{text(41, 51, QUOTE, "h-quote")}{text(42, 52, "", "h-line")}
</PremiereData>"""
    path = tmp_path / "p.prproj"
    path.write_bytes(gzip.compress(xml.encode("utf-8")))
    return path


def test_layer_blob_reads_each_text_layer_of_a_clip_in_chain_order(tmp_path):
    path = _project(tmp_path)
    got = [text_style.layer_blob(path, "S", f"V2@{2 * T}", k) for k in range(3)]
    assert got[0] == base64.b64decode(LINE) and got[1] == base64.b64decode(QUOTE)
    assert got[2] == got[0]  # an empty twin reads its carrier's blob


@pytest.mark.parametrize("sequence, clip, layer, error", [
    ("Nope", f"V2@{2 * T}", 0, "no sequence"),
    ("S", "V2@0", 0, "no clip"),
    ("S", "V3@0", 0, "no clip"),
    ("S", "V1@0", 0, "no text layer"),
    ("S", f"V2@{2 * T}", 3, "3 text layers"),
])
def test_layer_blob_refuses_what_is_not_there(tmp_path, sequence, clip, layer, error):
    with pytest.raises(ValueError, match=error):
        text_style.layer_blob(_project(tmp_path), sequence, clip, layer)


def test_layer_blob_refuses_a_sequence_name_two_sequences_share(tmp_path):
    path = _project(tmp_path)
    xml = gzip.decompress(path.read_bytes()).decode("utf-8")
    xml = xml.replace("</PremiereData>", '<Sequence ObjectUID="seq2"><Name>S</Name></Sequence></PremiereData>')
    path.write_bytes(gzip.compress(xml.encode("utf-8")))
    with pytest.raises(ValueError, match="2 sequences are named"):
        text_style.layer_blob(path, "S", f"V2@{2 * T}", 0)


def test_layer_blob_refuses_keyframed_source_text(tmp_path):
    path = _project(tmp_path, keyframes=f"<Keyframes>0,{QUOTE};</Keyframes>")
    with pytest.raises(ValueError, match="keyframed"):
        text_style.layer_blob(path, "S", f"V2@{2 * T}", 1)


def test_write_style_makes_a_named_style_project_holding_the_document(tmp_path):
    doc = td.restyle(td.decode(base64.b64decode(LINE)), {"fill": "#FF0000"})
    out = text_style.write_style(doc, "CutDeck restyle 1a2b3c", tmp_path / "x.prtextstyle")
    xml = out.read_text(encoding="utf-8")
    assert re.search(r"<StyleProjectItem ObjectUID=\"[0-9a-f-]{36}\"", xml)
    assert "<Name>CutDeck restyle 1a2b3c</Name>" in xml
    assert text_style.STYLE_UID not in xml and text_style.ROOT_UID not in xml
    (hash_, body), = re.findall(r'BinaryHash="([^"]+)">([^<]+)<', xml)
    blob = base64.b64decode(body)
    written = td.decode(blob)
    assert written["runs"][0]["text"] == "Aa"  # a style's text, as Premiere saves one
    written["runs"][0]["text"] = doc["runs"][0]["text"]
    assert written == doc
    assert int(hash_[-8:], 16) == len(blob) + 12
    again = text_style.write_style(doc, "CutDeck restyle 1a2b3c", tmp_path / "y.prtextstyle").read_text(encoding="utf-8")
    uid = lambda s: re.search(r'<StyleProjectItem ObjectUID="([^"]+)"', s)[1]  # noqa: E731
    assert uid(again) != uid(xml)  # each style a new project item


def test_restyled_layer_keeps_untouched_fields_and_refuses_several_runs():
    doc = text_style.restyled_layer(base64.b64decode(QUOTE), {"size": 50, "fill": "#00FF00"})
    before = td.decode(base64.b64decode(QUOTE))
    assert doc["runs"][0]["style"]["size"] == 50.0 and doc["background_corner"] == before["background_corner"]
    two = dict(before, runs=before["runs"] * 2)
    with pytest.raises(ValueError, match="2 style runs"):
        text_style.restyled_layer(td.encode(two), {"size": 50})


def test_mismatches_reads_fields_premiere_left_out_at_their_default():
    # Live 2026-11-27: green asked as #00FF00 was saved as {r: 0, b: 0} (g left out = 255).
    before = td.decode(base64.b64decode(LINE))
    changes = {"fill": "#00FF00", "size": 100, "underline": False}
    want = td.restyle(before, changes)
    saved = json.loads(json.dumps(want))
    saved["runs"][0]["style"]["fill"] = {"r": 0, "b": 0}
    saved["runs"][0]["style"].pop("size", None)
    saved["runs"][0]["style"].pop("underline", None)
    assert text_style.mismatches(saved, want, changes) == []
    saved["runs"][0]["text"] = "other"
    saved["alignment"] = 0 if want.get("alignment") else 1
    assert text_style.mismatches(saved, want, changes) == ["alignment", "runs (text or other run styles)"]
    saved = json.loads(json.dumps(want))
    saved["runs"][0]["style"]["fill"] = {"g": 0}
    assert text_style.mismatches(saved, want, changes) == ["fill"]


def _fake_premiere(path, calls):
    clip = f"V2@{2 * T}"

    async def premiere(command, args):
        calls.append(command)
        return {"open_sequence": {"name": "S"}, "save_project": {"path": "\\?\\" + str(path)},
                "read_timeline": {"tracks": [{"clips": [{"id": clip, "effects": [{"match_name": "AE.ADBE Text"}] * 3}]}]},
                "list_project": {"items": [{"name": "Footage", "bin": True}]},
                "remove_style_bin": {"removed": True}}.get(command, {})
    return premiere


def _premiere_links(path, monkeypatch, lands=True):
    """link_style as Premiere does it: the style's look onto layer 1, its text kept."""
    import tempfile
    from cutdeck import premiere_ui

    def link(layer, layers, name):
        style = (Path(tempfile.gettempdir()) / f"{name}.prtextstyle").read_text(encoding="utf-8")
        doc = td.decode(base64.b64decode(re.search(r'BinaryHash="[^"]+">([^<]+)<', style)[1]))
        doc["runs"][0]["text"] = td.decode(base64.b64decode(QUOTE))["runs"][0]["text"]
        xml = gzip.decompress(path.read_bytes()).decode("utf-8")
        if lands:
            xml = xml.replace(QUOTE, base64.b64encode(td.encode(doc)).decode())
        path.write_bytes(gzip.compress(xml.encode("utf-8")))
        return {"row": (514, 368)}
    monkeypatch.setattr(premiere_ui, "link_style", link)
    monkeypatch.setattr(premiere_ui, "unlink_style", lambda name: None)


def test_restyle_text_links_unlinks_removes_and_reads_the_look_back(tmp_path, monkeypatch):
    import asyncio
    from cutdeck import premiere_ui
    path, calls = _project(tmp_path), []
    _premiere_links(path, monkeypatch)
    out = asyncio.run(premiere_ui.restyle_text(_fake_premiere(path, calls), {
        "sequence": "S", "clip": f"V2@{2 * T}", "layer": 1, "styles": {"fill": "#00FF00", "size": 50}}))
    assert out["layers"] == 3 and out["style_removed"]
    assert calls.index("save_project") < calls.index("import_files") < calls.index("remove_style_bin") < len(calls) - 1
    assert calls[-1] == "save_project"
    after = td.decode(text_style.layer_blob(path, "S", f"V2@{2 * T}", 1))
    assert after["runs"][0]["style"]["size"] == 50.0 and after["runs"][0]["text"] == td.decode(base64.b64decode(QUOTE))["runs"][0]["text"]


def test_restyle_text_fails_when_the_saved_layer_is_not_the_asked_look(tmp_path, monkeypatch):
    import asyncio
    from cutdeck import premiere_ui
    path = _project(tmp_path)
    _premiere_links(path, monkeypatch, lands=False)
    with pytest.raises(RuntimeError, match=r"differs in \['fill', 'size'\].*four Edit > Undo"):
        asyncio.run(premiere_ui.restyle_text(_fake_premiere(path, []), {
            "sequence": "S", "clip": f"V2@{2 * T}", "layer": 1, "styles": {"fill": "#00FF00", "size": 50}}))


def test_restyle_text_refuses_a_leftover_restyle_bin_before_touching_anything(tmp_path):
    import asyncio
    from cutdeck import premiere_ui
    calls = []
    base = _fake_premiere(_project(tmp_path), calls)

    async def premiere(command, args):
        if command == "list_project":
            return {"items": [{"name": "CutDeck restyle 0a0a0a.prtextstyle", "bin": True}]}
        return await base(command, args)
    with pytest.raises(ValueError, match="earlier restyle"):
        asyncio.run(premiere_ui.restyle_text(premiere, {"clip": f"V2@{2 * T}", "layer": 0, "styles": {"size": 50}, "sequence": "S"}))
    assert "save_project" not in calls and "import_files" not in calls


def test_mismatches_ignores_what_premiere_adds_on_any_resave():
    # Live 2026-11-27: layer 2 of the scratch Graphic before and after restyle_text {fill FF00FF,
    # size 160, stroke_width 4}, as decoded from the saved project.
    before = {"runs": [{"text": "“", "style": {"size": 120.0, "fill": {"r": 32, "g": 110, "b": 143},
              "stroke": {"r": 177, "g": 225, "b": 250}, "stroke_on": 1, "stroke_width": 8.0, "fill_gradient": {}}}],
              "shadows": [{"colour": {}, "on": 1}]}
    changes = {"fill": "#FF00FF", "size": 160, "stroke_width": 4}
    want = td.restyle(before, changes)
    saved = {"runs": [{"text": "“", "style": {"size": 160.0, "fill": {"g": 0}, "stroke": {"r": 177, "g": 225, "b": 250},
             "stroke_on": 1, "stroke_width": 4.0, "fill_gradient": {}, "stroke_gradient": {}}}],
             "shadows": [{"colour": {}, "on": 1, "gradient": {}}], "f40_gradient": {}, "f44": 1}
    assert text_style.mismatches(saved, want, changes) == []
    saved["shadows"][0]["on"] = 0
    assert text_style.mismatches(saved, want, changes) == ["shadows"]
