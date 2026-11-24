"""Every Premiere command the helper runs is logged (#129), so a save diff minus the log is the
user's own edit. Talks to a real helper socket with a stand-in panel."""

import ast
import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

from cutdeck import helper
from cutdeck.ai_backend import Backend
from cutdeck.helper import Jobs

from tests.test_cutdeck_helper_v2 import _driver, _with_helper


def _log(tmp_path):
    return [json.loads(line) for line in (tmp_path / "premiere_commands.jsonl").read_text("utf-8").splitlines()]


def _calls(records):
    """call id -> (start record, end record or None)"""
    out = {}
    for r in records:
        if r["event"] == "start":
            out[r["call"]] = [r, None]
        else:
            out[r["call"]][1] = r
    return out


def test_each_command_logs_a_start_and_an_end_with_its_arguments_and_result(tmp_path):
    def answer(call):
        return {"ok": True, "result": {"name": "Seq 1"} if call["command"] == "read_sequence" else {"added": 1}}

    async def body(port):
        ws, _, task = await _driver(port, answer)
        backend = Backend(port)
        await backend.premiere("read_sequence")
        await backend.premiere("add_markers", {"markers": [{"start_s": 1.5, "name": "cut 1"}]})
        task.cancel()
        await ws.close()

    asyncio.run(_with_helper(Jobs(tmp_path), body))
    (read_start, read_end), (write_start, write_end) = _calls(_log(tmp_path)).values()
    assert (read_start["command"], read_start["hint"], read_start["args"]) == ("read_sequence", "read", {})
    assert read_end["ok"] is True and "result" not in read_end and read_end["result_bytes"] > 0
    assert (write_start["command"], write_start["hint"]) == ("add_markers", "write")
    assert write_start["args"] == {"markers": [{"start_s": 1.5, "name": "cut 1"}]}
    assert write_end == {**write_end, "ok": True, "result": {"added": 1}}
    times = [datetime.fromisoformat(r["time"]) for r in (read_start, read_end, write_start, write_end)]
    assert times == sorted(times) and all(t.tzinfo for t in times)


def test_a_refused_command_logs_its_error(tmp_path):
    async def body(port):
        ws, _, task = await _driver(port, lambda c: {"ok": False, "message": "No sequence is open"})
        with pytest.raises(ValueError, match="No sequence is open"):
            await Backend(port).premiere("read_sequence")
        task.cancel()
        await ws.close()

    asyncio.run(_with_helper(Jobs(tmp_path), body))
    ((_, end),) = _calls(_log(tmp_path)).values()
    assert end["ok"] is False and "No sequence is open" in end["error"]


def test_a_helper_command_logs_the_panel_calls_it_makes(tmp_path, monkeypatch):
    from cutdeck import menu
    monkeypatch.setattr(menu, "invoke", lambda path, front=False: {"menu": path})

    async def body(port):
        ws, _, task = await _driver(port, lambda c: {"ok": True, "result": {"name": "Edit"}},
                                    commands=["read_sequence", "open_sequence"])
        await Backend(port).premiere("menu_command", {"path": "Clip > Unlink"})
        task.cancel()
        await ws.close()

    asyncio.run(_with_helper(Jobs(tmp_path), body))
    starts = [r["command"] for r in _log(tmp_path) if r["event"] == "start"]
    assert starts == ["menu_command", "read_sequence", "read_sequence"]


def test_every_logged_call_names_its_caller_including_nested_panel_calls(tmp_path, monkeypatch):
    from cutdeck import menu
    monkeypatch.setattr(menu, "invoke", lambda path, front=False: {"menu": path})
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "session-a")

    async def body(port):
        ws, _, task = await _driver(port, lambda c: {"ok": True, "result": {"name": "Edit"}},
                                    commands=["read_sequence", "open_sequence"])
        await Backend(port).premiere("menu_command", {"path": "Clip > Unlink"})
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "session-b")
        await Backend(port).premiere("read_sequence")
        task.cancel()
        await ws.close()

    asyncio.run(_with_helper(Jobs(tmp_path), body))
    starts = [(r["command"], r["caller"].split()[-1]) for r in _log(tmp_path) if r["event"] == "start"]
    assert starts == [("menu_command", "session-a"), ("read_sequence", "session-a"),
                      ("read_sequence", "session-a"), ("read_sequence", "session-b")]


def test_the_socket_client_sends_its_caller(tmp_path, monkeypatch):
    from cutdeck import helper_protocol
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "session-c")

    async def body(port):
        ws, _, task = await _driver(port, lambda c: {"ok": True, "result": {"name": "Edit"}})
        await asyncio.to_thread(helper_protocol.ask, {"type": "premiere", "command": "read_sequence"}, port)
        task.cancel()
        await ws.close()

    asyncio.run(_with_helper(Jobs(tmp_path), body))
    (start,) = [r for r in _log(tmp_path) if r["event"] == "start"]
    assert start["caller"].endswith(" session-c")


def test_a_command_still_running_has_a_start_and_no_end(tmp_path):
    async def body(port):
        ws, _, task = await _driver(port, lambda c: None)  # the panel never answers
        call = asyncio.create_task(Backend(port).premiere("read_sequence"))
        for _ in range(100):
            if (tmp_path / "premiere_commands.jsonl").exists():
                break
            await asyncio.sleep(0.01)
        records = _log(tmp_path)
        call.cancel()
        task.cancel()
        await ws.close()
        return records

    records = asyncio.run(_with_helper(Jobs(tmp_path), body))
    assert [r["event"] for r in records] == ["start"]


def test_only_jobs_premiere_reaches_the_panel():
    # The log lives in Jobs.premiere. Any other caller of _call_driver would run a Premiere
    # command the log never sees, and its edit would be blamed on the user.
    tree = ast.parse(Path(helper.__file__).read_text("utf-8"))
    callers = [fn.name for fn in ast.walk(tree) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
               for node in ast.walk(fn) if isinstance(node, ast.Attribute) and node.attr == "_call_driver"
               and isinstance(node.ctx, ast.Load)]
    assert callers == ["premiere"], (
        f"_call_driver is used in {callers}: route the call through Jobs.premiere so it is logged")
