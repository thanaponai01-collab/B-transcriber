"""The helper restarts itself on `restart`, so a panel start picks up edited helper code
(user request 2026-09-23: a stale helper kept running the old matcher). Runs a real helper process."""

import asyncio
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

import pytest

from cutdeck.xml_bridge import VERSION, XmlJobs

ROOT = Path(__file__).resolve().parent.parent


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _ask(port, request):
    from websockets.asyncio.client import connect
    async with connect(f"ws://127.0.0.1:{port}") as ws:
        await ws.send(json.dumps(request))
        return json.loads(await ws.recv())


def _hello(port):
    try:
        return asyncio.run(_ask(port, {"type": "hello", "version": VERSION}))
    except OSError:
        return None


def _wait_for_hello(port, not_pid=None, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        reply = _hello(port)
        if reply and reply.get("ok") and reply["pid"] != not_pid:
            return reply
        time.sleep(0.2)
    raise AssertionError("no helper answered")


def _kill(pid):
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def test_restart_replaces_the_process_on_the_same_port(tmp_path):
    port = _free_port()
    first = subprocess.Popen([sys.executable, "-m", "cutdeck.xml_bridge", "--port", str(port),
                              "--jobs-dir", str(tmp_path)], cwd=ROOT,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    replacement = None
    try:
        old = _wait_for_hello(port)
        assert old["pid"] == first.pid or first.poll() is None
        assert asyncio.run(_ask(port, {"type": "restart"})) == {"ok": True, "restarting": True}
        assert first.wait(timeout=15) == 0, "the old helper exits cleanly"
        replacement = _wait_for_hello(port, not_pid=old["pid"])
        assert replacement["version"] == VERSION
    finally:
        _kill(first.pid)
        if replacement:
            _kill(replacement["pid"])


def test_restart_is_refused_while_a_job_runs(tmp_path):
    async def _test():
        jobs = XmlJobs(tmp_path)
        jobs.active = "some-job"
        with pytest.raises(ValueError, match="processing a job"):
            await jobs.dispatch({"type": "restart"})
        assert not jobs.restarting and not jobs.stop.is_set()

    asyncio.run(_test())
