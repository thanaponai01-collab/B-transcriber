"""HKS reels (cutdeck/hks_reels.py): the planner and the offline check on synthetic day projects,
then the check on the user's own saved reels when the G: drive is mounted."""
import asyncio
import copy
from functools import lru_cache
from pathlib import Path

import pytest

from cutdeck import driver_commands
from cutdeck import hks_reels as reels
from cutdeck.sequence_timing import PPRO_TICKS_PER_SECOND

ROOT = Path(r"G:\Me\Works")
PROJECT = r"E:\day\4. PROJECTS\1. PREMIERE PRO\day.prproj"
PNG = r"E:\day\1. FOOTAGE\PSD-REEL\1.png"


def clip(name, start, end, **extra):
    return {"name": name, "start": start, "end": end, "source_in": 0.0, "source_out": end - start,
            "disabled": False, "effects": [], **extra}


def seq(name, video, audio, frame=(1080, 1080)):
    track = lambda i, clips: {"index": i, "muted": False, "locked": False, "clips": list(clips)}  # noqa: E731
    return {"name": name, "frame": list(frame), "markers": [],
            "video_tracks": [track(i, c) for i, c in enumerate(video)],
            "audio_tracks": [track(i, c) for i, c in enumerate(audio)]}


def nest(name, end):
    return clip(name, 0.0, end, nested_sequence=name)


def frame(end, path=PNG):
    return clip("1.png", 0.0, end, media_path=path, source_in=3600.0)


def day(fb_end=179.96, square_end=59.96, user_reels=True):
    """A day project as prproj_reader reads it: the user's outputs beside the template's blanks."""
    logo = clip(reels.LOGO, 0.0, fb_end, media_path=r"G:\assets\LOGO_FOR SQUARE FRAME2.png")
    fb = seq("2 FACEBOOK D1", [[clip("a.mp4", 0.0, fb_end)], [], [logo]], [[clip("a.mp4", 0.0, fb_end)]])
    copy01 = seq("2 FACEBOOK D1 Copy 01", [[clip("a.mp4", 0.0, fb_end)], [], []], [[clip("a.mp4", 0.0, fb_end)]])
    square = seq("3 SQUARE SELECT D1", [[clip("b.mp4", 0.0, square_end)]], [[clip("b.mp4", 0.0, square_end)]])
    sequences = [fb, square,
                 seq("4 REEL SIZE D1", [[], []], [[], []], (1080, 1920)), seq("2 FACEBOOK D1", [[]] * 10, [[]] * 4),
                 seq("3 SQUARE SELECT D1", [[]] * 10, [[]] * 4), seq("5 REEL 1-3 SIZE D1", [[]] * 10, [[]] * 4, (1080, 1920))]
    if user_reels:
        sequences += [
            copy01,
            seq("4 REEL SIZE D1", [[nest(square["name"], square_end)], [], [frame(square_end)]],
                [[nest(square["name"], square_end)], []], (1080, 1920)),
            seq("5 REEL 1-3 SIZE D1", [[nest(copy01["name"], fb_end)]] + [[]] * 9 + [[frame(fb_end)]],
                [[nest(copy01["name"], fb_end)], [], [], []], (1080, 1920)),
        ]
    return {"path": PROJECT, "sequences": sequences}


def ticks(seconds):
    return str(round(seconds * PPRO_TICKS_PER_SECOND))


def test_the_plan_builds_both_reels_on_copies_of_the_blank_reels():
    calls = reels.plan(day(), PNG)
    assert [c["command"] for c in calls] == ["duplicate_sequence", "edit_clips", "duplicate_sequence", "place_media",
                                             "build_sequence", "duplicate_sequence", "place_media", "build_sequence"]
    fb_copy, reel4, reel5 = "2 FACEBOOK D1 Copy 01 (CutDeck)", "4 REEL SIZE D1 (CutDeck)", "5 REEL 1-3 SIZE D1 (CutDeck)"
    assert calls[0]["args"] == {"sequence_name": "2 FACEBOOK D1", "result_name": fb_copy}
    assert calls[0]["expect"] == {"video_clips": 2, "audio_clips": 1}
    assert calls[1]["args"] == {"sequence": fb_copy, "edits": [{"clip": "V3@0", "op": "remove"}]}
    assert calls[2]["args"] == {"sequence_name": "4 REEL SIZE D1", "result_name": reel4, "empty": True}
    assert calls[3]["args"] == {"sequence": reel4, "nest": "3 SQUARE SELECT D1", "at_ticks": "0", "v": 0, "a": 0}
    assert calls[6]["args"] == {"sequence": reel5, "nest": fb_copy, "at_ticks": "0", "v": 0, "a": 0}
    for build, reel, end in ((calls[4], reel4, 59.96), (calls[7], reel5, 179.96)):
        assert (build["args"]["base"], build["args"]["name"], build["args"]["into"]) == (reel, reel, True)
        item, = build["args"]["items"]
        assert (item["media"], item["in_ticks"], item["out_ticks"], item["v"], item["a"]) == (PNG, "0", ticks(end), 1, None)
    # The user's sequences are only ever sources, and every call passes the helper's own argument check.
    user = {s["name"] for s in day()["sequences"]}
    for c in calls:
        target = c["args"].get("result_name") or c["args"].get("sequence") or c["args"].get("name")
        assert target not in user and target.endswith(reels.SUFFIX)
        driver_commands.COMMANDS[c["command"]].prepare(c["args"], None)


def test_a_fresh_day_builds_too_and_a_d2_day_uses_the_template_blanks():
    assert len(reels.plan(day(user_reels=False), PNG)) == 8
    d2 = day(user_reels=False)
    for s in d2["sequences"]:
        if s["video_tracks"][0]["clips"]:
            s["name"] = s["name"].replace("D1", "D2")
    calls = reels.plan(d2, PNG)
    assert calls[0]["args"]["sequence_name"] == "2 FACEBOOK D2"
    assert calls[2]["args"] == {"sequence_name": "4 REEL SIZE D1", "result_name": "4 REEL SIZE D2 (CutDeck)", "empty": True}
    assert calls[5]["args"]["sequence_name"] == "5 REEL 1-3 SIZE D1"


@pytest.mark.parametrize("change, message", [
    (lambda p: p["sequences"].pop(0), r"a non-empty 2 FACEBOOK D<n>, found \[\]"),
    (lambda p: p["sequences"].pop(1), "no non-empty \"3 SQUARE SELECT D1\""),
    (lambda p: p["sequences"].append(copy.deepcopy(p["sequences"][0])), "panel cannot tell them apart"),
    (lambda p: p["sequences"][0]["video_tracks"][1]["clips"].append(clip(reels.LOGO, 0.0, 5.0)), "2 LOGO_FOR"),
    (lambda p: p["sequences"][0]["video_tracks"][0]["clips"].append(clip("late.mp4", 179.96, 181.0)), "over 179.96"),
    (lambda p: p["sequences"].append(seq("4 REEL SIZE D1 (CutDeck)", [[]], [[]])), "already in the project"),
    (lambda p: [s for s in p["sequences"] if s["name"] == "4 REEL SIZE D1" and not s["video_tracks"][0]["clips"]][0]
     .update(name="spare"), "no empty 1080x1920 \"4 REEL SIZE D<n>\""),
])
def test_the_plan_refuses_a_missing_or_ambiguous_piece(change, message):
    project = day()
    change(project)
    with pytest.raises(ValueError, match=message):
        reels.plan(project, PNG)


def test_the_plan_refuses_without_the_frame_png():
    with pytest.raises(ValueError, match="no 1.png"):
        reels.plan(day(), None)


def test_run_sends_each_call_and_stops_on_a_copy_that_reads_back_wrong():
    calls = reels.plan(day(), PNG)
    sent = []

    async def premiere(command, args):
        sent.append(command)
        if command == "duplicate_sequence":
            blank = args.get("empty")
            return {"width": 1080, "height": 1920 if blank else 1080, "video_clips": 0 if blank else 2,
                    "audio_clips": 0 if blank else 1}
        return {}

    assert len(asyncio.run(reels.run(calls, premiere))) == 8
    assert sent == [c["command"] for c in calls]

    async def landscape(command, args):
        return {"width": 1920, "height": 1080, "video_clips": 2, "audio_clips": 1}

    with pytest.raises(RuntimeError, match="4 REEL SIZE D1 \\(CutDeck\\) read back"):
        asyncio.run(reels.run(calls, landscape))

    async def short_frame(command, args):
        if command == "build_sequence":
            return {"placed": 1, "mismatches": 1, "first_mismatches": [{"id": "reel frame", "off_s": {"end": -0.04}}]}
        return await premiere(command, args)

    with pytest.raises(RuntimeError, match="the frame landed off"):
        asyncio.run(reels.run(calls, short_frame))


def test_the_check_passes_the_users_reels_and_sees_no_built_ones():
    assert reels.check(day(), suffix="") == []
    assert reels.check(day()) == ["4 REEL SIZE D1 (CutDeck): not one non-empty sequence of that name",
                                  "5 REEL 1-3 SIZE D1 (CutDeck): not one non-empty sequence of that name"]


def _reel(project, name):
    return next(s for s in project["sequences"] if s["name"] == name and s["video_tracks"][0]["clips"])


def test_the_check_fails_a_frame_under_the_nest():
    project = day()
    r4 = _reel(project, "4 REEL SIZE D1")
    r4["video_tracks"][0]["clips"], r4["video_tracks"][2]["clips"] = r4["video_tracks"][2]["clips"], r4["video_tracks"][0]["clips"]
    assert reels.check(project, suffix="") == ["4 REEL SIZE D1: 0 nested clips on V1, need 1"]
    project = day()
    r5 = _reel(project, "5 REEL 1-3 SIZE D1")
    r5["video_tracks"][1]["clips"], r5["video_tracks"][0]["clips"] = r5["video_tracks"][0]["clips"], [frame(179.96)]
    r5["video_tracks"][10]["clips"] = []   # the frame on V1, the nest above it on V2
    assert reels.check(project, suffix="")[0].startswith("5 REEL 1-3 SIZE D1: 0 nested clips on V1")


@pytest.mark.parametrize("change, message", [
    (lambda p: _reel(p, "4 REEL SIZE D1")["video_tracks"][2]["clips"][0].update(end=30.0), "topmost video clip"),
    (lambda p: _reel(p, "4 REEL SIZE D1")["video_tracks"].append(
        {"index": 3, "clips": [clip("title.png", 10.0, 12.0, media_path="t.png")]}), "top track V4"),
    (lambda p: _reel(p, "4 REEL SIZE D1")["video_tracks"][0]["clips"][0].update(end=40.0), "nest 0.00-40.00"),
    (lambda p: _reel(p, "5 REEL 1-3 SIZE D1")["audio_tracks"][0].update(clips=[]), "A1 has no"),
    (lambda p: _reel(p, "2 FACEBOOK D1 Copy 01")["video_tracks"][2]["clips"].append(
        clip(reels.LOGO, 0.0, 179.96)), "is not '2 FACEBOOK D1' minus its one"),
    (lambda p: _reel(p, "4 REEL SIZE D1").update(frame=[1080, 1080]), "frame [1080, 1080]"),
])
def test_the_check_fails_a_reel_off_the_rule(change, message):
    project = day()
    change(project)
    problems = reels.check(project, suffix="")
    assert any(message in p for p in problems), problems


# --- the user's saved projects ------------------------------------------------------------------

def _days():
    if not ROOT.is_dir():
        return [], []
    from cutdeck.hks_gold import day_folders
    return day_folders(ROOT)


@lru_cache(maxsize=None)
def _read(folder):
    from cutdeck.prproj_reader import read_project
    project, = sorted((Path(folder) / "4. PROJECTS" / "1. PREMIERE PRO").glob("*.prproj"))
    return read_project(project)


needs_g = pytest.mark.skipif(not ROOT.is_dir(), reason="the user's HKS projects (G:) are not mounted")


@needs_g
@pytest.mark.parametrize("folder", _days()[0], ids=lambda f: f.name[:8])
def test_the_check_passes_the_users_own_reels(folder):
    project = _read(str(folder))
    if not any(s["name"].startswith("4 REEL SIZE D") and reels._has_clips(s) for s in project["sequences"]):
        pytest.skip("the user has not made this day's reels yet")
    assert reels.check(project, suffix="") == []


@needs_g
@pytest.mark.parametrize("folder", _days()[0], ids=lambda f: f.name[:8])
def test_the_plan_reads_every_tuning_day(folder):
    project = _read(str(folder))
    if folder.name.startswith("20261020"):  # two identical non-empty 2 FACEBOOK D1: the panel cannot pick
        with pytest.raises(ValueError, match="cannot tell them apart"):
            reels.plan(project, reels.find_frame(project["path"]))
        return
    calls = reels.plan(project, reels.find_frame(project["path"]))
    assert Path(calls[4]["args"]["items"][0]["media"]).is_file()
    for c in calls:
        driver_commands.COMMANDS[c["command"]].prepare(c["args"], None)


@needs_g
def test_the_check_fails_the_users_reel_with_the_frame_moved_under_the_nest():
    folder = _days()[0][-1]
    project = copy.deepcopy(_read(str(folder)))
    r4 = _reel(project, "4 REEL SIZE D1")
    top = max(i for i, t in enumerate(r4["video_tracks"]) if t["clips"])
    r4["video_tracks"][0]["clips"], r4["video_tracks"][top]["clips"] = r4["video_tracks"][top]["clips"], r4["video_tracks"][0]["clips"]
    assert reels.check(project, suffix="") == ["4 REEL SIZE D1: 0 nested clips on V1, need 1"]
