"""One table owns the Premiere driver commands (docs/arch-design-helper-v3.md move 1)."""
import asyncio
import json
import subprocess
from pathlib import Path

from cutdeck import driver_commands
from cutdeck.ai_backend import Backend
from cutdeck.mcp_server import create_server

DRIVER_JS = Path(__file__).resolve().parent.parent / "uxp" / "cutdeck" / "features" / "driver.js"


def test_panel_driver_offers_exactly_the_tabled_commands():
    # The commands the panel registers are its handler names, read from the real module.
    script = ("const { createDriver } = require(process.argv[1]);"
              "console.log(JSON.stringify(createDriver({ ppro: {}, ctl: {} }).commands));")
    out = subprocess.run(["node", "-e", script, str(DRIVER_JS)], capture_output=True, text=True, check=True).stdout
    assert sorted(json.loads(out)) == sorted(driver_commands.PANEL_COMMANDS)


def test_every_command_is_an_agent_tool():
    listed = {f"premiere_{name}" for name in driver_commands.COMMANDS}
    assert listed <= set(Backend().capabilities()["tools"])
    tools = asyncio.run(create_server(Backend()).list_tools())
    assert listed <= {tool.name for tool in tools}


def test_a_tool_sends_what_it_was_given_minus_unset_optionals():
    class Recorder(Backend):
        def __init__(self):
            super().__init__(1)
            self.calls = []

        async def premiere(self, command, args=None):
            self.calls.append((command, args))
            return {}

    backend = Recorder()
    server = create_server(backend)
    calls = [("premiere_set_in_out", {"in_ticks": "0"}),
             ("premiere_menu_command", {"path": "Edit > Undo", "focus": None}),  # an explicit null focus is kept
             ("premiere_read_timeline", {}),
             ("premiere_build_sequence", {"project": "E:/a.prproj", "base": "b", "name": "n", "items": [],
                                          "options": {"mark_whole": True}})]
    for tool, args in calls:
        asyncio.run(server.call_tool(tool, args))
    assert backend.calls == [
        ("set_in_out", {"in_ticks": "0"}),
        ("menu_command", {"path": "Edit > Undo", "focus": None}),
        ("read_timeline", {"effects": False}),
        ("build_sequence", {"project": "E:/a.prproj", "base": "b", "name": "n", "items": [], "save": False,
                            "options": {"mark_whole": True}}),
    ]
    merged = driver_commands.COMMANDS["build_sequence"].prepare(
        {"project": "E:/a.prproj", "base": "b", "name": "n",
         "items": [{"media": "D:/a.mp4", "in_ticks": "0", "out_ticks": "1", "at_ticks": "0", "v": 0}],
         "options": {"mark_whole": True}}, None)
    assert merged["mark_whole"] is True and "options" not in merged


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


def test_transform_tools_take_what_their_descriptions_offer():
    field = driver_commands.COMMANDS["set_transform_field"].prepare
    for name in ("crop-left", "crop-bottom", "opacity", "scale-width", "uniform-scale", "anti-flicker"):
        assert field({"field": name, "value": 1}, None) == {"field": name, "value": 1.0}
    align = driver_commands.COMMANDS["align_clips"].prepare
    assert align({"edge": "left", "to": "group"}, None) == {"edge": "left", "to": "group"}
    for bad in ({"field": "blend-mode", "value": 1}, {"field": "opacity", "value": "x"}):
        try:
            field(bad, None)
        except ValueError:
            continue
        raise AssertionError(f"{bad} accepted")


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


def test_duplicate_sequence_checks_names_and_empty():
    prepare = driver_commands.COMMANDS["duplicate_sequence"].prepare
    ok = {"sequence_name": "2 FACEBOOK D1", "result_name": "2 FACEBOOK D1 Copy 01 (CutDeck)"}
    assert prepare(ok, None) == {**ok, "empty": False}
    assert prepare({**ok, "empty": True}, None)["empty"] is True
    for bad in ({"result_name": "2 FACEBOOK D1"}, {"result_name": " "}, {"sequence_name": None}, {"empty": "yes"}):
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
    assert prepare({**args, "steps": [{"op": "clone", "from_ticks": "0", "to_ticks": "1", "dt_ticks": "-5",
                                       "tracks": {"video": [0]}, "v_offset": 4}]}, None)["steps"][0]["v_offset"] == 4
    assert prepare({**args, "steps": [{"op": "clone", "from_ticks": "0", "to_ticks": "1", "dt_ticks": "0",
                                       "v_offset": -2}]}, None)["steps"][0]["v_offset"] == -2  # Upgrade lands Graphics on top
    assert prepare({**args, "items": [], "steps": []}, None)["restyle"] == args["restyle"]  # restyle only
    assert out["into"] is True and out["steps"] == args["steps"] and out["restyle"] == args["restyle"]
    for bad in ({"name": "other"}, {"steps": [{"op": "move", "from_ticks": "5", "to_ticks": "1", "dt_ticks": "1"}]},
                {"steps": [{"op": "clone", "from_ticks": "0", "to_ticks": "1"}]}, {"steps": [{"op": "trim", "from_ticks": "0", "to_ticks": "1"}]},
                {"restyle": [{"kind": "title", "track": 0, "from_ticks": "0", "to_ticks": "1"}]},
                {"steps": [{"op": "clone", "from_ticks": "0", "to_ticks": "1", "dt_ticks": "1", "tracks": {"title": [0]}}]},
                {"steps": [{"op": "clone", "from_ticks": "0", "to_ticks": "1", "dt_ticks": "1", "tracks": {"video": [-1]}}]},
                {"steps": [{"op": "move", "from_ticks": "0", "to_ticks": "1", "dt_ticks": "1", "v_offset": 1}]},
                {"steps": [{"op": "trim", "from_ticks": "0", "to_ticks": "1"}]},
                {"into": False}):
        try:
            prepare({**args, **bad}, None)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")


def test_control_commands_check_ids_ticks_and_ops(tmp_path):
    c = driver_commands.COMMANDS
    edits = [{"clip": "V1@0", "op": "move", "dt_ticks": "-254016000000"}, {"clip": "A2@5", "op": "remove"}]
    assert c["edit_clips"].prepare({"edits": edits}, None) == {"edits": [
        {"clip": "V1@0", "op": "move", "dt_ticks": "-254016000000"}, {"clip": "A2@5", "op": "remove", "ripple": False}]}
    assert c["read_timeline"].prepare({"tracks": ["V1", "A2"], "from_ticks": "0", "to_ticks": "5"}, None) == {
        "effects": False, "tracks": ["V1", "A2"], "from_ticks": "0", "to_ticks": "5"}
    assert c["select_clips"].prepare({"clips": [], "sequence": "Edit"}, None) == {"sequence": "Edit", "clips": []}
    assert c["set_param"].prepare({"clip": "V1@0", "component": 1, "param": 0, "value": [0.5, 0.5]}, None)["value"] == [0.5, 0.5]
    media = tmp_path / "b.mp4"
    media.write_bytes(b"x")
    assert c["place_media"].prepare({"media": str(media), "at_ticks": "0", "v": 0, "a": 2}, None)["mode"] == "overwrite"
    donor = tmp_path / "d.prproj"
    donor.write_bytes(b"x")
    ids = ["8e214d18-932a-4ad9-b6aa-663740045e4b"]
    assert c["import_sequences"].prepare({"path": str(donor), "sequence_ids": ids}, None) == {"path": str(donor), "sequence_ids": ids}
    bad = [
        ("edit_clips", {"edits": [{"clip": "V0@0", "op": "move", "dt_ticks": "1"}]}),       # track 0
        ("edit_clips", {"edits": [{"clip": "V1@0", "op": "razor"}]}),                       # not an op
        ("edit_clips", {"edits": [{"clip": "V1@0", "op": "trim_in", "in_ticks": 5}]}),      # ticks not a string
        ("edit_clips", {"edits": [{"clip": "V1@0", "op": "disable"}, {"clip": "V1@0", "op": "enable"}]}),  # twice
        ("set_in_out", {"in_ticks": "9", "out_ticks": "3"}),
        ("set_in_out", {}),
        ("set_param", {"clip": "V1@0", "component": 1, "param": 0, "value": {"x": 1}}),
        ("place_media", {"media": str(media), "nest": "Edit", "at_ticks": "0", "v": 0, "a": 0}),
        ("place_media", {"media": str(tmp_path / "none.mp4"), "at_ticks": "0", "v": 0, "a": 0}),
        ("place_media", {"media": str(media), "at_ticks": "0", "v": 0, "a": -1}),       # -1 lands on A1
        ("set_track_mute", {"track": "V0", "muted": True}),
        ("read_timeline", {"effects": "all"}),
        ("read_timeline", {"tracks": ["V0"]}),
        ("read_timeline", {"from_ticks": "9", "to_ticks": "3"}),
        ("import_sequences", {"path": str(media), "sequence_ids": ["8e214d18-932a-4ad9-b6aa-663740045e4b"]}),  # not a .prproj
        ("import_sequences", {"path": str(donor), "sequence_ids": []}),
        ("import_sequences", {"path": str(donor), "sequence_ids": ["Gate4"]}),
    ]
    for name, args in bad:
        try:
            c[name].prepare(args, None)
        except ValueError:
            continue
        raise AssertionError(f"{name} accepted {args}")


def test_build_sequence_takes_no_items_only_for_steps_on_a_copy():
    import pytest
    from cutdeck.driver_commands import COMMANDS
    prepare = COMMANDS["build_sequence"].prepare
    base = {"project": "C:/p.prproj", "base": "s", "name": "s", "items": []}
    with pytest.raises(ValueError, match="0 only with into and steps"):
        prepare(base, None)
    steps = [{"op": "lift", "from_ticks": "0", "to_ticks": "10"}]
    assert prepare({**base, "options": {"into": True, "steps": steps}}, None)["items"] == []


def test_word_tools_pass_on_the_transcript_warnings(monkeypatch):
    note = "these words are the Thai transcript (job 86) ... language=\"en\""
    built = {"missing": [], "warnings": [note], "word_objects": [], "source_words": {}, "source_level": None}
    monkeypatch.setattr(driver_commands.timeline_transcript, "build", lambda *a, **k: built)
    monkeypatch.setattr(driver_commands.word_cut, "plan_pieces", lambda *a, **k: [])

    async def premiere(command, args):
        return {"name": "S", "ticks_per_frame": "8467200000"}

    args = {"keep": [{"text": "x"}], "pad_ms": 60, "wordless_ms": 0}
    result = asyncio.run(driver_commands._plan_pieces(args, premiere))
    assert result["warnings"] == [note]


class _PasteHost:
    """Just enough Premiere for paste_from, following PREMIERE_FACTS: Make Subsequence cuts a range
    to a new sequence; Edit > Paste lands at the playhead on the lowest targeted tracks (here
    `land_v` tracks up); build_sequence clone overwrites, lift removes clips starting in range."""
    S = 254016000000

    def __init__(self, land_v=0):
        self.seqs = {"Split": [("V", 1, 0, 6 * self.S), ("V", 2, 2 * self.S, 8 * self.S), ("A", 1, 0, 6 * self.S)],
                     "YT": [("V", 1, 0, 10 * self.S), ("A", 1, 0, 10 * self.S)]}
        self.land_v, self.clipboard, self.playhead, self.calls = land_v, None, {}, []

    def timeline(self, name):
        tracks = {}
        for k, n, s, e in self.seqs[name]:
            tracks.setdefault(f"{k}{n}", []).append({"id": f"{k}{n}@{s}", "start_ticks": str(s), "end_ticks": str(e)})
        end = max((e for *_, e in self.seqs[name]), default=0)
        return {"name": name, "end_ticks": str(end), "tracks": [{"id": i, "clips": c} for i, c in tracks.items()]}

    async def __call__(self, command, args):
        self.calls.append(command)
        if command == "make_subsequence":
            a, b = int(args["in_ticks"]), int(args["out_ticks"])
            self.seqs[args["result_name"]] = [(k, n, max(s, a) - a, min(e, b) - a)
                                              for k, n, s, e in self.seqs[args["sequence"]] if s < b and e > a]
        elif command == "read_timeline":
            return self.timeline(args["sequence"])
        elif command == "set_playhead":
            self.playhead[args["sequence"]] = int(args["ticks"])
        elif command == "menu_command" and args["path"] == "Edit > Copy":
            self.clipboard = list(self.seqs[args["sequence"]])
        elif command == "menu_command" and args["path"] == "Edit > Paste":
            at = self.playhead[args["sequence"]]
            self.seqs[args["sequence"]] += [(k, n + (self.land_v if k == "V" else 0), s + at, e + at) for k, n, s, e in self.clipboard]
        elif command == "list_project":
            return {"path": "E:/day.prproj"}
        elif command == "build_sequence":
            seq = self.seqs[args["base"]]
            for st in args["options"]["steps"]:
                lo, hi = int(st["from_ticks"]), int(st["to_ticks"])
                moving = [c for c in seq if lo <= c[2] < hi]
                if st["op"] == "lift":
                    seq[:] = [c for c in seq if c not in moving]
                    continue
                dt, up = int(st["dt_ticks"]), st.get("v_offset", 0)
                for k, n, s, e in moving:
                    new = (k, n + (up if k == "V" else 0), s + dt, e + dt)
                    seq[:] = [c for c in seq if not (c[:2] == new[:2] and c[2] < new[3] and c[3] > new[2])] + [new]
        elif command == "remove_piece":
            del self.seqs[args["name"]]
        elif command == "duplicate_sequence":
            self.seqs[args["result_name"]] = list(self.seqs[args["sequence_name"]])
        return {}


def _paste(host, **extra):
    S = _PasteHost.S
    args = driver_commands.COMMANDS["paste_from"].prepare(
        {"source": "Split", "in_ticks": str(1 * S), "out_ticks": str(4 * S), "target": "YT", "at_ticks": str(5 * S), **extra}, None)
    return asyncio.run(driver_commands.COMMANDS["paste_from"].run(args, host))


def test_paste_from_puts_every_track_of_the_range_at_the_place_and_cleans_up():
    S = _PasteHost.S
    host = _PasteHost()
    out = _paste(host)
    assert out["missing"] == [] and out["left_at_park"] == [] and out["piece"] is None
    yt = sorted(host.seqs["YT"])
    # V1/A1 of 1-4 s at 5 s (overwriting the YT clip there), V2's 2-4 s at 6 s.
    assert ("V", 1, 5 * S, 8 * S) in yt and ("A", 1, 5 * S, 8 * S) in yt and ("V", 2, 6 * S, 8 * S) in yt
    assert all(s < 30 * S for _, _, s, _ in yt)
    assert host.seqs["Split"][0] == ("V", 1, 0, 6 * S)  # source untouched
    assert not any(n.endswith(driver_commands.PIECE_SUFFIX) for n in host.seqs)


def test_paste_from_corrects_where_the_paste_landed_and_honours_v_offset():
    S = _PasteHost.S
    host = _PasteHost(land_v=1)  # V1 not targeted: the paste lands one track up
    out = _paste(host, v_offset=2)
    assert out["missing"] == []
    assert ("V", 3, 5 * S, 8 * S) in host.seqs["YT"] and ("V", 4, 6 * S, 8 * S) in host.seqs["YT"]


def test_paste_from_checks_its_arguments():
    prep = driver_commands.COMMANDS["paste_from"].prepare
    good = {"source": "a", "target": "b", "in_ticks": "0", "out_ticks": "5", "at_ticks": "0"}
    for bad in ({"out_ticks": "0"}, {"v_offset": -1}, {"v_offset": True}, {"keep_piece": "yes"}, {"target": ""}):
        try:
            prep({**good, **bad}, None)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")
    try:
        driver_commands.COMMANDS["remove_piece"].prepare({"name": "1 YOUTUBE D1"}, None)
    except ValueError:
        pass
    else:
        raise AssertionError("remove_piece accepted a user sequence")


def _arrange(host, blocks, sequence="Cut"):
    args = driver_commands.COMMANDS["arrange"].prepare(
        {"sequence": sequence, "result_name": "Cut v2",
         "blocks": [{"from_ticks": str(f), "to_ticks": str(t)} for f, t in blocks]}, None)
    return asyncio.run(driver_commands.COMMANDS["arrange"].run(args, host))


def test_arrange_plays_the_blocks_in_the_new_order_on_a_copy():
    S = _PasteHost.S
    host = _PasteHost()
    # A 2 s intro left alone, then three pieces A (2-4), B (4-7, with a V2 cover), C (7-8); an outro.
    cut = [("V", 1, 0, 2 * S), ("V", 1, 2 * S, 4 * S), ("V", 1, 4 * S, 7 * S), ("V", 2, 5 * S, 6 * S),
           ("V", 1, 7 * S, 8 * S), ("A", 1, 2 * S, 4 * S), ("A", 1, 4 * S, 7 * S), ("V", 1, 8 * S, 9 * S)]
    host.seqs["Cut"] = list(cut)
    out = _arrange(host, [(7 * S, 8 * S), (4 * S, 7 * S), (2 * S, 4 * S)])  # C, B, A
    assert out["missing"] == [] and out["unexpected"] == []
    assert sorted(host.seqs["Cut v2"]) == sorted([
        ("V", 1, 0, 2 * S), ("V", 1, 2 * S, 3 * S),                          # intro, C
        ("V", 1, 3 * S, 6 * S), ("V", 2, 4 * S, 5 * S), ("A", 1, 3 * S, 6 * S),  # B with its cover
        ("V", 1, 6 * S, 8 * S), ("A", 1, 6 * S, 8 * S),                      # A
        ("V", 1, 8 * S, 9 * S)])                                            # outro untouched
    assert sorted(host.seqs["Cut"]) == sorted(cut)  # the source is never edited


def test_arrange_refuses_a_clip_across_a_block_edge_before_copying():
    S = _PasteHost.S
    host = _PasteHost()
    host.seqs["Cut"] = [("V", 1, 0, 3 * S), ("V", 1, 3 * S, 4 * S)]
    try:
        _arrange(host, [(2 * S, 4 * S), (0, 2 * S)])
    except ValueError as e:
        assert "cross a block edge" in str(e)
    else:
        raise AssertionError("arranged across a clip")
    assert "Cut v2" not in host.seqs


def test_arrange_blocks_must_tile_one_stretch():
    prep = driver_commands.COMMANDS["arrange"].prepare
    for blocks in ([[0, 5]], [[0, 5], [6, 9]], [[0, 5], [4, 9]], [[0, 5], [0, 5]]):
        try:
            prep({"sequence": "a", "result_name": "b",
                  "blocks": [{"from_ticks": str(f), "to_ticks": str(t)} for f, t in blocks]}, None)
        except ValueError:
            continue
        raise AssertionError(f"accepted {blocks}")
