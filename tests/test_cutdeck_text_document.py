"""The typed Source Text codec: every Premiere-saved FlatBuffer blob decodes, re-encodes and decodes
the same, and the named fields mean what the Properties panel showed when they were saved."""
import base64
import json
import struct
from pathlib import Path

import pytest

from cutdeck import text_document as td

FIXTURES = Path(__file__).parent / "fixtures"
PLAIN = json.loads((FIXTURES / "source_text_blobs.json").read_text(encoding="utf-8"))
STYLED = json.loads((FIXTURES / "source_text_styled.json").read_text(encoding="utf-8"))
BLOBS = {k: base64.b64decode(v) for k, v in {**PLAIN, **STYLED}.items()
         if "," not in v}  # "<ticks>,<blob>" entries are keyframe lists, not blobs
FLAT = {k: b for k, b in BLOBS.items() if b[8:12] == struct.pack("<I", td.TAG)}


def test_fixtures_cover_both_forms():
    assert len(FLAT) >= 20 and "J1_json_centered_two_lines" not in FLAT


@pytest.mark.parametrize("name", sorted(FLAT))
def test_round_trip(name):
    doc = td.decode(FLAT[name])
    again = td.encode(doc)
    assert td.decode(again) == doc
    assert struct.unpack_from("<Q", again, 0)[0] == len(again) - 12


def test_json_form_is_refused():
    with pytest.raises(ValueError):
        td.decode(BLOBS["J1_json_centered_two_lines"])


def test_field_meanings_from_panel_saves():
    red = td.decode(FLAT["C1_red"])["runs"][0]["style"]
    assert red["fill"] == {"g": 0, "b": 0}  # FF0000: the red channel is left at its default 255
    assert td.decode(FLAT["A1_center"])["alignment"] == 2
    assert td.decode(FLAT["S5_leading_150"])["leading"] == 150.0
    runs = td.decode(FLAT["I1_italic_ab_underline_cd"])["runs"]
    assert [r["text"] for r in runs] == ["ab\r", "cd"]
    assert "underline" not in runs[0]["style"] and runs[1]["style"]["underline"] == 1

    quote = td.decode(FLAT["P3_quote_open_bg_shadows"])
    assert quote["fonts"] == ["DBEEStrokeX"]
    style = quote["runs"][0]["style"]
    assert style["size"] == 120.0 and style["caps"] == 2 and style["baseline"] == 2
    assert style["fill"] == {"r": 32, "g": 110, "b": 143} and style["stroke_width"] == 8.0
    assert (quote["background_on"], quote["background_opacity"], quote["background_size"],
            quote["background_corner"]) == (1, 40.0, 12.0, 9.0)
    assert (quote["shadow_opacity"], quote["shadow_angle"], quote["shadow_distance"],
            quote["shadow_size"], quote["shadow_blur"]) == (55.0, 45.0, 3.0, 2.0, 60.0)
    extra = quote["shadows"][0]
    assert (extra["opacity"], extra["angle"], extra["distance"], extra["size"]) == (30.0, 90.0, 5.0, 4.0)

    close = td.decode(FLAT["P4_quote_close_rtl_underline"])
    assert close["rtl"] == 1 and close["alignment"] == 1
    assert close["runs"][0]["style"]["underline"] == 1


def test_edit_and_encode():
    doc = td.decode(FLAT["P2_top_line_thai"])
    doc["runs"][0]["text"] = "ข้อความใหม่"
    doc["runs"][0]["style"]["fill"] = {"r": 255, "g": 0, "b": 0}
    doc["alignment"] = 2
    back = td.decode(td.encode(doc))
    assert back["runs"][0]["text"] == "ข้อความใหม่"
    assert back["runs"][0]["style"]["fill"] == {"r": 255, "g": 0, "b": 0}
    assert back["alignment"] == 2


def test_unmapped_slot_is_refused(monkeypatch):
    monkeypatch.delitem(td.DOCUMENT, 1)  # as if Premiere wrote a slot the schema never saw
    with pytest.raises(td.UnmappedField, match=r"Document\.f1 "):
        td.decode(FLAT["C1_red"])
    with pytest.raises(td.UnmappedField):
        td.encode({"runs": [], "no_such_field": 1})


def test_a_blob_whose_offsets_lead_nowhere_is_refused():
    blob = bytearray(FLAT["C1_red"])
    struct.pack_into("<I", blob, 12, 0x7F000000)  # root offset past the end
    with pytest.raises(td.UnmappedField, match="not mapped"):
        td.decode(bytes(blob))
