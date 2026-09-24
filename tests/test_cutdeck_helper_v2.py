"""Helper v2 (docs/arch-design-helper-v2.md): request ids answered out of order, pushed job
events, the CPU lane, jobs that outlive the helper, and the panel as the Premiere driver.
Every test talks to a real helper socket on an ephemeral port."""

import asyncio
import json
import time

import pytest

from cutdeck import xml_bridge
from cutdeck.ai_backend import Backend
from cutdeck.xml_bridge import PPRO_TICKS_PER_SECOND, XmlJobs, serve


async def _with_helper(jobs, body):
    server = await serve(jobs, 0)
    try:
        return await body(server.sockets[0].getsockname()[1])
    finally:
        server.close()
        await server.wait_closed()


def _connect(port):
    from websockets.asyncio.client import connect
    return connect(f"ws://127.0.0.1:{port}", max_size=1 << 24)


async def _recv(ws, timeout=5):
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


def test_replies_carry_the_request_id_and_do_not_wait_for_slower_ones(tmp_path, monkeypatch):
    """A slow frame_bounds (on its worker thread) doesn't hold up a status sent after it."""
    monkeypatch.setattr(xml_bridge.frame_bounds, "measure_request",
                        lambda *_: (time.sleep(0.5), {"bounds": None})[1])

    async def body(port):
        async with _connect(port) as ws:
            await ws.send(json.dumps({"id": 1, "type": "frame_bounds"}))
            await ws.send(json.dumps({"id": 2, "type": "status", "job_id": "0" * 32}))
            first, second = await _recv(ws), await _recv(ws)
        assert (first["id"], first["ok"]) == (2, False) and "Unknown job" in first["message"]
        assert (second["id"], second["ok"], second["bounds"]) == (1, True, None)

    asyncio.run(_with_helper(XmlJobs(tmp_path), body))


def test_a_request_without_an_id_gets_a_reply_without_one(tmp_path):
    async def body(port):
        async with _connect(port) as ws:
            await ws.send(json.dumps({"type": "hello", "version": xml_bridge.VERSION}))
            reply = await _recv(ws)
        assert reply["ok"] and "id" not in reply

    asyncio.run(_with_helper(XmlJobs(tmp_path), body))


def test_a_one_megabyte_request_is_read(tmp_path):
    """The old 64 KB cap closed the socket at ~200 clips; a JSON sequence read is bigger."""
    async def body(port):
        async with _connect(port) as ws:
            await ws.send(json.dumps({"id": "big", "type": "status", "job_id": "x", "pad": "p" * (1 << 20)}))
            reply = await _recv(ws)
        assert reply["id"] == "big" and "Unknown job" in reply["message"]

    asyncio.run(_with_helper(XmlJobs(tmp_path), body))


def _media(folder):
    path = folder / "A.mp4"
    path.write_bytes(b"")
    return str(path)


def test_watch_pushes_progress_then_the_finished_job(tmp_path, monkeypatch):

    def slow_loader(*_):
        while not release_flag:
            time.sleep(0.01)
        raise RuntimeError("no audio stream")  # a finding in the plan, not a failed job

    release_flag = False
    monkeypatch.setattr(xml_bridge, "_load_audio", slow_loader)
    jobs = XmlJobs(tmp_path / "jobs")

    async def body(port):
        nonlocal release_flag
        async with _connect(port) as ws:
            await ws.send(json.dumps({"id": 1, "type": "plan_sync",
                                      "clips": [{"id": "a", "path": _media(tmp_path), "duration_s": 5}]}))
            job = await _recv(ws)
            await ws.send(json.dumps({"id": 2, "type": "watch", "job_id": job["job_id"]}))
            watched = await _recv(ws)
            assert watched["id"] == 2 and watched["state"] == "running"
            release_flag = True
            events = []
            while not events or events[-1]["job"]["state"] == "running":
                events.append(await _recv(ws))
        assert all(e["event"] == "job" and e["job"]["job_id"] == job["job_id"] for e in events)
        assert events[-1]["job"]["state"] == "ready"
        assert events[-1]["job"]["plan"]["placements"][0]["status"] == "no_audio"
        assert not jobs.watchers  # a finished job keeps no watchers

    asyncio.run(_with_helper(jobs, body))


def test_watching_a_finished_job_just_returns_it(tmp_path):
    jobs = XmlJobs(tmp_path)
    folder = tmp_path / ("a" * 32)
    folder.mkdir()
    jobs.jobs["a" * 32] = {"job_id": "a" * 32, "job_type": "cut", "state": "no_cuts"}

    async def body(port):
        async with _connect(port) as ws:
            await ws.send(json.dumps({"id": 1, "type": "watch", "job_id": "a" * 32}))
            assert (await _recv(ws))["state"] == "no_cuts"
        assert not jobs.watchers

    asyncio.run(_with_helper(jobs, body))


# --- move 4: jobs survive a helper restart ---------------------------------------------------

def _saved_job(folder, job_id, **fields):
    (folder / job_id).mkdir(parents=True)
    job = {"job_id": job_id, "job_type": "cut", **fields}
    (folder / job_id / "job.json").write_text(json.dumps(job), encoding="utf-8")


def test_a_job_running_when_the_helper_stopped_reads_as_interrupted(tmp_path):
    _saved_job(tmp_path, "b" * 32, state="running", progress={"pct": 40, "stage": "Transcribing"})
    _saved_job(tmp_path, "c" * 32, state="ready", cuts={"cuts_frames": [[1, 2]]})
    _saved_job(tmp_path, "d" * 32, state="prepared", source_path=str(tmp_path / "source.xml"))

    async def _test():
        jobs = XmlJobs(tmp_path)  # a fresh helper: nothing in memory
        running = await jobs.dispatch({"type": "status", "job_id": "b" * 32})
        assert running["state"] == "interrupted" and "restarted" in running["message"]
        saved = json.loads((tmp_path / ("b" * 32) / "job.json").read_text(encoding="utf-8"))
        assert saved["state"] == "interrupted"
        assert (await jobs.dispatch({"type": "status", "job_id": "c" * 32}))["cuts"] == {"cuts_frames": [[1, 2]]}
        # Prepared is still startable: its source is on disk, and start reads it from there.
        assert (await jobs.dispatch({"type": "status", "job_id": "d" * 32}))["state"] == "prepared"
        for bad in ("../" + "e" * 29, "E" * 32, 7, None, "f" * 32):
            with pytest.raises(ValueError, match="Unknown job"):
                await jobs.dispatch({"type": "status", "job_id": bad})

    asyncio.run(_test())


def test_mcp_reports_an_interrupted_job(tmp_path):
    _saved_job(tmp_path, "b" * 32, state="running")

    async def body(port):
        return await Backend(port).status("b" * 32)

    view = asyncio.run(_with_helper(XmlJobs(tmp_path), body))
    assert view["state"] == "interrupted"


# --- move 3: the panel as the Premiere driver ------------------------------------------------

async def _driver(port, answer, commands=("read_sequence", "apply_cuts", "add_markers")):
    """A stand-in panel: registers, then answers each call with `answer(call)`."""
    ws = await _connect(port).__aenter__()
    await ws.send(json.dumps({"id": "r", "type": "register_driver", "commands": list(commands)}))
    assert (await _recv(ws))["registered"]
    calls = []

    async def loop():
        async for raw in ws:
            call = json.loads(raw)
            calls.append(call)
            reply = answer(call)
            if reply is not None:
                await ws.send(json.dumps({"type": "driver_reply", "call": call["call"], **reply}))

    return ws, calls, asyncio.create_task(loop())


def test_a_premiere_command_round_trips_through_the_panel(tmp_path):
    async def body(port):
        ws, calls, task = await _driver(port, lambda c: {"ok": True, "result": {"name": "Seq 1"}})
        backend = Backend(port)
        assert await backend.premiere_status() == {
            "connected": True, "commands": ["read_sequence", "apply_cuts", "add_markers"]}
        assert await backend.premiere("read_sequence") == {"name": "Seq 1"}
        assert calls[0]["command"] == "read_sequence" and calls[0]["args"] == {}
        task.cancel()
        await ws.close()

    asyncio.run(_with_helper(XmlJobs(tmp_path), body))


def test_without_a_panel_the_command_says_to_open_it(tmp_path):
    async def body(port):
        with pytest.raises(ValueError, match="open the CutDeck panel"):
            await Backend(port).premiere("read_sequence")
        assert (await Backend(port).premiere_status())["connected"] is False

    asyncio.run(_with_helper(XmlJobs(tmp_path), body))


def test_a_panel_that_disconnects_fails_the_pending_call(tmp_path):
    async def body(port):
        ws, calls, task = await _driver(port, lambda c: None)  # never answers
        pending = asyncio.create_task(Backend(port).premiere("read_sequence"))
        while not calls:
            await asyncio.sleep(0.01)
        task.cancel()
        await ws.close()
        with pytest.raises(ValueError, match="disconnected"):
            await pending
        with pytest.raises(ValueError, match="open the CutDeck panel"):
            await Backend(port).premiere("read_sequence")

    asyncio.run(_with_helper(XmlJobs(tmp_path), body))


def test_the_panels_refusal_is_the_callers_error(tmp_path):
    async def body(port):
        ws, _, task = await _driver(port, lambda c: {"ok": False, "message": "CutDeck panel is busy"})
        with pytest.raises(ValueError, match="panel is busy"):
            await Backend(port).premiere("read_sequence")
        task.cancel()
        await ws.close()

    asyncio.run(_with_helper(XmlJobs(tmp_path), body))


def test_apply_cuts_sends_a_finished_jobs_cut_list_and_nothing_else(tmp_path):
    jobs = XmlJobs(tmp_path)
    cuts = {"cuts_frames": [[10, 20]], "ticks_per_frame": "8475667200", "sequence_duration_frames": 900}
    jobs.jobs["a" * 32] = {"job_id": "a" * 32, "job_type": "cut", "state": "ready", "cuts": cuts,
                           "context": {"sequence_id": "seq-guid", "sequence_name": "Interview"},
                           "result_name": "Interview — CutDeck aaaaaaaa"}
    jobs.jobs["b" * 32] = {"job_id": "b" * 32, "job_type": "cut", "state": "running"}
    jobs.jobs["c" * 32] = {"job_id": "c" * 32, "job_type": "transcribe", "state": "ready"}

    async def body(port):
        ws, calls, task = await _driver(port, lambda c: {"ok": True, "result": {"cuts": 1}})
        backend = Backend(port)
        assert await backend.premiere("apply_cuts", {"job_id": "a" * 32}) == {"cuts": 1}
        assert calls[0]["args"] == {"cuts": cuts, "sequence_id": "seq-guid", "sequence_name": "Interview",
                                    "result_name": "Interview — CutDeck aaaaaaaa"}
        for job_id in ("b" * 32, "c" * 32):
            with pytest.raises(ValueError, match="finished rough cut"):
                await backend.premiere("apply_cuts", {"job_id": job_id})
        with pytest.raises(ValueError, match="Unknown job"):
            await backend.premiere("apply_cuts", {"job_id": "d" * 32})
        assert len(calls) == 1  # refused requests never reach the panel
        task.cancel()
        await ws.close()

    asyncio.run(_with_helper(jobs, body))


def test_add_markers_reach_the_panel_as_exact_ticks(tmp_path):
    async def body(port):
        ws, calls, task = await _driver(port, lambda c: {"ok": True, "result": {"added": 1}})
        backend = Backend(port)
        await backend.premiere("add_markers", {"markers": [
            {"start_s": 1.5, "duration_s": 0.25, "name": "cut 1", "comment": "removed 0.3 s"}]})
        assert calls[0]["args"]["markers"] == [{
            "start_ticks": str(PPRO_TICKS_PER_SECOND * 3 // 2), "duration_ticks": str(PPRO_TICKS_PER_SECOND // 4),
            "name": "cut 1", "comment": "removed 0.3 s"}]
        for bad in ([], [{"start_s": -1}], [{"start_s": "1"}], [{"start_s": 1, "name": 5}], "x",
                    [{"start_s": 1}] * (xml_bridge.MAX_MARKERS + 1)):
            with pytest.raises(ValueError):
                await backend.premiere("add_markers", {"markers": bad})
        assert len(calls) == 1
        task.cancel()
        await ws.close()

    asyncio.run(_with_helper(XmlJobs(tmp_path), body))


def test_only_the_fixed_commands_exist(tmp_path):
    async def body(port):
        ws, calls, task = await _driver(port, lambda c: {"ok": True, "result": None}, commands=["read_sequence"])
        backend = Backend(port)
        with pytest.raises(ValueError, match="Unknown Premiere command"):
            await backend.premiere("eval", {"code": "app.quit()"})
        with pytest.raises(ValueError, match="does not offer add_markers"):
            await backend.premiere("add_markers", {"markers": [{"start_s": 0}]})
        async with _connect(port) as other:
            await other.send(json.dumps({"id": 1, "type": "register_driver", "commands": ["eval"]}))
            assert "Unknown driver commands" in (await _recv(other))["message"]
        assert calls == []
        task.cancel()
        await ws.close()

    asyncio.run(_with_helper(XmlJobs(tmp_path), body))


# --- the command line for outside scripts -------------------------------------------------------

def test_cli_runs_each_command_through_the_panel(tmp_path):
    import argparse
    from cutdeck import premiere_cli
    markers = tmp_path / "markers.json"
    markers.write_text(json.dumps([{"start_s": 2, "name": "check"}]), encoding="utf-8")

    async def body(port):
        ws, calls, task = await _driver(port, lambda c: {"ok": True, "result": {"did": c["command"]}})
        backend = Backend(port)
        for command, target in (("read_sequence", None), ("add_markers", str(markers))):
            out = await premiere_cli.run(argparse.Namespace(command=command, target=target), backend)
            assert out == {"did": command}
        assert calls[1]["args"]["markers"][0]["start_ticks"] == str(2 * PPRO_TICKS_PER_SECOND)
        assert (await premiere_cli.run(argparse.Namespace(command="status", target=None), backend))["connected"]
        task.cancel()
        await ws.close()

    asyncio.run(_with_helper(XmlJobs(tmp_path), body))


def test_cli_without_a_helper_says_how_to_start_it(capsys):
    import socket
    from cutdeck import premiere_cli
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert premiere_cli.main(["read_sequence", "--port", str(port)]) == 1
    assert "python -m cutdeck.xml_bridge" in capsys.readouterr().err


def test_measure_text_via_helper(tmp_path):
    async def body(port):
        async with _connect(port) as ws:
            await ws.send(json.dumps({
                "id": 10,
                "type": "measure_text",
                "text": "Testing 123",
                "font_size": 50,
            }))
            reply = await _recv(ws)
            assert reply["id"] == 10
            assert reply["ok"] is True
            bounds = reply["bounds"]
            assert bounds["width"] > 0
            assert bounds["height"] > 0
            assert bounds["advance"] > 0

    asyncio.run(_with_helper(XmlJobs(tmp_path), body))
