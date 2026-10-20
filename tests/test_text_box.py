"""Premiere's blue text box (the box its Properties panel aligns and snaps the anchor to),
predicted from the saved project's Source Text and the font file (cutdeck/text_box.py).

The rule, from Premiere's own Align Left/Right/Top/Bottom on two DB Heavent Med layers
(live 2026-10-19, docs/PREMIERE_FACTS.md): in the text layer's own space (baseline y = 0,
y down), the box is one em tall, centred capHeight / 2 above the baseline, and runs from
x = 0 to the shaped advance width (kerning included)."""
import os
import time
from pathlib import Path

import pytest

from cutdeck import text_box

fontBuilder = pytest.importorskip("fontTools.fontBuilder")


def _font(tmp_path, cap_height=700, kern=-100):
    """A 1000-upem font: A and V, each 600 wide, ink 50..550 x 0..700, and an A-V kern."""
    from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    fb = fontBuilder.FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "A", "V"])
    fb.setupCharacterMap({ord("A"): "A", ord("V"): "V"})
    glyphs = {}
    for name in (".notdef", "A", "V"):
        pen = TTGlyphPen(None)
        if name != ".notdef":
            pen.moveTo((50, 0)); pen.lineTo((550, 0)); pen.lineTo((550, 700)); pen.lineTo((50, 700))
            pen.closePath()
        glyphs[name] = pen.glyph()
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({n: (600 if n != ".notdef" else 500, 50) for n in glyphs})
    fb.setupHorizontalHeader(ascent=900, descent=-300)
    fb.setupNameTable({"familyName": "BoxTest", "styleName": "Regular", "psName": "BoxTest-Regular"})
    fb.setupOS2(sTypoAscender=900, sTypoDescender=-300, usWinAscent=900, usWinDescent=300,
                sCapHeight=cap_height, sxHeight=500, version=4)
    fb.setupPost()
    addOpenTypeFeaturesFromString(fb.font, f"feature kern {{ pos A V {kern}; }} kern;")
    path = tmp_path / "BoxTest-Regular.ttf"
    fb.save(str(path))
    return path


def _layer(text="AV", font="BoxTest-Regular", size=100.0, **run):
    style = {"text": text, "font": font, "size": size, "tracking": 0.0, "bold": False, "italic": False}
    style.update(run)
    return {"text": text, "font": font, "size": size, "leading": 0.0, "alignment": "left", "runs": [style]}


def test_box_is_one_em_centred_on_half_the_cap_height_and_as_wide_as_the_kerned_advance(tmp_path):
    path = _font(tmp_path)
    got = text_box.layer_box(_layer(size=200.0), lambda name: path)
    s = 200 / 1000
    assert got["box"] == pytest.approx({"left": 0, "right": (600 + 600 - 100) * s,
                                        "top": -(350 + 500) * s, "bottom": (500 - 350) * s})
    # The letters: A's ink 50..550, V's starts after A's kerned advance (500).
    assert got["ink"] == pytest.approx({"left": 50 * s, "right": (500 + 550) * s, "top": -700 * s, "bottom": 0})


@pytest.mark.parametrize("change, reason", [
    ({"alignment": "center"}, "aligned"),
    ({"text": "A\rV"}, "line"),
    ({"tracking": 50.0}, "tracking"),
    ({"bold": True}, "bold"),
    ({"font": "NoSuchFont-Regular"}, "font"),
])
def test_cases_the_rule_was_not_proven_for_give_a_reason_not_a_box(tmp_path, change, reason):
    path = _font(tmp_path)
    layer = _layer()
    if "alignment" in change:
        layer["alignment"] = change["alignment"]
    elif "text" in change:
        layer["text"] = layer["runs"][0]["text"] = change["text"]
    elif "font" in change:
        layer["font"] = layer["runs"][0]["font"] = change["font"]
    else:
        layer["runs"][0].update(change)
    got = text_box.layer_box(layer, lambda name: path if name == "BoxTest-Regular" else None)
    assert "box" not in got
    assert reason in got["reason"]


def test_a_font_without_a_cap_height_gives_a_reason(tmp_path):
    path = _font(tmp_path, cap_height=0)
    got = text_box.layer_box(_layer(), lambda name: path)
    assert "box" not in got and "cap height" in got["reason"]


# The live numbers (Premiere's own Align buttons, 2026-10-19): "New Text Layer", DBHeavent-Med.
HEAVENT = Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts\DB HEAVENT MED V3.2.TTF"))


@pytest.mark.skipif(not HEAVENT.exists(), reason="DB Heavent Med is installed on the live machine only")
@pytest.mark.parametrize("size, top, bottom, right", [
    (162.38414001464844, -120.817, 41.567, 782.11),
    (238.61585998535156, -177.535, 61.081, 1149.271),
])
def test_live_db_heavent_boxes(size, top, bottom, right):
    layer = _layer("New Text Layer", "DBHeavent-Med", size)
    got = text_box.layer_box(layer, lambda name: HEAVENT if name == "DBHeavent-Med" else None)
    assert got["box"] == pytest.approx({"left": 0, "right": right, "top": top, "bottom": bottom}, abs=0.01)


def test_newest_save_is_used_project_or_auto_save(tmp_path):
    project = tmp_path / "EP 35.prproj"
    autos = tmp_path / "Adobe Premiere Pro Auto-Save"
    autos.mkdir()
    old = autos / "EP 35--abc-2026-10-19_09-00-00.prproj"
    new = autos / "EP 35--abc-2026-10-19_11-17-16.prproj"
    other = autos / "Other--abc-2026-10-19_12-00-00.prproj"
    for i, p in enumerate([old, project, new]):
        p.write_text("x")
        os.utime(p, (time.time() - 100 + i, time.time() - 100 + i))
    other.write_text("x")
    assert text_box.newest_save(str(project)) == new
    assert text_box.newest_save("\\\\?\\" + str(project)) == new


def test_finds_the_clip_by_track_and_start_and_reads_each_text_layer(tmp_path):
    path = _font(tmp_path)
    clip = {"name": "Graphic", "start": 1123.6, "effects": [
        {"match_name": "AE.ADBE Motion", "params": {}},
        {"match_name": "AE.ADBE Text", "text": _layer(size=100.0)},
        {"match_name": "AE.ADBE Text", "text": _layer(size=200.0)},
    ]}
    project = {"sequences": [{"name": "Editing", "video_tracks": [
        {"index": 0, "clips": []}, {"index": 8, "clips": [clip]}]}]}
    got = text_box.clip_layers(project, "Editing", 8, 1123.6, lambda name: path)
    assert [round(g["box"]["right"]) for g in got] == [110, 220]
    with pytest.raises(LookupError):
        text_box.clip_layers(project, "Editing", 8, 50.0, lambda name: path)


def test_helper_answers_text_box_requests():
    from cutdeck.helper import Jobs

    assert Jobs._HANDLERS["text_box"] == "_on_text_box"
    assert hasattr(Jobs, "_on_text_box")
