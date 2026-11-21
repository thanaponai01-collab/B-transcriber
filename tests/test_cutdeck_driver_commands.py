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


def test_build_sequence_needs_the_open_project_and_saves_only_when_asked():
    prepare = driver_commands.COMMANDS["build_sequence"].prepare
    item = {"id": "V1@0", "media": "D:\a.mp4", "in_ticks": "0", "out_ticks": "254016000000", "at_ticks": "0", "v": 0, "a": 0}
    args = {"project": "E:\Shows\hks.prproj", "base": "1 YOUTUBE D1", "name": "HKS build", "items": [item]}
    assert prepare(args, None) == {**args, "save": False}
    assert prepare({**args, "save": True}, None)["save"] is True
    for bad in ({"project": None}, {"project": "hks.prproj"}, {"project": "E:\Shows\hks.mp4"}, {"save": "yes"}):
        try:
            prepare({**args, **bad}, None)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")


def test_build_sequence_disable_tracks_is_optional_and_checked():
    prepare = driver_commands.COMMANDS["build_sequence"].prepare
    item = {"id": "V1@0", "media": "D:\a.mp4", "in_ticks": "0", "out_ticks": "254016000000", "at_ticks": "0", "v": 0, "a": 0}
    args = {"project": "E:\Shows\hks.prproj", "base": "b", "name": "n", "items": [item]}
    assert "disable_tracks" not in prepare(args, None)
    off = {"video": [2], "audio": [1, 2]}
    assert prepare({**args, "disable_tracks": off}, None)["disable_tracks"] == off
    for bad in ([2], {"video": [-1]}, {"video": ["2"]}, {"titles": [0]}):
        try:
            prepare({**args, "disable_tracks": bad}, None)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")


def test_build_sequence_mark_whole_is_opt_in():
    prepare = driver_commands.COMMANDS["build_sequence"].prepare
    item = {"id": "V1@0", "media": "D:\a.mp4", "in_ticks": "0", "out_ticks": "254016000000", "at_ticks": "0", "v": 0, "a": 0}
    args = {"project": "E:\Shows\hks.prproj", "base": "b", "name": "n", "items": [item]}
    assert "mark_whole" not in prepare(args, None)
    assert prepare({**args, "mark_whole": True}, None)["mark_whole"] is True
    try:
        prepare({**args, "mark_whole": "yes"}, None)
    except ValueError:
        return
    raise AssertionError("accepted mark_whole='yes'")


def test_cut_copy_checks_names_and_frames():
    prepare = driver_commands.COMMANDS["cut_copy"].prepare
    ok = {"sequence_name": "YT editing", "result_name": "short", "cuts": {"ticks_per_frame": 8467200000, "cuts_frames": [[0, 10], [20, 30]]}}
    assert prepare(ok, None)["cuts"] == {"ticks_per_frame": "8467200000", "cuts_frames": [[0, 10], [20, 30]]}
    for bad in ({"result_name": "YT editing"}, {"cuts": {"ticks_per_frame": 1, "cuts_frames": [[10, 5]]}},
                {"cuts": {"ticks_per_frame": 1, "cuts_frames": [[0, 10], [5, 20]]}}, {"cuts": {"cuts_frames": [[0, 1]]}}):
        try:
            prepare({**ok, **bad}, None)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")


def test_build_sequence_into_mode_checks():
    prepare = driver_commands.COMMANDS["build_sequence"].prepare
    item = {"id": "p", "media": "D:\a.mp4", "in_ticks": "0", "out_ticks": "1", "at_ticks": "0", "v": 0, "a": None}
    args = {"project": "E:\Shows\hks.prproj", "base": "cut", "name": "cut", "items": [item], "into": True,
            "steps": [{"op": "move", "from_ticks": "0", "to_ticks": "10", "dt_ticks": "-5"}, {"op": "lift", "from_ticks": "0", "to_ticks": "1"}],
            "restyle": [{"kind": "video", "track": 1, "from_ticks": "0", "to_ticks": "9", "enabled": True}]}
    out = prepare(args, None)
    assert prepare({**args, "steps": [{"op": "clone", "from_ticks": "0", "to_ticks": "1", "dt_ticks": "5",
                                       "tracks": {"video": [5]}}]}, None)["steps"][0]["tracks"] == {"video": [5]}
    assert prepare({**args, "steps": [{"op": "trim", "from_ticks": "0", "to_ticks": "1", "end_ticks": "9"}]}, None)["steps"][0]["end_ticks"] == "9"
    assert out["into"] is True and out["steps"] == args["steps"] and out["restyle"] == args["restyle"]
    for bad in ({"name": "other"}, {"steps": [{"op": "move", "from_ticks": "5", "to_ticks": "1", "dt_ticks": "1"}]},
                {"steps": [{"op": "clone", "from_ticks": "0", "to_ticks": "1"}]}, {"steps": [{"op": "trim", "from_ticks": "0", "to_ticks": "1"}]},
                {"restyle": [{"kind": "title", "track": 0, "from_ticks": "0", "to_ticks": "1"}]},
                {"steps": [{"op": "clone", "from_ticks": "0", "to_ticks": "1", "dt_ticks": "1", "tracks": {"title": [0]}}]},
                {"steps": [{"op": "clone", "from_ticks": "0", "to_ticks": "1", "dt_ticks": "1", "tracks": {"video": [-1]}}]},
                {"steps": [{"op": "trim", "from_ticks": "0", "to_ticks": "1"}]},
                {"into": False}):
        try:
            prepare({**args, **bad}, None)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")
