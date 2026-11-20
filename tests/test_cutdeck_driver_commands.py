"""One table owns the Premiere driver commands (docs/arch-design-helper-v3.md move 1)."""
import asyncio
from pathlib import Path
import re

from cutdeck import driver_commands
from cutdeck.ai_backend import Backend
from cutdeck.mcp_server import create_server

DRIVER_JS = Path(__file__).resolve().parent.parent / "uxp" / "cutdeck" / "features" / "driver.js"


def test_panel_driver_offers_exactly_the_tabled_commands():
    array = re.search(r"const COMMANDS = \[([^\]]*)\]", DRIVER_JS.read_text(encoding="utf-8")).group(1)
    assert sorted(re.findall(r'"(\w+)"', array)) == sorted(driver_commands.COMMANDS)


def test_every_command_is_an_agent_tool():
    listed = {f"premiere_{name}" for name in driver_commands.COMMANDS}
    assert listed <= set(Backend().capabilities()["tools"])
    tools = asyncio.run(create_server(Backend()).list_tools())
    assert listed <= {tool.name for tool in tools}


def test_export_sequence_checks_paths_and_never_overwrites(tmp_path):
    prepare = driver_commands.COMMANDS["export_sequence"].prepare
    preset = tmp_path / "BAS4.epr"
    preset.write_text("<PremiereData/>", encoding="utf-8")
    out = tmp_path / "reel.mp4"
    assert prepare({"output_file": str(out), "preset_file": str(preset)}, None) == {
        "output_file": str(out), "preset_file": str(preset), "queue": "premiere", "start": True}
    assert prepare({"output_file": str(out), "preset_file": str(preset), "start": False}, None)["start"] is False
    assert prepare({"output_file": str(out), "preset_file": str(preset), "queue": "ame"}, None)["queue"] == "ame"
    bad = [
        {"output_file": str(out), "preset_file": str(preset), "queue": "later"},     # unknown queue
        {"output_file": "reel.mp4", "preset_file": str(preset)},                     # relative
        {"output_file": str(out), "preset_file": str(tmp_path / "missing.epr")},      # no preset
        {"output_file": str(tmp_path / "nope" / "reel.mp4"), "preset_file": str(preset)},  # no folder
    ]
    out.write_bytes(b"x")
    bad.append({"output_file": str(out), "preset_file": str(preset)})                # exists
    for args in bad:
        try:
            prepare(args, None)
        except ValueError:
            continue
        raise AssertionError(f"accepted {args}")


def test_anchor_and_align_take_an_optional_text_layer():
    anchor = driver_commands.COMMANDS["set_anchor"]
    align = driver_commands.COMMANDS["align_clips"]
    assert anchor.prepare({"target": "top-left"}, None) == {"target": "top-left"}
    assert anchor.prepare({"target": "top-left", "layer": 1}, None) == {"target": "top-left", "layer": 1}
    assert align.prepare({"edge": "left", "layer": 0}, None) == {"edge": "left", "to": "frame", "layer": 0}
    for bad in (-1, 1.5, True, "1"):
        try:
            align.prepare({"edge": "left", "layer": bad}, None)
        except ValueError:
            continue
        raise AssertionError(f"layer {bad!r} accepted")
    assert anchor.cli_target[1]("top-left 1") == {"target": "top-left", "layer": 1}
    assert align.cli_target[1]("left frame 1") == {"edge": "left", "to": "frame", "layer": 1}
