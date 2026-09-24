"""tests/test_cutdeck_text_properties.py — tests for cutdeck/text_properties.py"""

import base64
import gzip
from pathlib import Path

import pytest

from cutdeck.text_properties import (
    decompress_prproj,
    extract_graphic_texts_from_xml,
    extract_project_text_properties,
    measure_text_bounds,
    parse_source_text_blob,
    resolve_font_file,
    tokenize_font,
)


def test_decompress_prproj_plain_and_gzip():
    plain = "<PremiereData></PremiereData>".encode("utf-8")
    assert decompress_prproj(plain) == "<PremiereData></PremiereData>"

    gzipped = gzip.compress(plain)
    assert decompress_prproj(gzipped) == "<PremiereData></PremiereData>"


def test_parse_source_text_blob_extracts_font_and_text():
    # Build a simulated binary buffer with PostScript font name and text
    font_bytes = b"LucidaCalligraphy-Italic\x00"
    text_content = "Hello World".encode("utf-16le")
    blob = b"\x00\x01\x02\x03" + font_bytes + b"\x04\x05" + text_content + b"\x00\x00"

    parsed = parse_source_text_blob(blob)
    assert parsed["font_name"] == "LucidaCalligraphy-Italic"
    assert parsed["text"] == "Hello World"
    assert parsed["raw_length"] == len(blob)


def test_extract_graphic_texts_from_xml():
    # Create sample binary blob and base64 encode it
    font_bytes = b"THSarabunNew-Bold\x00"
    text_content = "วิดีโอทดสอบ 2026".encode("utf-16le")
    blob = b"\xaa\xbb" + font_bytes + b"\xcc\xdd" + text_content + b"\x00\x00"
    b64_val = base64.b64encode(blob).decode("ascii")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PremiereData Version="3">
  <Component>
    <DisplayName>Title Text</DisplayName>
    <MatchName>AE.ADBE Text</MatchName>
    <ComponentParams>
      <ArbVideoComponentParam>
        <ParamName>Source Text</ParamName>
        <StartKeyframeValue>{b64_val}</StartKeyframeValue>
      </ArbVideoComponentParam>
    </ComponentParams>
  </Component>
  <Component>
    <DisplayName>Motion</DisplayName>
    <MatchName>AE.ADBE Motion</MatchName>
  </Component>
</PremiereData>"""

    results = extract_graphic_texts_from_xml(xml)
    assert len(results) == 1
    assert results[0]["component_name"] == "Title Text"
    assert results[0]["font_name"] == "THSarabunNew-Bold"
    assert results[0]["text"] == "วิดีโอทดสอบ 2026"


def test_extract_project_text_properties_file(tmp_path: Path):
    font_bytes = b"Arial-BoldMT\x00"
    text_content = "Sub-title text".encode("utf-16le")
    blob = b"\x01\x02" + font_bytes + b"\x03" + text_content
    b64_val = base64.b64encode(blob).decode("ascii")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PremiereData Version="3">
  <Component>
    <DisplayName>Text 1</DisplayName>
    <MatchName>AE.ADBE Text</MatchName>
    <ComponentParams>
      <ArbVideoComponentParam>
        <ParamName>Source Text</ParamName>
        <StartKeyframeValue>{b64_val}</StartKeyframeValue>
      </ArbVideoComponentParam>
    </ComponentParams>
  </Component>
</PremiereData>"""

    prproj_file = tmp_path / "test_project.prproj"
    prproj_file.write_bytes(gzip.compress(xml.encode("utf-8")))

    extracted = extract_project_text_properties(prproj_file)
    assert len(extracted) == 1
    assert extracted[0]["component_name"] == "Text 1"
    assert extracted[0]["font_name"] == "Arial-BoldMT"
    assert extracted[0]["text"] == "Sub-title text"

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
