import json

import pytest

from cutdeck import hks_gate_store as store


@pytest.fixture(autouse=True)
def own_key(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "KEY", tmp_path / "key")


def seq(guid, name, end=10.0, label=3):
    clip = {"start": 0.0, "end": end, "source_in": 0.0, "source_out": end, "media_path": "a.mp4", "label": label}
    return {"guid": guid, "name": name, "video_tracks": [{"clips": [clip]}], "audio_tracks": [{"clips": [clip]}]}


def record(s, failed=()):
    return {"guid": s["guid"], "cut_hash": store.cut_hash(s), "time": "t", "failed": list(failed),
            "gates": {"same_frame_share": {"value": 0.7, "line": 0.46}}}


def test_status_follows_the_saved_cut_not_the_name(tmp_path):
    path = tmp_path / "r.jsonl"
    draft, other = seq("g1", "1 YOUTUBE agent v1"), seq("g2", "Editing")
    store.append(record(draft, failed=["same_frame_share"]), path)
    rows = {r["guid"]: r for r in store.status({"sequences": [draft, other]}, path)}
    assert rows["g1"]["status"] == "fail"
    assert rows["g1"]["failed"] == [{"gate": "same_frame_share", "value": 0.7, "line": 0.46}]
    assert rows["g2"] == {**rows["g2"], "status": "ungated", "why": "never gated"}

    renamed = {**draft, "name": "1 YOUTUBE D1"}
    assert store.status({"sequences": [renamed]}, path)[0]["status"] == "fail"

    edited = seq("g1", "1 YOUTUBE agent v1", end=9.0)
    row = store.status({"sequences": [edited]}, path)[0]
    assert (row["status"], row["why"]) == ("ungated", "changed after its last gate run")


def test_a_label_change_is_an_edit():
    assert store.cut_hash(seq("g", "a", label=3)) != store.cut_hash(seq("g", "a", label=14))


def test_a_record_written_by_hand_is_not_trusted(tmp_path):
    path = tmp_path / "r.jsonl"
    draft = seq("g1", "1 YOUTUBE agent v1")
    store.append(record(draft, failed=["same_frame_share"]), path)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({**record(draft), "time": "later"}) + "\n")  # a forged pass
    row = store.status({"sequences": [draft]}, path)[0]
    assert (row["status"], row["why"]) == ("ungated", "record not signed by the helper")
