"""Automated live test suite against a running Premiere Pro session with CutDeck panel.

Skipped automatically if Premiere Pro / CutDeck panel is not connected.
To run:
    1. Start the helper: python -m cutdeck.xml_bridge
    2. Open Premiere Pro with a project open, and open the CutDeck panel
    3. Run: python -m pytest tests/test_cutdeck_live_premiere.py -v
"""
import asyncio
import pytest

from cutdeck.ai_backend import Backend
from cutdeck.driver_commands import COMMANDS


@pytest.fixture(scope="module")
def live_backend():
    backend = Backend()
    try:
        status = asyncio.run(backend.premiere_status())
    except Exception as exc:
        pytest.skip(f"CutDeck helper not running or unreachable: {exc}")
    if not status.get("connected"):
        pytest.skip("Premiere Pro CutDeck panel is not open/connected to the helper")
    return backend


def test_live_premiere_connection_and_commands(live_backend):
    status = asyncio.run(live_backend.premiere_status())
    assert status["connected"] is True
    # Verify all tabled commands are offered by the live panel
    for cmd in COMMANDS:
        assert cmd in status["commands"]


def test_live_read_sequence(live_backend):
    res = asyncio.run(live_backend.premiere("read_sequence"))
    assert "name" in res
    assert "sequence_id" in res
    assert "ticks_per_frame" in res
    assert res["video_track_count"] >= 0
    assert res["audio_track_count"] >= 0


def test_live_inspect_selection(live_backend):
    res = asyncio.run(live_backend.premiere("inspect_selection"))
    assert "sequence_name" in res
    assert "selected_count" in res
    assert isinstance(res["items"], list)
    assert res["selected_count"] == len(res["items"])


def test_live_run_timing_probe(live_backend):
    res = asyncio.run(live_backend.premiere("run_probe", {"probe": "timing"}))
    assert res["probe"] == "timing"
    report = res["report"]
    assert report.get("probe") == "marks-and-timing"
    assert report.get("complete") is True
