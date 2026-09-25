"""End to end over the wire (docs/arch-design-helper-v2.md moves 1 and 3): the panel's real
core/rpc.js and features/driver.js, run by Node, against the real helper socket. Proves both
sides agree on ids, pushed job events and Premiere driver calls; Premiere itself is the fake."""
import asyncio
import json
from pathlib import Path
import shutil
import sys

import pytest

from cutdeck.ai_backend import Backend
from cutdeck.xml_bridge import XmlJobs, serve

CLIENT = Path(__file__).parent / "fixtures" / "panel_wire_client.cjs"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node for the panel code")


def test_the_real_panel_code_and_the_real_helper_agree(tmp_path):
    jobs = XmlJobs(tmp_path)
    job_id = "a" * 32
    (tmp_path / job_id).mkdir()
    jobs.jobs[job_id] = job = {"job_id": job_id, "job_type": "cut", "state": "running",
                               "progress": {"pct": 10, "stage": "Detecting speech"}}

    async def scenario():
        server = await serve(jobs, 0)
        port = server.sockets[0].getsockname()[1]
        panel = await asyncio.create_subprocess_exec(
            "node", str(CLIENT), str(port), job_id, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)

        async def line():
            raw = await asyncio.wait_for(panel.stdout.readline(), 15)
            assert raw, (await panel.stderr.read()).decode()
            return json.loads(raw)

        try:
            assert await line() == {"registered": True}
            assert await line() == {"hello": "cutdeck-xml-5",
                                    "missing": "Unknown job; start a new operation"}
            assert await line() == {"update": "running", "pct": 10}  # the watch reply

            # An outside script asks for markers: helper -> panel driver -> fake Premiere.
            backend = Backend(port)
            assert (await backend.premiere_status())["connected"] is True
            result = await backend.premiere("add_markers", {"markers": [
                {"start_s": 2, "name": "cut 1", "comment": "removed 0.8 s"}]})
            assert result == {"added": 1, "undo_steps": 1}
            ran = await line()
            assert ran["ran"] == "add_markers" and ran["undoSteps"] == ["CutDeck: add markers"]
            assert ran["added"] == [{"name": "cut 1", "start": "508032000000", "comments": "removed 0.8 s"}]

            # The job's progress and end reach the panel as pushed events, with no polling.
            job["progress"] = {"pct": 60, "stage": "Transcribing speech"}
            jobs._notify(job)
            assert await line() == {"update": "running", "pct": 60}
            job["state"] = "no_cuts"
            jobs._notify(job)
            assert (await line())["update"] == "no_cuts"
            assert await line() == {"finished": "no_cuts"}
            assert await asyncio.wait_for(panel.wait(), 10) == 0
        finally:
            if panel.returncode is None:
                panel.kill()
                await panel.wait()
            server.close()
            await server.wait_closed()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(scenario())
