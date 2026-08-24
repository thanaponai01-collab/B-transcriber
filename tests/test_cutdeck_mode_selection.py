"""Phase 4 acceptance — cutdeck.mode config selection
(docs/HANDOFF_CUTDECK_LIVE_SEQUENCE.md).
"""

import pytest

from cutdeck.export_mode import (
    MODE_IN_PLACE,
    MODE_NEW_SEQUENCE,
    exporter_for_mode,
    mode_from_config,
)
from cutdeck.jsx_export import to_jsx
from cutdeck.xml_export import to_xml


def test_new_sequence_mode_selects_xml_export():
    assert exporter_for_mode(MODE_NEW_SEQUENCE) is to_xml


def test_in_place_mode_selects_jsx_export():
    assert exporter_for_mode(MODE_IN_PLACE) is to_jsx


def test_unrecognized_mode_raises():
    with pytest.raises(ValueError, match="unrecognized cutdeck.mode"):
        exporter_for_mode("something_else")


def test_mode_from_config_defaults_to_new_sequence():
    assert mode_from_config({}) == MODE_NEW_SEQUENCE
    assert mode_from_config({"cutdeck": {}}) == MODE_NEW_SEQUENCE


def test_mode_from_config_reads_explicit_value():
    assert mode_from_config({"cutdeck": {"mode": "in_place"}}) == MODE_IN_PLACE
