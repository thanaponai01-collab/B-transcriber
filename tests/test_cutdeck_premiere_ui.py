"""Pixel logic of cutdeck/premiere_ui.py on real Premiere 27.0 captures (live 2026-11-21).

Fixtures (tests/fixtures/premiere_ui/): the Clip Speed/Duration dialog as opened (speed_tab0),
after one Tab (speed_tab1: focus ring on Reverse) and with Ripple edit ticked (speed_r9s); the
Tools panel (tools_panel); the Program Monitor area of the window with a "OLD TEXT" Graphic on and
off (monitor_on/off) and the rendered frames, halved, on and off (frame_on/off).
"""
from pathlib import Path

import pytest
from PIL import Image

pytest.importorskip("scipy")
from cutdeck import premiere_ui as ui  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "premiere_ui"


def _img(name):
    return Image.open(FIX / f"{name}.png").convert("RGB")


def test_focus_ring_marks_the_focused_checkbox_only():
    assert ui.ring_at(_img("speed_tab1"), *ui.REVERSE_BOX) > 30
    assert ui.ring_at(_img("speed_tab0"), *ui.REVERSE_BOX) < 30
    assert ui.ring_at(_img("speed_tab1"), *ui.RIPPLE_BOX) < 30


def test_ticked_box_is_told_from_an_empty_one():
    assert ui.ticked(_img("speed_r9s"), *ui.RIPPLE_BOX)
    assert not ui.ticked(_img("speed_tab0"), *ui.RIPPLE_BOX)
    assert not ui.ticked(_img("speed_tab0"), *ui.REVERSE_BOX)


def test_selection_tool_is_found_by_its_glyph():
    x, y = ui.find_selection_tool(_img("tools_panel"))
    assert abs(x - 33) <= 3 and abs(y - 32) <= 3  # the arrow at the top of the Tools panel


def test_selection_tool_missing_is_refused():
    with pytest.raises(RuntimeError, match="Selection tool"):
        ui.find_selection_tool(_img("frame_on"))


def test_text_is_located_in_the_monitor_from_the_frames():
    where = ui.locate_in_window(_img("frame_on"), _img("frame_off"), _img("monitor_on"), _img("monitor_off"))
    x, y = where["point"]
    assert abs(x - 320) <= 6 and abs(y - 223) <= 4  # "OLD TEXT" in the monitor (live click point 1610, 313)
    assert abs(where["scale"] - 0.408) < 0.03


def test_frames_without_a_change_are_refused():
    with pytest.raises(RuntimeError, match="draws nothing"):
        ui.locate_in_window(_img("frame_on"), _img("frame_on"), _img("monitor_on"), _img("monitor_off"))


def test_paste_attributes_boxes_read_from_the_dialog():
    image = _img("paste_attributes")  # Paste Attributes as opened, live 2026-11-22: Motion, Opacity, Effects ticked
    assert image.size == ui.PASTE_SIZE
    assert all(ui.ticked(image, *box) for box in ui.PASTE_BOXES.values())
    assert not ui.ticked(image, 44, 197)  # Time Remapping, unticked in the same capture


def test_paste_attributes_reports_clips_that_differ(monkeypatch):
    import asyncio

    def clip(cid, opacity):
        return {"id": cid, "effects": [{"match_name": "AE.ADBE Opacity", "params": [{"index": 0, "value": opacity}]}]}

    calls = []

    async def premiere(command, args=None):
        calls.append(command)
        if command == "read_timeline":
            return {"tracks": [{"clips": [clip("V4@0", 80), clip("V4@10", 80), clip("V4@20", 100)]}]}
        return {}

    async def run_focused(premiere_, focus, sequence, action):
        return {"sequence": "S"}

    monkeypatch.setattr(ui.keys, "run_focused", run_focused)
    out = asyncio.run(ui.paste_attributes(premiere, {"source": "V4@0", "clips": ["V4@10", "V4@20", "V4@30"]}))
    assert out["matching"] == 1 and out["differ"] == ["V4@20", "V4@30"]
    assert calls == ["select_clips", "select_clips", "read_timeline"]


def test_paste_attributes_arguments_drop_the_source_and_need_a_target():
    from cutdeck.driver_commands import COMMANDS
    parse = COMMANDS["paste_attributes"].prepare
    assert parse({"source": "V4@0", "clips": ["V4@0", "V4@10"]}, None)["clips"] == ["V4@10"]
    with pytest.raises(ValueError, match="other than source"):
        parse({"source": "V4@0", "clips": ["V4@0"]}, None)
