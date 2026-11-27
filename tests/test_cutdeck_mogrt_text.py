import base64
import gzip
import io
import json
import re
import struct
import zipfile

import pytest

from cutdeck import mogrt_text, text_document
from cutdeck.prproj_reader import parse_source_text


def _template(path):
    definition = {
        "capsuleID": "old-id",
        "clientControls": [
            {"type": 6, "uiName": {"strDB": [{"localeString": "en_US", "str": "Title"}]},
             "value": {"strDB": [{"localeString": "en_US", "str": "Old"}, {"localeString": "th_TH", "str": "เก่า"}]}},
            {"type": 2, "uiName": {"strDB": [{"localeString": "en_US", "str": "Color"}]}},
            {"type": 6, "uiName": {"strDB": [{"localeString": "en_US", "str": "Sub"}]},
             "value": {"strDB": [{"localeString": "en_US", "str": "Keep"}]}},
        ],
        "sourceInfoLocalized": {"en_US": {"capsuleparams": {"capParams": [
            {"capPropUIName": "Title", "capPropDefault": "Old"}, {"capPropUIName": "Sub", "capPropDefault": "Keep"}]}}},
    }
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("definition.json", json.dumps(definition))
        z.writestr("project.aegraphic", b"\x00binary")
    return path


def test_bake_sets_text_everywhere_and_a_new_capsule_id(tmp_path):
    src = _template(tmp_path / "t.mogrt")
    out = mogrt_text.bake(src, {"Title": "สวัสดี"})
    with zipfile.ZipFile(out) as z:
        d = json.loads(z.read("definition.json"))
        assert z.read("project.aegraphic") == b"\x00binary"
    assert [s["str"] for s in d["clientControls"][0]["value"]["strDB"]] == ["สวัสดี", "สวัสดี"]
    assert d["clientControls"][2]["value"]["strDB"][0]["str"] == "Keep"
    params = d["sourceInfoLocalized"]["en_US"]["capsuleparams"]["capParams"]
    assert [p["capPropDefault"] for p in params] == ["สวัสดี", "Keep"]
    assert d["capsuleID"] != "old-id"  # Premiere re-places its cached original otherwise


def test_bake_by_index_counts_text_controls_only(tmp_path):
    out = mogrt_text.bake(_template(tmp_path / "t.mogrt"), {"1": "New sub"})
    assert [c["text"] for c in mogrt_text.text_controls(out)] == ["Old", "New sub"]


def test_unknown_text_lists_the_templates_texts(tmp_path):
    with pytest.raises(ValueError, match='0 "Title", 1 "Sub"'):
        mogrt_text.bake(_template(tmp_path / "t.mogrt"), {"Nope": "x"})


def test_bake_deletes_copies_older_than_a_week_and_keeps_recent_ones(tmp_path, monkeypatch):
    import os, time
    monkeypatch.setattr(mogrt_text.tempfile, "gettempdir", lambda: str(tmp_path))
    bake_dir = tmp_path / "cutdeck-mogrt"
    bake_dir.mkdir()
    old, recent = bake_dir / "old.mogrt", bake_dir / "recent.mogrt"
    for f, age_days in ((old, 8), (recent, 6)):
        f.write_bytes(b"x")
        t = time.time() - age_days * 86400
        os.utime(f, (t, t))
    out = mogrt_text.bake(_template(tmp_path / "t.mogrt"), {"Title": "x"})
    assert not old.exists() and recent.exists() and out.exists()


# Source Text blobs (FlatBuffer form) cut from the user's Premiere-exported CFD quote template
# `20261111 - template.mogrt` (2026-11-27): a Thai line layer and a quote-mark layer.
LINE_HASH = "4de08c46-7e00-dd62-6ddd-743900000204"
LINE_BLOB = (
    "7AEAAAAAAABEMyIRDAAAAAAABgAKAAQABgAAAGQAAAAAAF4AKAAUABAAAAAAAAAAAAAAAAAAAAAAACQAIwAAAAAAAAAAABwA"
    "AAAAAAAAAAAAAAAAAAAAAAAAGwAAAAAAAAAAAAAAAAAAAAAAAAAAAAwAAAAAAAgAAAAAAAAABwBeAAAAAAAAAVgAAAAcAAAA"
    "ZAAAAHgAAAAAAAABfkLwQgAAAAFIAAAAAQAAABwAAAAAABYAEAAIAAcAAAAAAAAAAAAAAAAADAAWAAAAAAAAAQgAAAAIAAAA"
    "GP///xz///8g////JP///yj///8G////AP///wEAAAAEAAAACwAAAERCRUVTdHJva2VYAAEAAAAMAAAACAAMAAQACAAIAAAA"
    "CAAAAHwAAAA/AAAA4LiE4Lin4Liy4Lih4Lij4Li54LmJ4Liq4Li24LiB4LiC4Lit4LiH4Lir4LiZ4Li54Lih4Liy4LiB4Lie"
    "4LitADQAIAAAABwAGAAAABQAEwAMAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIAAAABAA0AAAAIAAAACQAAAAAAIBB"
    "AAAAASgAAAA4AAAA09INQwQABAAEAAAABAAGAAQAAAAAAAoACgAHAAgACQAKAAAAAAAAseH6CgAIAAUABgAHAAoAAAAAIG6P"
)
QUOTE_HASH = "8e5eee22-918c-64af-fb68-1df500000188"
QUOTE_BLOB = (
    "cAEAAAAAAABEMyIRDAAAAAAABgAIAAQABgAAAFQAAABQACAADAAIAAAAAAAAAAAAAAAAAAAAAAAcABsAAAAAAAAAAAAUAAAA"
    "AAAAAAAAAAAAAAAAAAAAABMAAAAAAAAAAAAAAAAAAAAAAAAAAAAEAFAAAAAcAAAATAAAAGAAAAAAAAABfkLwQgAAAAEwAAAA"
    "AQAAAAwAAAAIAAwACAAHAAgAAAAAAAABBAAAAPj////8////BAAEAAQAAABa////AP///wEAAAAEAAAACwAAAERCRUVTdHJv"
    "a2VYAAEAAAAMAAAACAAMAAQACAAIAAAAhAAAADQAAAAwABwAAAAYABQAAAAQAA8ACAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAABAAwAAAAHAAAAAAAAEEAAAABIAAAADAAAAAAAPBCBAAGAAQAAAAAAAoACgAHAAgACQAKAAAAAAAAseH6CgAIAAUA"
    "BgAHAAoAAAAAIG6PAwAAAOKAnAA="
)
LINE_TEXT = "ความรู้สึกของหนูมากพอ"


def _source_text(blob, hash_, empty=False):
    value = (f'<StartKeyframeValue Encoding="base64" BinaryHash="{hash_}"/>' if empty else
             f'<StartKeyframeValue Encoding="base64" BinaryHash="{hash_}">{blob}\n\t\t</StartKeyframeValue>')
    return ('\t<ArbVideoComponentParam ObjectID="1" ClassID="313e54d4-6903-49ad-b0bf-8262cdd10f4e" Version="3">\n'
            f'\t\t<Name>Source Text</Name>\n\t\t{value}\n\t</ArbVideoComponentParam>\n')


def _ppro_template(path):
    """A Premiere-made template: four text layers whose text Premiere draws from project.prgraphic.
    The fourth layer is an empty twin of the third, sharing its BinaryHash, as Premiere saves it."""
    xml = ('<?xml version="1.0" encoding="UTF-8" ?>\n<PremiereData Version="3">\n'
           + _source_text(LINE_BLOB, LINE_HASH) + _source_text(LINE_BLOB, LINE_HASH, empty=True)
           + _source_text(QUOTE_BLOB, QUOTE_HASH) + _source_text(QUOTE_BLOB, QUOTE_HASH, empty=True)
           + '</PremiereData>\n')
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("t.prproj", gzip.compress(xml.encode("utf-8")))
    texts = [LINE_TEXT, LINE_TEXT, "“", "“"]
    definition = {"authorApp": "ppro", "capsuleID": "old-id", "clientControls": [
        {"type": 6, "uiName": {"strDB": [{"localeString": "en_US", "str": "TextLayer"}]},
         "value": {"strDB": [{"localeString": "en_US", "str": t}]}} for t in texts]}
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("definition.json", json.dumps(definition))
        z.writestr("project.prgraphic", inner.getvalue())
    return path


def _layers(mogrt):
    """(BinaryHash, decoded Source Text or None for an empty twin) per text layer of a baked copy."""
    with zipfile.ZipFile(mogrt) as z, zipfile.ZipFile(io.BytesIO(z.read("project.prgraphic"))) as inner:
        assert inner.namelist() == ["t.prproj"]
        xml = gzip.decompress(inner.read("t.prproj")).decode("utf-8")
    found = re.findall(r'BinaryHash="([^"]+)"(?:/>|>([^<]*)<)', xml)
    return [(h, parse_source_text(base64.b64decode(b)) if b else None) for h, b in found]


@pytest.mark.parametrize("new", ["สั้น", "ผู้ชายคนนี้ ไม่ได้ห่วงเลยแม้แต่นิดเดียว จริง ๆ นะ"])
def test_bake_rewrites_premiere_source_text_keeping_its_style(tmp_path, new):
    before = _layers(_ppro_template(tmp_path / "t.mogrt"))
    out = mogrt_text.bake(tmp_path / "t.mogrt", {"0": new})
    after = _layers(out)
    text, original = after[0][1], before[0][1]
    assert text["text"] == new
    for key in ("font", "size", "leading", "alignment", "shadow"):
        assert text[key] == original[key]
    for key in ("fill", "stroke", "stroke_width", "tracking", "bold"):
        assert text["runs"][0][key] == original["runs"][0][key]
    blob_len = len(base64.b64decode(re.search(r'BinaryHash="%s">([^<]*)<' % re.escape(after[0][0]),
                                               _xml(out)).group(1)))
    assert after[0][0] != LINE_HASH and after[0][0].endswith(f"{blob_len + 12:08x}")
    # The second layer was an empty twin of the first: it now carries the original itself.
    assert after[1][0] == LINE_HASH and after[1][1]["text"] == LINE_TEXT
    assert after[2:] == before[2:]


def _xml(mogrt):
    with zipfile.ZipFile(mogrt) as z, zipfile.ZipFile(io.BytesIO(z.read("project.prgraphic"))) as inner:
        return gzip.decompress(inner.read("t.prproj")).decode("utf-8")


def test_bake_maps_same_text_controls_to_layers_in_order(tmp_path):
    out = mogrt_text.bake(_ppro_template(tmp_path / "t.mogrt"), {"3": "”", "1": "บรรทัดสอง"})
    texts = [t and t["text"] for _, t in _layers(out)]
    assert texts == [LINE_TEXT, "บรรทัดสอง", "“", "”"]
    assert [c["text"] for c in mogrt_text.text_controls(out)] == [LINE_TEXT, "บรรทัดสอง", "“", "”"]


def test_bake_keeps_a_json_form_prgraphic_byte_identical(tmp_path):
    """Basic Title's Source Text is the UTF-16 JSON form, which honours definition.json."""
    payload = json.dumps({"mTextParam": {"mStyleSheet": {"mText": "Old"}}}).encode("utf-16-le")
    blob = base64.b64encode(struct.pack("<Q", len(payload)) + payload).decode("ascii")
    xml = '<PremiereData>\n' + _source_text(blob, "11111111-2222-3333-4444-5555000000ff") + '</PremiereData>\n'
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("t.prproj", gzip.compress(xml.encode("utf-8")))
    src = _template(tmp_path / "t.mogrt")
    with zipfile.ZipFile(src, "a") as z:
        z.writestr("project.prgraphic", inner.getvalue())
    out = mogrt_text.bake(src, {"Title": "ใหม่"})
    with zipfile.ZipFile(out) as z:
        assert z.read("project.prgraphic") == inner.getvalue()


def test_bake_refuses_a_control_with_no_matching_layer(tmp_path):
    src = _ppro_template(tmp_path / "t.mogrt")
    with zipfile.ZipFile(src) as z:
        definition, prgraphic = json.loads(z.read("definition.json")), z.read("project.prgraphic")
    definition["clientControls"][0]["value"]["strDB"][0]["str"] = "not in the graphic"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("definition.json", json.dumps(definition))
        z.writestr("project.prgraphic", prgraphic)
    with pytest.raises(ValueError, match="no text layer"):
        mogrt_text.bake(src, {"0": "x"})


def _documents(mogrt):
    """The decoded Source Text document per text layer of a baked copy (None for an empty twin)."""
    found = re.findall(r'BinaryHash="([^"]+)"(?:/>|>([^<]*)<)', _xml(mogrt))
    return [text_document.decode(base64.b64decode(b)) if b.strip() else None for _, b in found]


def test_bake_styles_a_layer_and_keeps_its_text_and_the_rest(tmp_path):
    src = _ppro_template(tmp_path / "t.mogrt")
    out = mogrt_text.bake(src, {}, styles={"0": {
        "fill": "#FF0000", "size": 90, "bold": True, "alignment": "centre", "shadow_on": True}})
    docs, before = _documents(out), _documents(src)
    style = docs[0]["runs"][0]["style"]
    assert docs[0]["runs"][0]["text"] == LINE_TEXT
    assert style["fill"] == {"r": 255, "g": 0, "b": 0}  # every channel written, never merged
    assert (style["size"], style["bold"], docs[0]["alignment"], docs[0]["shadow_on"]) == (90.0, 1, 2, 1)
    assert style["stroke"] == before[0]["runs"][0]["style"]["stroke"]  # untouched fields kept
    assert docs[1] == before[0]  # the twin now carries the original itself
    assert docs[2:] == before[2:]


def test_bake_sets_text_and_style_on_one_control(tmp_path):
    out = mogrt_text.bake(_ppro_template(tmp_path / "t.mogrt"), {"2": "”"},
                          styles={"2": {"stroke": "#00ff80", "stroke_width": 3.5, "vertical_alignment": "bottom"}})
    doc = _documents(out)[2]
    assert doc["runs"][0]["text"] == "”" and doc["vertical_alignment"] == 2
    assert doc["runs"][0]["style"]["stroke"] == {"r": 0, "g": 255, "b": 128}
    assert doc["runs"][0]["style"]["stroke_width"] == 3.5


@pytest.mark.parametrize("change, error", [
    ({"font": "Arial"}, "unknown style"),
    ({"fill_gradient": {}}, "unknown style"),
    ({"f26": 1}, "unknown style"),
    ({"fill": "red"}, "#RRGGBB"),
    ({"alignment": "middle"}, "alignment"),
    ({"size": "big"}, "number"),
])
def test_bake_refuses_a_bad_style(tmp_path, change, error):
    with pytest.raises(ValueError, match=error):
        mogrt_text.bake(_ppro_template(tmp_path / "t.mogrt"), {}, styles={"0": change})


def test_bake_refuses_styles_a_template_cannot_take(tmp_path):
    with pytest.raises(ValueError, match="unknown text"):
        mogrt_text.bake(_ppro_template(tmp_path / "t.mogrt"), {}, styles={"9": {"size": 10}})
    with pytest.raises(ValueError, match="no text layer"):  # After Effects: no Premiere Source Text
        mogrt_text.bake(_template(tmp_path / "ae.mogrt"), {}, styles={"Title": {"size": 10}})
