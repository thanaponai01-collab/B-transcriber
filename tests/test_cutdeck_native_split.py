"""The helper side of the native Add Edit probe (cutdeck/native_split.py): one-shot request files
for the Cutter Probe plugin. A fake plugin stands in for tools/native-cutter-spike/CutterProbe.cpp."""

import asyncio
import json

import pytest

from cutdeck import native_split
from cutdeck.helper import Jobs


async def fake_plugin(folder, *, consume=True, answer=True, seen=None):
    """Takes the first request like the plugin: validate, delete, then write the result."""
    while True:
        found = sorted(folder.glob("request-*.txt"))
        if found:
            break
        await asyncio.sleep(0.01)
    request = found[0]
    nonce, expected, created, *rest = request.read_text(encoding="ascii").split("\n")
    if seen is not None:
        seen.append({"file": request.name, "nonce": nonce, "expected": expected, "created": created, "rest": rest})
    if not consume:
        return
    request.unlink()
    if answer:
        (folder / f"result-{nonce}.json").write_text(json.dumps(
            {"schema": 1, "nonce": nonce, "status": "executed", "command": "cmd.sequence.razorateditline.all",
             "timeBefore": expected, "timeAfter": expected}), encoding="utf-8")


def run(folder, expected="00:00:04:00", **plugin):
    async def body():
        task = asyncio.create_task(fake_plugin(folder, **plugin))
        result = await native_split.request_split(expected, folder, timeout_s=0.5, grace_s=0.3)
        await asyncio.wait_for(task, 1)
        return result
    return asyncio.run(body())


def test_a_taken_request_returns_the_plugins_result_and_leaves_no_files(tmp_path):
    seen = []
    result = run(tmp_path, seen=seen)
    assert result["status"] == "executed" and result["time_before"] == "00:00:04:00"
    assert result["command"] == "cmd.sequence.razorateditline.all"
    request = seen[0]
    assert request["file"] == f"request-{request['nonce']}.txt"
    assert len(request["nonce"]) == 32 and int(request["nonce"], 16) >= 0
    assert request["expected"] == "00:00:04:00" and request["created"].isdigit() and request["rest"] == [""]
    assert list(tmp_path.iterdir()) == []


def test_an_untaken_request_is_withdrawn_unrun(tmp_path):
    result = run(tmp_path, consume=False)
    assert result["status"] == "not_picked_up"
    assert list(tmp_path.glob("request-*")) == []


def test_a_request_taken_without_a_result_is_reported_as_unknown(tmp_path):
    result = run(tmp_path, answer=False)
    assert result["status"] == "unknown" and "may have cut" in result["message"]


@pytest.mark.parametrize("bad", [None, "", "4", "00:00:04", "00;00;04;00", "00:00:04:00\ncmd.sequence.lift", 400])
def test_a_malformed_timecode_writes_nothing(tmp_path, bad):
    with pytest.raises(ValueError, match="hh:mm:ss:ff"):
        asyncio.run(native_split.request_split(bad, tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_a_second_request_is_refused_while_one_waits(tmp_path):
    (tmp_path / "request-0123456789abcdef0123456789abcdef.txt").write_text("x", encoding="ascii")
    with pytest.raises(ValueError, match="already waiting"):
        asyncio.run(native_split.request_split("00:00:04:00", tmp_path))
    assert len(list(tmp_path.iterdir())) == 1


def test_the_helper_routes_native_split_request(tmp_path, monkeypatch):
    folder = tmp_path / "spike"
    monkeypatch.setattr(native_split, "FOLDER", folder)
    monkeypatch.setattr(native_split, "PICKUP_TIMEOUT_S", 0.5)
    folder.mkdir()

    async def body():
        task = asyncio.create_task(fake_plugin(folder))
        reply = await Jobs(tmp_path / "jobs").dispatch({"type": "native_split_request", "expected_timecode": "00:00:04:00"})
        await asyncio.wait_for(task, 1)
        return reply

    assert asyncio.run(body())["status"] == "executed"


def test_the_helper_never_forwards_a_client_chosen_command(tmp_path, monkeypatch):
    folder = tmp_path / "spike"
    monkeypatch.setattr(native_split, "FOLDER", folder)
    folder.mkdir()
    seen = []

    async def body():
        task = asyncio.create_task(fake_plugin(folder, seen=seen))
        await Jobs(tmp_path / "jobs").dispatch({"type": "native_split_request", "expected_timecode": "00:00:04:00",
                                                "command": "cmd.sequence.lift", "context": "timeline"})
        await asyncio.wait_for(task, 1)

    asyncio.run(body())
    assert "lift" not in json.dumps(seen) and "timeline" not in json.dumps(seen)
