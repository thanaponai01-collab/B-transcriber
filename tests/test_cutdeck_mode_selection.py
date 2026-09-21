"""Phase 4 acceptance — cutdeck.mode config selection
(docs/HANDOFF_CUTDECK_LIVE_SEQUENCE.md; the ExtendScript ``in_place`` mode
was retired in issue #23, ``mark``/``assemble`` in issue #25).
"""

import pytest

from cutdeck.export_mode import (
    MODE_NEW_SEQUENCE,
    MODE_RECUT_SEQUENCE,
    exporter_for_mode,
    mode_from_config,
)
from cutdeck.xml_export import to_xml
from cutdeck.xml_recut import recut


def test_new_sequence_mode_selects_xml_export():
    assert exporter_for_mode(MODE_NEW_SEQUENCE) is to_xml


def test_recut_sequence_mode_selects_xml_recut():
    assert exporter_for_mode(MODE_RECUT_SEQUENCE) is recut


def test_unrecognized_mode_raises():
    with pytest.raises(ValueError, match="unrecognized cutdeck.mode"):
        exporter_for_mode("something_else")


def test_in_place_mode_no_longer_recognized():
    """jsx_export.py / the ExtendScript in-place mode is retired (issue #23) —
    the old mode value must fail loudly rather than silently resolving."""
    with pytest.raises(ValueError, match="unrecognized cutdeck.mode"):
        exporter_for_mode("in_place")


def test_mode_from_config_defaults_to_new_sequence():
    assert mode_from_config({}) == MODE_NEW_SEQUENCE
    assert mode_from_config({"cutdeck": {}}) == MODE_NEW_SEQUENCE


def test_mode_from_config_reads_explicit_value():
    assert mode_from_config({"cutdeck": {"mode": "recut_sequence"}}) == MODE_RECUT_SEQUENCE


def test_retired_mark_and_assemble_modes_fail_loudly():
    for retired in ("mark", "assemble"):
        with pytest.raises(ValueError, match="unrecognized cutdeck.mode"):
            exporter_for_mode(retired)
