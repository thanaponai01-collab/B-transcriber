"""Save diff minus the command log (#129): changes between two saves that no logged command
explains are the user's, and the trial passes when they hold half the spoken corrections."""

import copy
from datetime import datetime, timedelta

from cutdeck import save_diff
from cutdeck.helper import Jobs


def _clip(name, start, end, **extra):
    return {"name": name, "start": start, "end": end, "source_in": start, "source_out": end,
            "disabled": False, "effects": [], **extra}


def _project(*sequences):
    return {"path": "x.prproj", "sequences": [
        {"name": name, "markers": [], "frame": [1080, 1920],
         "video_tracks": [{"index": i, "muted": False, "locked": False, "clips": clips}
                          for i, clips in enumerate(tracks)],
         "audio_tracks": []}
        for name, tracks in sequences]}


BASE = _project(("Short", [[_clip("feed.mp4", 0, 5), _clip("feed.mp4", 5, 9)], [_clip("Graphic", 0, 4)]]),
                ("Other", [[_clip("cam.mp4", 0, 3)]]))


def _edit(fn):
    p = copy.deepcopy(BASE)
    fn(p)
    return p


def _kinds(changes):
    return sorted((c["sequence"], c["track"], c["kind"], tuple(c.get("fields", []))) for c in changes)


def test_an_unchanged_save_has_no_changes():
    assert save_diff.diff(BASE, copy.deepcopy(BASE)) == []


def test_a_trim_is_one_changed_clip_with_its_span():
    after = _edit(lambda p: p["sequences"][0]["video_tracks"][1]["clips"][0].update(end=2.1, source_out=2.1))
    [ch] = save_diff.diff(BASE, after)
    assert (ch["sequence"], ch["track"], ch["kind"], ch["fields"]) == ("Short", "V2", "changed", ["end", "source_out"])
    assert (ch["start"], ch["end"]) == (0, 4)


def test_added_and_removed_clips_tracks_and_sequences():
    def edit(p):
        short = p["sequences"][0]
        short["video_tracks"][0]["clips"].pop()  # removed
        short["video_tracks"].append({"index": 2, "muted": False, "locked": False,
                                      "clips": [_clip("CutDeck_Hold_1.png", 1.2, 2.1)]})  # new track + clip
        short["video_tracks"][1]["muted"] = True
        p["sequences"].pop()  # Other deleted
    assert _kinds(save_diff.diff(BASE, _edit(edit))) == [
        ("Other", None, "sequence", ("removed",)),
        ("Short", "V1", "removed", ()),
        ("Short", "V2", "track", ("muted",)),
        ("Short", "V3", "added", ()),
        ("Short", "V3", "track", ("added",)),
    ]


def _save(tmp_path, when: datetime, project, projects):
    path = tmp_path / f"proj--uid-{when:%Y-%m-%d_%H-%M-%S}.prproj"
    path.write_text("")
    projects[path.name] = project
    return path


def _run(tmp_path, monkeypatch, logged, after):
    """Two saves around commands logged now by the helper's own writer."""
    jobs = Jobs(tmp_path / "jobs")
    for command, hint, args in logged:
        jobs._log_command({"call": command, "event": "start", "command": command, "hint": hint, "args": args})
        jobs._log_command({"call": command, "event": "end", "ok": True})
    now, projects = datetime.now(), {}
    saves = [_save(tmp_path, now - timedelta(minutes=1), BASE, projects),
             _save(tmp_path, now + timedelta(minutes=1), after, projects)]
    monkeypatch.setattr(save_diff, "read_project", lambda p: projects[p.name])
    return save_diff.report(saves, save_diff.read_log(jobs.directory / "premiere_commands.jsonl"))


TRIM = _edit(lambda p: p["sequences"][0]["video_tracks"][1]["clips"][0].update(end=2.1, source_out=2.1))


def test_a_write_naming_the_sequence_explains_its_changes(tmp_path, monkeypatch):
    [iv] = _run(tmp_path, monkeypatch, [("edit_clips", "destructive", {"sequence": "Short"})], TRIM)
    assert [len(ch["explained_by"]) for ch in iv["changes"]] == [1]


def test_reads_and_writes_to_other_sequences_explain_nothing(tmp_path, monkeypatch):
    [iv] = _run(tmp_path, monkeypatch, [("read_timeline", "read", {"sequence": "Short"}),
                                        ("build_sequence", "write", {"result_name": "Other"})], TRIM)
    assert [ch["explained_by"] for ch in iv["changes"]] == [[]]


def test_a_write_naming_no_sequence_explains_the_whole_interval(tmp_path, monkeypatch):
    [iv] = _run(tmp_path, monkeypatch, [("key_command", "destructive", {"keys": "ctrl+k"})], TRIM)
    assert [len(ch["explained_by"]) for ch in iv["changes"]] == [1]


def test_score_passes_at_half_the_spoken_corrections():
    intervals = [{"changes": [{"id": "c1", "explained_by": []}, {"id": "c2", "explained_by": ["x"]},
                              {"id": "c3", "explained_by": []}]}]
    half = save_diff.score(intervals, [{"said": "trim title", "change": "c1"},
                                       {"said": "hold", "change": "c2"}])  # c2 is the agent's
    assert (half["found"], half["passed"], half["missed"], half["unclaimed_user_changes"]) == \
        (1, True, ["hold"], ["c3"])
    under = save_diff.score(intervals, [{"said": "a", "change": "c1"}, {"said": "b", "change": None},
                                        {"said": "c", "change": None}])
    assert (under["found"], under["passed"]) == (1, False)
