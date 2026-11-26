"""One table owns the Premiere driver commands (docs/arch-design-helper-v3.md move 1)."""
import asyncio
import json
import subprocess
from pathlib import Path

import pytest

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


@pytest.fixture(autouse=True)
def _fresh_paste_counts():
    driver_commands._PASTES_INTO.clear()  # the guard counts per helper life; each test is a new one
    yield
    driver_commands._PASTES_INTO.clear()


class _PasteHost:
    """Just enough Premiere for paste_from, following PREMIERE_FACTS: Make Subsequence cuts a range
    to a new sequence; Edit > Paste lands at the playhead on the lowest targeted tracks (here
    `land_v` tracks up); build_sequence clone overwrites, lift removes clips starting in range."""
    S = 254016000000

    def __init__(self, land_v=0):
        self.seqs = {"Split": [("V", 1, 0, 6 * self.S), ("V", 2, 2 * self.S, 8 * self.S), ("A", 1, 0, 6 * self.S)],
                     "YT": [("V", 1, 0, 10 * self.S), ("A", 1, 0, 10 * self.S)]}
        self.land_v, self.clipboard, self.playhead, self.calls = land_v, None, {}, []
        self.transactions = 0
        self.active, self.fail_paste, self.fail_on = None, False, set()

    def timeline(self, name):
        tracks = {}
        for k, n, s, e in self.seqs[name]:
            tracks.setdefault(f"{k}{n}", []).append({"id": f"{k}{n}@{s}", "start_ticks": str(s), "end_ticks": str(e)})
        end = max((e for *_, e in self.seqs[name]), default=0)
        return {"name": name, "end_ticks": str(end), "ticks_per_frame": str(self.S // 30),
                "tracks": [{"id": i, "clips": c} for i, c in tracks.items()]}

    async def __call__(self, command, args):
        self.calls.append(command)
        if command in self.fail_on:
            raise ValueError(f"{command} failed")
        if command == "make_subsequence":
            a, b = int(args["in_ticks"]), int(args["out_ticks"])
            cut = [(k, n, max(s, a), min(e, b)) for k, n, s, e in self.seqs[args["sequence"]] if s < b and e > a]
            first = min((s for _, _, s, _ in cut), default=a)  # Make Subsequence drops the empty lead-in
            self.seqs[args["result_name"]] = [(k, n, s - first, e - first) for k, n, s, e in cut]
        elif command == "read_timeline":
            return self.timeline(args["sequence"])
        elif command == "set_playhead":
            self.playhead[args["sequence"]] = int(args["ticks"])
        elif command == "menu_command" and args["path"] == "Edit > Copy":
            self.clipboard, self.active = list(self.seqs[args["sequence"]]), args["sequence"]
        elif command == "menu_command" and args["path"] == "Edit > Paste":
            if self.fail_paste:
                raise ValueError("A1@0: no clip starts at 0 ticks on that track, in 4 reads.")
            self.active = args["sequence"]  # Paste happens in the focused target
            at = self.playhead[args["sequence"]] - min(s for _, _, s, _ in self.clipboard)  # earliest clip at the playhead
            self.seqs[args["sequence"]] += [(k, n + (self.land_v if k == "V" else 0), s + at, e + at) for k, n, s, e in self.clipboard]
        elif command == "list_project":
            return {"path": "E:/day.prproj", "sequences": [{"name": n} for n in self.seqs]}
        elif command == "build_sequence":
            seq = self.seqs[args["base"]]
            for st in args["options"]["steps"]:
                self.transactions += 1
                lo, hi = int(st["from_ticks"]), int(st["to_ticks"])
                if st["op"] == "lift":
                    seq[:] = [c for c in seq if not lo <= c[2] < hi]
                    continue
                up = st.get("v_offset", 0)
                parts = [st] + st.get("ranges", [])  # one read, one transaction
                moving = [(c, int(r["dt_ticks"])) for r in parts for c in seq if int(r["from_ticks"]) <= c[2] < int(r["to_ticks"])]
                for (k, n, s, e), dt in moving:
                    new = (k, n + (up if k == "V" else 0), s + dt, e + dt)
                    seq[:] = [c for c in seq if not (c[:2] == new[:2] and c[2] < new[3] and c[3] > new[2])] + [new]
        elif command == "cut_copy":  # keep what lies outside the cuts, gaps closed (applyNativeCut)
            tpf = int(args["cuts"]["ticks_per_frame"])
            cuts = [(f * tpf, t * tpf) for f, t in args["cuts"]["cuts_frames"]]
            gone = lambda x: sum(min(x, t) - f for f, t in cuts if f < x)  # noqa: E731
            edges = sorted({x for c in cuts for x in c})
            out = []
            for k, n, s, e in self.seqs[args["sequence_name"]]:
                for lo, hi in zip([s] + [x for x in edges if s < x < e], [x for x in edges if s < x < e] + [e]):
                    if not any(f <= lo and hi <= t for f, t in cuts):
                        out.append((k, n, lo - gone(lo), hi - gone(lo)))
            self.seqs[args["result_name"]] = out
        elif command == "remove_piece":
            if args["name"] == self.active:
                raise ValueError(f"{args['name']!r} is the active sequence; nothing removed")
            del self.seqs[args["name"]]
        elif command == "open_sequence":
            self.active = args["sequence"]
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


def test_paste_from_keeps_a_gap_at_the_start_of_the_range():
    S = _PasteHost.S
    host = _PasteHost()
    host.seqs["Split"] = [("V", 1, 2 * S, 6 * S), ("A", 1, 2 * S, 6 * S)]  # nothing before 2 s
    out = _paste(host)  # range 1-4 s into YT at 5 s
    assert out["missing"] == [] and out["left_at_park"] == []
    assert ("V", 1, 6 * S, 8 * S) in host.seqs["YT"] and ("A", 1, 6 * S, 8 * S) in host.seqs["YT"]


def test_paste_from_an_empty_range_leaves_no_piece_behind():
    S = _PasteHost.S
    host = _PasteHost()
    host.seqs["Split"] = [("V", 1, 5 * S, 6 * S)]
    try:
        _paste(host)
    except ValueError as e:
        assert "no clips" in str(e)
    else:
        raise AssertionError("pasted an empty range")
    assert not any(n.endswith(driver_commands.PIECE_SUFFIX) for n in host.seqs)


def test_paste_from_replaces_a_piece_an_earlier_failed_run_kept():
    S = _PasteHost.S
    host = _PasteHost()
    stale = "Split 1.000-4.000s" + driver_commands.PIECE_SUFFIX
    host.seqs[stale] = [("V", 1, 0, S)]
    assert _paste(host)["missing"] == []
    assert stale not in host.seqs and ("V", 1, 5 * S, 8 * S) in host.seqs["YT"]


@pytest.fixture(autouse=True)
def _plenty_of_memory(monkeypatch):
    monkeypatch.setattr(driver_commands, "_commit_free_gb", lambda: 64.0)


def _derive(host, pieces, **extra):
    args = driver_commands.COMMANDS["paste_pieces"].prepare(
        {"source": "Parent", "template": "Template", "target": "Short",
         "pieces": [{"from_ticks": str(f), "to_ticks": str(t)} for f, t in pieces], **extra}, None)
    return asyncio.run(driver_commands.COMMANDS["paste_pieces"].run(args, host))


def _parent(host, seconds):
    S = _PasteHost.S
    # One clip per second on V1, V2 (a cover) and A1, so every piece edge falls between clips or inside one.
    host.seqs["Parent"] = [(k, n, i * S, (i + 1) * S) for i in range(seconds) for k, n in (("V", 1), ("V", 2), ("A", 1))]
    host.seqs["Template"] = [("V", 6, 0, 3 * S)]  # the user's title Graphic
    return S


def test_paste_pieces_plays_the_pieces_in_order_on_a_template_copy_and_cleans_up():
    host = _PasteHost()
    S = _parent(host, 20)
    half = S // 2
    out = _derive(host, [(10 * S, 12 * S + half), (2 * S, 3 * S), (15 * S + half, 17 * S)])
    assert out["missing"] == [] and out["unexpected"] == []
    short = sorted(host.seqs["Short"])
    assert ("V", 6, 0, 3 * S) in short  # the template's title stays
    assert ("A", 1, 0, S) in short and ("A", 1, 2 * S, 2 * S + half) in short  # piece 1 at 0
    assert ("V", 2, 2 * S + half, 3 * S + half) in short  # piece 2 right after piece 1
    assert ("V", 1, 3 * S + half, 4 * S) in short and ("V", 1, 4 * S, 5 * S) in short  # piece 3
    assert not any(n.endswith(driver_commands.PIECE_SUFFIX) for n in host.seqs)  # every temporary removed
    assert host.seqs["Template"] == [("V", 6, 0, 3 * S)] and len(host.seqs["Parent"]) == 60  # never edited
    assert host.calls.count("save_project") == 2


def test_paste_pieces_costs_the_same_whatever_the_piece_count():
    costs = []
    for n in (3, 12):
        host = _PasteHost()
        S = _parent(host, 40)
        pieces = [(i * 3 * S, i * 3 * S + 2 * S) for i in range(n)][::-1]  # play order reversed
        out = _derive(host, pieces)
        assert out["missing"] == [] and out["unexpected"] == []
        costs.append((len(host.calls), host.transactions, host.calls.count("make_subsequence"), host.calls.count("menu_command")))
    assert costs[0] == costs[1], costs
    assert costs[0][2] == 2 and costs[0][3] == 2  # the span, and one piece for the one paste: one Copy, one Paste


def test_paste_pieces_refuses_overlapping_pieces_and_an_existing_name():
    prep = driver_commands.COMMANDS["paste_pieces"].prepare
    base = {"source": "P", "template": "T", "target": "S"}
    for pieces in ([], [[0, 5], [4, 9]], [[5, 5]]):
        try:
            prep({**base, "pieces": [{"from_ticks": str(f), "to_ticks": str(t)} for f, t in pieces]}, None)
        except ValueError:
            continue
        raise AssertionError(f"accepted {pieces}")
    host = _PasteHost()
    S = _parent(host, 5)
    host.seqs["Short"] = []
    try:
        _derive(host, [(0, S)])
    except ValueError as e:
        assert "already exists" in str(e)
    else:
        raise AssertionError("overwrote an existing sequence")


def test_paste_pieces_without_a_template_pastes_into_the_existing_target_in_place():
    host = _PasteHost()
    S = _parent(host, 20)
    host.seqs["Draft"] = [("V", 1, 0, 4 * S), ("V", 3, 30 * S, 32 * S)]  # the draft's own edit
    before = set(host.seqs)
    args = driver_commands.COMMANDS["paste_pieces"].prepare(
        {"source": "Parent", "target": "Draft", "at_ticks": str(10 * S),
         "pieces": [{"from_ticks": str(6 * S), "to_ticks": str(7 * S)}, {"from_ticks": str(2 * S), "to_ticks": str(3 * S)}]}, None)
    out = asyncio.run(driver_commands.COMMANDS["paste_pieces"].run(args, host))
    assert out["missing"] == [] and out["unexpected"] == []
    draft = host.seqs["Draft"]
    assert ("V", 1, 0, 4 * S) in draft and ("V", 3, 30 * S, 32 * S) in draft  # what was there stays
    assert ("V", 2, 10 * S, 11 * S) in draft and ("A", 1, 11 * S, 12 * S) in draft  # both pieces, in play order
    assert set(host.seqs) == before  # no new sequence, every temporary removed


def test_a_failed_paste_pieces_removes_its_temporaries_and_names_the_half_built_target():
    host = _PasteHost()
    S = _parent(host, 20)
    host.fail_paste = True
    before = set(host.seqs)
    try:
        _derive(host, [(10 * S, 12 * S), (2 * S, 3 * S)])
    except ValueError as e:
        assert "no clip starts at" in str(e) and "'Short' was made from the template" in str(e)
    else:
        raise AssertionError("a failed paste reported success")
    assert set(host.seqs) - before == {"Short"}  # every temporary removed, even the active one


def test_paste_pieces_plays_touching_pieces_that_still_follow_each_other_as_one_block():
    host = _PasteHost()
    S = _parent(host, 20)
    half = S // 2
    out = _derive(host, [(10 * S, 11 * S + half), (11 * S + half, 13 * S), (2 * S, 3 * S)])
    assert out["missing"] == [] and out["unexpected"] == []
    assert ("V", 1, S, 2 * S) in host.seqs["Short"]  # the clip across the shared edge, whole


def test_paste_pieces_refuses_touching_pieces_in_a_new_order_before_touching_premiere():
    host = _PasteHost()
    S = _parent(host, 20)
    half = S // 2
    try:
        _derive(host, [(3 * S + half, 5 * S), (2 * S, 3 * S + half)])
    except ValueError as e:
        assert "meet at" in str(e) and "leave a frame" in str(e) and "made from the template" not in str(e)
    else:
        raise AssertionError("reordered across a clip")
    assert "make_subsequence" not in host.calls and "Short" not in host.seqs


def test_paste_pieces_refuses_a_missing_template_before_any_cut():
    host = _PasteHost()
    S = _parent(host, 5)
    try:
        _derive(host, [(0, S)], template="Template ")
    except ValueError as e:
        assert "no template sequence 'Template '" in str(e)
    else:
        raise AssertionError("cut with no template to paste into")
    assert "make_subsequence" not in host.calls


def test_a_paste_pieces_failure_before_the_template_copy_does_not_name_a_target():
    host = _PasteHost()
    S = _parent(host, 20)
    host.fail_on = {"cut_copy"}
    before = set(host.seqs)
    try:
        _derive(host, [(10 * S, 12 * S), (2 * S, 3 * S)])
    except ValueError as e:
        assert "cut_copy failed" in str(e) and "made from the template" not in str(e)
    else:
        raise AssertionError("a failed cut reported success")
    assert set(host.seqs) == before


def test_paste_pieces_names_the_temporaries_it_could_not_remove():
    # Live 2026-11-26: in a Premiere session a few minutes old every remove_piece threw "The script
    # object is no longer valid." for a minute, and the temporaries stayed with nothing said.
    host = _PasteHost()
    S = _parent(host, 20)
    host.fail_on = {"remove_piece"}
    out = _derive(host, [(10 * S, 12 * S), (2 * S, 3 * S)])
    assert out["missing"] == [] and out["unexpected"] == []
    assert out["temporaries_left"] == ["Short span (CutDeck piece)", "Short cut (CutDeck piece)", "Short order (CutDeck piece)",
                                       "Short order (CutDeck piece) 0.000-3.000s (CutDeck piece)"]
    host = _PasteHost()
    S = _parent(host, 20)
    host.fail_on = {"remove_piece", "cut_copy"}
    try:
        _derive(host, [(10 * S, 12 * S), (2 * S, 3 * S)])
    except ValueError as e:
        assert "cut_copy failed" in str(e) and "Short span (CutDeck piece)" in str(e) and "remove by hand" in str(e)
    else:
        raise AssertionError("a failed cut reported success")


def test_paste_pieces_removes_only_its_own_pieces_and_leaves_the_short_open():
    host = _PasteHost()
    S = _parent(host, 20)
    kept = {"Short yt 1.000-3.000s (CutDeck piece)", "Short 2 span (CutDeck piece)"}  # a kept piece; another run's
    for n in kept:
        host.seqs[n] = []
    out = _derive(host, [(10 * S, 12 * S), (2 * S, 3 * S)])
    assert out["missing"] == [] and out["unexpected"] == []
    assert kept <= set(host.seqs) and host.active == "Short"


def test_paste_pieces_refuses_to_start_when_memory_is_nearly_gone(monkeypatch):
    # Live 2026-11-26: 17 soak runs took Premiere to 41 GB private with 0.6 GB of commit left;
    # Premiere keeps what each cut used until it quits, so the next run would have crashed it.
    monkeypatch.setattr(driver_commands, "_commit_free_gb", lambda: 2.0)
    host = _PasteHost()
    S = _parent(host, 5)
    try:
        _derive(host, [(0, S)])
    except ValueError as e:
        assert "restart Premiere" in str(e) and "2.0 GB" in str(e)
    else:
        raise AssertionError("started a build with no memory left")
    assert host.calls == []  # refused before touching Premiere


def test_paste_pieces_without_a_template_needs_an_existing_target():
    host = _PasteHost()
    S = _parent(host, 5)
    args = driver_commands.COMMANDS["paste_pieces"].prepare(
        {"source": "Parent", "target": "Nope", "pieces": [{"from_ticks": "0", "to_ticks": str(S)}]}, None)
    try:
        asyncio.run(driver_commands.COMMANDS["paste_pieces"].run(args, host))
    except ValueError as e:
        assert "no sequence 'Nope'" in str(e)
    else:
        raise AssertionError("pasted into a sequence that does not exist")


def test_a_third_paste_into_one_target_needs_a_reason_and_reports_the_fallback():
    host = _PasteHost()
    _paste(host)
    _paste(host)
    try:
        _paste(host)
    except ValueError as e:
        assert "paste_pieces" in str(e) and "per_piece_reason" in str(e)
    else:
        raise AssertionError("a third paste went through silently")
    out = _paste(host, per_piece_reason="one insert per user note")
    assert out["fallback"] == "one insert per user note"


def test_a_failed_paste_does_not_count_toward_the_per_piece_guard():
    host = _PasteHost()
    host.fail_paste = True
    for _ in range(2):
        with pytest.raises(ValueError):
            _paste(host)
    host.fail_paste, host.active = False, None
    host.seqs = {n: c for n, c in host.seqs.items() if not n.endswith(driver_commands.PIECE_SUFFIX)}  # kept to look at
    assert "fallback" not in _paste(host)


def test_arrange_clones_a_long_reorder_in_batches_from_fresh_reads():
    S = _PasteHost.S
    n = 2 * driver_commands.CLONE_BATCH + 5
    host = _PasteHost()
    host.seqs["Cut"] = [(k, 1, i * S, (i + 1) * S) for i in range(n) for k in "VA"]
    out = _arrange(host, [(i * S, (i + 1) * S) for i in range(n)][::-1])
    assert out["missing"] == [] and out["unexpected"] == []
    assert host.transactions == 3 + 3


def test_arrange_is_four_steps_whatever_the_block_count():
    S = _PasteHost.S
    for n in (3, 9):
        host = _PasteHost()
        host.seqs["Cut"] = [(k, 1, i * S, (i + 1) * S) for i in range(n) for k in "VA"]
        out = _arrange(host, [(i * S, (i + 1) * S) for i in range(n)][::-1])
        assert out["missing"] == [] and out["unexpected"] == []
        assert host.transactions == 4
