"""cutdeck/srt_subtitles.py: SRT snapping, the pixel locators on live Premiere 27.0 captures
(2026-11-22), and the command's steps against a fake `premiere` (the UI drag is stubbed).

Fixtures (tests/fixtures/premiere_ui/): the Project panel right after `import_files` of an SRT
(project_caption_selected: the SRT row selected and scrolled to), the same panel with a Style item
selected instead (project_style_selected), the timeline panel (timeline_headers) and the
"New caption track" dialog as opened (new_caption_track).
"""
import asyncio
import math
from pathlib import Path

import pytest
from PIL import Image

pytest.importorskip("scipy")
from cutdeck import srt_subtitles as subs  # noqa: E402
from cutdeck.driver_commands import COMMANDS  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "premiere_ui"
TPF = 8467200000  # 30 fps
SRT = """1
00:00:00,517 --> 00:00:01,933
แม็กซ์บอกว่ารถดีมาก

2
00:00:01,933 --> 00:00:03,250
แต่ยางหมดเร็วเกินไป

3
00:00:03,250 --> 00:00:04,700
บรรทัดแรก
บรรทัดสอง

4
00:00:05,000 --> 00:00:05,010
สั้นเกิน
"""


def _img(name):
    return Image.open(FIX / f"{name}.png").convert("RGB")


def test_srt_parses_and_snaps_to_nearest_frames():
    cues = subs.parse_srt(SRT)
    assert [c["start_ms"] for c in cues] == [517, 1933, 3250, 5000]
    assert cues[2]["text"] == "บรรทัดแรก\nบรรทัดสอง"
    kept, dropped = subs.to_frames(cues, TPF)
    assert [(c["start_frame"], c["end_frame"]) for c in kept] == [(16, 58), (58, 98), (98, 141)]
    assert [d["cue"] for d in dropped] == [4]  # 10 ms: under a frame


def test_written_times_floor_back_to_the_same_frame():
    """Premiere floors SRT ms to frames (live: 0.517 s -> frame 15), so each stamp is the first ms of its frame."""
    kept, _ = subs.to_frames(subs.parse_srt(SRT), TPF)
    again = subs.parse_srt(subs.srt_text(kept, TPF))
    for c, a in zip(kept, again):
        assert math.floor(a["start_ms"] * subs.TICKS_PER_MS / TPF) == c["start_frame"]
        assert math.floor(a["end_ms"] * subs.TICKS_PER_MS / TPF) == c["end_frame"]
    assert subs.srt_text(kept, TPF).startswith("1\n00:00:00,534 --> 00:00:01,934\n")


def test_overlapping_cues_are_refused():
    with pytest.raises(ValueError, match="overlap"):
        subs.to_frames([{"start_ms": 0, "end_ms": 1000, "text": "a"}, {"start_ms": 500, "end_ms": 2000, "text": "b"}], TPF)


def test_imported_srt_row_is_found():
    x, y = subs.find_caption_row(_img("project_caption_selected"))
    assert abs(y - 511) <= 4 and 100 <= x <= 160  # zz-probe5.srt, the selected row


def test_no_selected_caption_row_is_refused():
    with pytest.raises(RuntimeError, match="not the selected row"):
        subs.find_caption_row(_img("project_style_selected"))  # a Style item selected, white label


def test_timeline_drop_point_is_right_of_the_track_headers():
    x, y = subs.find_timeline(_img("timeline_headers"), caption_tracks=3)
    assert 380 <= x <= 440 and abs(y - 175) <= 6  # V4, the top video row below C3, C2 and C1


def test_no_timeline_is_refused():
    with pytest.raises(RuntimeError, match="timeline"):
        subs.find_timeline(_img("project_caption_selected"), 0)


def test_start_point_radio_reads_source_timecode():
    dialog = _img("new_caption_track")
    assert dialog.size == subs.CAPTION_SIZE
    assert subs.selected(dialog, *subs.SOURCE_TIMECODE_RADIO)
    assert not subs.selected(dialog, subs.SOURCE_TIMECODE_RADIO[0], subs.SOURCE_TIMECODE_RADIO[1] + 24)


class FakePremiere:
    """Answers the panel commands the route uses; place_by_drag and Upgrade are simulated."""

    def __init__(self, tmp, landing=6, v5=(), v6=()):
        self.calls, self.captions, self.landing = [], [], landing
        self.video = {f"V{n}": [] for n in range(1, 7)}
        self.video["V5"], self.video["V6"] = list(v5), list(v6)
        self.project = str(tmp / "show.prproj")

    async def __call__(self, command, args=None):
        self.calls.append((command, args))
        if command == "open_sequence":
            return {"name": args["sequence"]}
        if command == "read_sequence":
            return {"name": "short", "ticks_per_frame": str(TPF), "project_path": "\\\\?\\" + self.project,
                    "video_track_count": 6}
        if command == "run_probe":
            return {"report": {"complete": True, "sequence_name": "short",
                               "tracks": [{"index": 0, "items": [{"start_ticks": str(s), "end_ticks": str(e)} for s, e in self.captions]}]}}
        if command == "read_timeline":
            tracks = args.get("tracks") or list(self.video)
            return {"tracks": [{"id": t, "clips": [{"id": f"{t}@{s}", "start_ticks": str(s), "end_ticks": str(e)} for s, e in self.video[t]]}
                               for t in tracks]}
        if command == "menu_command" and args["path"].startswith("Graphics and Titles > Upgrade"):
            self.video[f"V{self.landing}"] += self.captions
            self.captions = []
        if command == "build_sequence" and args["steps"]:
            step = args["steps"][0]
            src = f"V{step['tracks']['video'][0] + 1}"
            dst = f"V{step['tracks']['video'][0] + 1 + step['v_offset']}"
            self.video[dst] += self.video[src]
            self.video[src] = []
        return {}


def _run(fake, monkeypatch, srt_path, **args):
    async def focused(premiere, focus, sequence, action):
        return action()

    def drop(style, caption_tracks):
        kept, _ = subs.to_frames(subs.parse_srt(Path(fake.calls_srt[0]).read_text(encoding="utf-8")), TPF)
        fake.captions = [(c["start_frame"] * TPF, c["end_frame"] * TPF) for c in kept]
        return {"row": (1, 1), "drop": (2, 2), "style": style, "caption_tracks": caption_tracks}

    async def no_sleep(_):
        return None

    original = fake.__call__

    async def call(command, a=None):
        if command == "import_files":
            fake.calls_srt = a["paths"]
        return await original(command, a)

    monkeypatch.setattr(subs.keys, "run_focused", focused)
    monkeypatch.setattr(subs, "place_by_drag", drop)
    monkeypatch.setattr(subs.asyncio, "sleep", no_sleep)
    return asyncio.run(subs.run(call, {"sequence": "short", "srt": str(srt_path), "track": None, "style": 1,
                                       "position": None, "scale": None, **args}))


def test_command_moves_upgraded_graphics_down_to_the_chosen_track(tmp_path, monkeypatch):
    srt = tmp_path / "max.srt"
    srt.write_text(SRT, encoding="utf-8")
    fake = FakePremiere(tmp_path, landing=6)
    out = _run(fake, monkeypatch, srt, track=5, position=[0.5, -0.0423], scale=112.5)
    assert out["track"] == "V5" and out["upgraded_on"] == "V6" and out["off_cues"] == []
    assert out["graphics"] == [f"V5@{f * TPF}" for f in (16, 58, 98)] and [d["cue"] for d in out["dropped_cues"]] == [4]
    build = next(a for c, a in fake.calls if c == "build_sequence")
    assert build["steps"][0]["v_offset"] == -1 and build["steps"][1]["op"] == "lift"
    assert build["restyle"][0]["track"] == 4 and build["restyle"][0]["motion"] == {"position": [0.5, -0.0423], "scale": 112.5}
    assert Path(out["srt_imported"]).parent == tmp_path / "CutDeck" / "Subtitles"
    menus = [a["path"] for c, a in fake.calls if c == "menu_command"]
    assert menus == ["Edit > Select All", "Graphics and Titles > Upgrade Caption to Graphic", "Edit > Deselect All"]


def test_command_refuses_a_busy_target_track(tmp_path, monkeypatch):
    srt = tmp_path / "max.srt"
    srt.write_text(SRT, encoding="utf-8")
    fake = FakePremiere(tmp_path, v5=[(30 * TPF, 40 * TPF)])
    with pytest.raises(ValueError, match="V5 is not empty"):
        _run(fake, monkeypatch, srt, track=5)
    assert not any(c == "import_files" for c, _ in fake.calls)


def test_command_refuses_a_sequence_with_captions(tmp_path, monkeypatch):
    srt = tmp_path / "max.srt"
    srt.write_text(SRT, encoding="utf-8")
    fake = FakePremiere(tmp_path)
    fake.captions = [(0, TPF)]
    with pytest.raises(ValueError, match="already has captions"):
        _run(fake, monkeypatch, srt)


def test_arguments_are_checked(tmp_path):
    srt = tmp_path / "a.srt"
    srt.write_text(SRT, encoding="utf-8")
    prepare = COMMANDS["srt_subtitles"].prepare
    good = {"sequence": "short", "srt": str(srt), "track": 5, "position": [0.5, -0.0423], "scale": 112.5}
    assert prepare(good, None) == {**good, "style": 1}
    for bad in ({"srt": str(tmp_path / "missing.srt")}, {"track": 0}, {"style": -1}, {"position": [0.5]}, {"sequence": ""}, {"scale": 0}):
        with pytest.raises(ValueError):
            prepare({**good, **bad}, None)


def test_command_without_track_restyles_where_upgrade_put_them(tmp_path, monkeypatch):
    srt = tmp_path / "max.srt"
    srt.write_text(SRT, encoding="utf-8")
    fake = FakePremiere(tmp_path, landing=6)
    out = _run(fake, monkeypatch, srt, position=[0.5, -0.0423], scale=112.5)
    assert out["track"] == "V6" and out["off_cues"] == []
    build = next(a for c, a in fake.calls if c == "build_sequence")
    assert build["steps"] == [] and build["items"] == [] and build["restyle"][0]["track"] == 5


def test_command_stops_before_moving_a_clip_already_on_the_landing_track(tmp_path, monkeypatch):
    """A title in a gap between cues on the track Upgrade used would be cloned and lifted too."""
    srt = tmp_path / "max.srt"
    srt.write_text(SRT, encoding="utf-8")
    fake = FakePremiere(tmp_path, landing=6, v6=[(60 * TPF, 62 * TPF)])  # a title inside the subtitles' span
    with pytest.raises(RuntimeError, match="already holds"):
        _run(fake, monkeypatch, srt, track=5)
    assert not any(c == "build_sequence" for c, _ in fake.calls)
