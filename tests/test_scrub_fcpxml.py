"""Tests for scripts/scrub_fcpxml.py (HANDOFF_CUTDECK_XML_RECUT.md Phase 1).

The scrubber's whole contract is asymmetric: strings that identify the editor's
real project are rewritten, numbers that describe the sequence's structure are
not. Both halves are tested, because a scrubber that quietly changed a frame
number would poison every fixture built with it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from scrub_fcpxml import scrub  # noqa: E402

# Two clipitems sharing one source file (the second <file> is an id-only stub,
# Premiere's convention) plus a clipitem name carrying a CutDeck round-trip key.
SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="5">
  <sequence id="seq-1">
    <name>ClientCorp Q3 Launch v4 FINAL</name>
    <duration>1500</duration>
    <rate><timebase>25</timebase><ntsc>FALSE</ntsc></rate>
    <media>
      <video>
        <track>
          <clipitem id="v0">
            <name>cd042_p007_s0012</name>
            <start>0</start><end>250</end><in>100</in><out>350</out>
            <file id="file-1">
              <name>A_CAM_0031.MP4</name>
              <pathurl>file://localhost/E%3A/Clients/ClientCorp/A_CAM_0031.MP4</pathurl>
            </file>
          </clipitem>
          <clipitem id="v1">
            <name>cd042_p007_s0014</name>
            <start>250</start><end>500</end><in>600</in><out>850</out>
            <file id="file-1"/>
          </clipitem>
        </track>
        <track>
          <clipitem id="v2">
            <name>cd042_p007_s0012</name>
            <start>0</start><end>250</end><in>0</in><out>250</out>
            <file id="file-2">
              <name>B_CAM_0007.MP4</name>
              <pathurl>file://localhost/E%3A/Clients/ClientCorp/B_CAM_0007.MP4</pathurl>
            </file>
          </clipitem>
        </track>
      </video>
    </media>
  </sequence>
</xmeml>
"""

_NUMERIC_TAGS = ("start", "end", "in", "out", "duration", "timebase")


def _numbers(xml_text: str) -> list[tuple[str, str]]:
    root = ET.fromstring(xml_text)
    return [(el.tag, (el.text or "").strip())
            for el in root.iter() if el.tag in _NUMERIC_TAGS]


def _ids(xml_text: str) -> list[str]:
    root = ET.fromstring(xml_text)
    return [el.get("id", "") for el in root.iter() if el.get("id")]


def test_no_real_absolute_path_survives():
    out, _, _ = scrub(SAMPLE)
    assert "ClientCorp" not in out
    assert "A_CAM_0031" not in out
    assert "E%3A" not in out


def test_shared_source_still_shares_one_dummy_path():
    """Two clipitems on one source must still look like one source afterwards —
    that de-duplication is exactly the structure the recut parser has to read."""
    out, mapping, _ = scrub(SAMPLE)
    assert len(mapping) == 2, mapping          # two distinct sources, not three clipitems
    urls = re.findall(r"<pathurl>([^<]+)</pathurl>", out)
    assert len(urls) == 2 and len(set(urls)) == 2


def test_extension_is_preserved():
    _, mapping, _ = scrub(SAMPLE)
    assert all(dummy.lower().endswith(".mp4") for dummy in mapping.values())


def test_every_number_and_id_is_byte_identical():
    out, _, _ = scrub(SAMPLE)
    assert _numbers(out) == _numbers(SAMPLE)
    assert _ids(out) == _ids(SAMPLE)


def test_clipitem_names_are_left_alone():
    """<clipitem><name> carries CutDeck's round-trip key — scrubbing it would
    break the recut tests that match plan spans back to clips."""
    out, _, _ = scrub(SAMPLE)
    assert out.count("cd042_p007_s0012") == 2
    assert "cd042_p007_s0014" in out


def test_sequence_and_file_names_are_neutralized():
    out, _, names_changed = scrub(SAMPLE)
    assert names_changed == 3          # 1 sequence + 2 files
    assert "Q3 Launch" not in out
    assert "fixture sequence" in out


def test_output_is_still_parseable_xmeml():
    out, _, _ = scrub(SAMPLE)
    root = ET.fromstring(out)
    assert root.tag == "xmeml" and root.get("version") == "5"
    assert out.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>')
