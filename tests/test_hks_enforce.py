import pytest

from cutdeck import hks_enforce


def seq(name="d", guid="g", end=100.0):
    clip = {"start": 0.0, "end": end, "source_in": 0.0, "source_out": end, "media_path": "a.mp4"}
    return {"name": name, "guid": guid, "video_tracks": [], "audio_tracks": [{"clips": [clip]}]}


def gate(passed, kind="control", status="kept"):
    return {"value": 0.7, "line": 0.46, "direction": "max", "kind": kind, "status": status, "passed": passed}


def test_a_failed_control_and_each_unanswered_rule_fail_the_handover():
    found = {"same_frame_share": gate(False), "day_setup": gate(False, kind="warning")}
    v = hks_enforce.judge(seq(), found, 10.0, {"HKS-R1": "opens on 2:10 'ผมไป...'", "HKS-R2": "  "}, {},
                          {"HKS-R1": "q", "HKS-R2": "q"})
    assert v["failed"] == ["same_frame_share"]
    assert v["answers_missing"] == ["HKS-R2"]
    assert v["warned"] == ["day_setup"]


def test_an_override_waives_a_control_but_stays_listed():
    v = hks_enforce.judge(seq(), {"same_frame_share": gate(False)}, 0.0, {}, {"same_frame_share": "why"}, {})
    assert v["failed"] == [] and v["warned"] == ["same_frame_share"]


def test_a_body_start_past_the_hook_and_sting_fails():
    assert hks_enforce.judge(seq(end=6000.0), {}, 32.0, {}, {}, {})["failed"] == []
    assert hks_enforce.judge(seq(end=6000.0), {}, 600.0, {}, {}, {})["failed"] == ["body_range"]


def test_a_name_two_sequences_share_is_refused_but_the_guid_finds_it():
    project = {"sequences": [seq("1 YOUTUBE D1", "a"), seq("1 YOUTUBE D1", "b")]}
    with pytest.raises(ValueError, match="2 sequences"):
        hks_enforce.find_sequence(project, "1 YOUTUBE D1")
    assert hks_enforce.find_sequence(project, "b")["guid"] == "b"


def test_an_override_with_no_reason_is_refused_before_anything_runs(tmp_path):
    with pytest.raises(ValueError, match="written reason"):
        hks_enforce.handover(tmp_path / "x.prproj", "d", 0.0, None, {}, {"same_frame_share": " "}, "agent")


def test_every_active_do_confirm_rule_needs_an_answer():
    required = hks_enforce.do_confirm_rules()
    assert required and all(q.strip() for q in required.values())


def test_a_sequence_made_after_the_baseline_is_new_whatever_its_name(tmp_path, monkeypatch):
    from cutdeck import prproj_reader
    project = {"sequences": [seq("Editing", "e"), seq("1 YOUTUBE D1", "y")]}
    monkeypatch.setattr(prproj_reader, "read_project", lambda path: project)
    monkeypatch.setattr(hks_enforce, "_SAVED", {})
    monkeypatch.setattr(hks_enforce.hks_gate_store, "KEY", tmp_path / "key")
    (tmp_path / "day.prproj").write_text("x")
    kw = {"store": tmp_path / "r.jsonl", "baseline": tmp_path / "b.json"}
    assert {r["new"] for r in hks_enforce.status(tmp_path / "day.prproj", **kw)} == {None}
    hks_enforce.status(tmp_path / "day.prproj", mark_baseline=True, **kw)
    project["sequences"].append(seq("1 YOUTUBE D1", "dup"))  # a menu Duplicate renamed like the final
    hks_enforce._SAVED.clear()  # a new save
    rows = {r["guid"]: r for r in hks_enforce.status(tmp_path / "day.prproj", **kw)}
    assert (rows["y"]["new"], rows["dup"]["new"], rows["dup"]["status"]) == (False, True, "ungated")
