"""The Premiere driver commands, end to end through the helper, in two modes.

offline  the real helper + the real panel driver (Node) + the fake Premiere, nothing selected.
         Runs in every normal test run.
live     a real Premiere Pro, a running helper and the CutDeck panel. Left out unless you pass
         --live, and then a missing piece FAILS (it never skips). Selected clips are edited only
         with --live-edit.

To run live:
    1. Start the helper:  python -m cutdeck.xml_bridge   (or Start CutDeck.cmd)
    2. Open Premiere Pro with a sequence (In/Out marks set), and open the CutDeck panel
    3. Check the stack:   python -m cutdeck.live_check
    4. Run:               python -m pytest tests/test_cutdeck_live_premiere.py --live -v
"""
import asyncio
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from cutdeck.ai_backend import Backend
from cutdeck.driver_commands import COMMANDS
from cutdeck.xml_bridge import XmlJobs, serve

PANEL = Path(__file__).parent / "fixtures" / "offline_panel.cjs"


@pytest.fixture(scope="module")
def offline_backend(tmp_path_factory):
    if shutil.which("node") is None:
        pytest.fail("the offline driver test needs Node for the panel code")
    loop = asyncio.new_event_loop()
    started = {}
    ready = threading.Event()

    async def boot():
        started["server"] = await serve(XmlJobs(tmp_path_factory.mktemp("jobs")), 0)
        started["port"] = started["server"].sockets[0].getsockname()[1]
        ready.set()

    def run():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(boot())
        loop.run_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert ready.wait(10), "helper did not start"
    panel = subprocess.Popen(["node", str(PANEL), str(started["port"])],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert panel.stdout.readline().strip() == "ready", panel.stderr.read()
        backend = Backend(started["port"])
        assert asyncio.run(backend.premiere_status())["connected"] is True
        yield backend
    finally:
        panel.kill()
        panel.wait()
        async def shutdown():
            started["server"].close()
            await started["server"].wait_closed()

        asyncio.run_coroutine_threadsafe(shutdown(), loop).result(10)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)


@pytest.fixture(scope="module")
def live_backend(request):
    from cutdeck import live_check
    steps, selection = live_check.check()
    report = "\n".join(("  ok   " if s.ok else "  FAIL ") + f"{s.name}: {s.detail}" for s in steps)
    if not steps or not all(s.ok for s in steps):
        pytest.fail("live Premiere stack is not ready:\n" + report, pytrace=False)
    if selection.get("has_selection") and not request.config.getoption("--live-edit"):
        pytest.fail(f"{selection['selected_count']} clip(s) are selected in Premiere and these tests "
                    "edit the selection. Deselect them, or pass --live-edit to allow it.", pytrace=False)
    return Backend()


@pytest.fixture(params=["offline", pytest.param("live", marks=pytest.mark.live)])
def live_backend_or_offline(request):
    return request.getfixturevalue("offline_backend" if request.param == "offline" else "live_backend")


def test_live_premiere_connection_and_commands(live_backend_or_offline):
    status = asyncio.run(live_backend_or_offline.premiere_status())
    assert status["connected"] is True
    # Verify all tabled commands are offered by the live panel
    for cmd in COMMANDS:
        assert cmd in status["commands"]


def test_live_read_sequence(live_backend_or_offline):
    res = asyncio.run(live_backend_or_offline.premiere("read_sequence"))
    assert "name" in res
    assert "sequence_id" in res
    assert "ticks_per_frame" in res
    assert res["video_track_count"] >= 0
    assert res["audio_track_count"] >= 0


def test_live_inspect_selection(live_backend_or_offline):
    res = asyncio.run(live_backend_or_offline.premiere("inspect_selection"))
    assert "sequence_name" in res
    assert "selected_count" in res
    assert isinstance(res["items"], list)
    assert res["selected_count"] == len(res["items"])


def test_live_run_timing_probe(live_backend_or_offline):
    res = asyncio.run(live_backend_or_offline.premiere("run_probe", {"probe": "timing"}))
    assert res["probe"] == "timing"
    report = res["report"]
    assert report.get("probe") == "marks-and-timing"
    assert report.get("complete") is True


def test_live_set_transform_field(live_backend_or_offline):
    sel = asyncio.run(live_backend_or_offline.premiere("inspect_selection"))
    if not sel.get("has_selection"):
        with pytest.raises(Exception, match=r"Select a clip"):
            asyncio.run(live_backend_or_offline.premiere("set_transform_field", {"field": "scale", "value": 100}))
    else:
        res = asyncio.run(live_backend_or_offline.premiere("set_transform_field", {"field": "scale", "value": 100}))
        assert res["field"] == "scale"
        assert res["value"] == 100.0
        assert res["done"] >= 1


def test_live_set_anchor(live_backend_or_offline):
    sel = asyncio.run(live_backend_or_offline.premiere("inspect_selection"))
    if not sel.get("has_selection"):
        with pytest.raises(Exception, match=r"Select a clip"):
            asyncio.run(live_backend_or_offline.premiere("set_anchor", {"target": "center"}))
    else:
        res = asyncio.run(live_backend_or_offline.premiere("set_anchor", {"target": "center"}))
        assert res["target"] == "center"
        assert res["done"] >= 1


def test_live_align_clips(live_backend_or_offline):
    sel = asyncio.run(live_backend_or_offline.premiere("inspect_selection"))
    if not sel.get("has_selection"):
        with pytest.raises(Exception, match=r"Select a clip"):
            asyncio.run(live_backend_or_offline.premiere("align_clips", {"edge": "hcenter", "to": "frame"}))
    else:
        res = asyncio.run(live_backend_or_offline.premiere("align_clips", {"edge": "hcenter", "to": "frame"}))
        assert res["edge"] == "hcenter"
        assert res["to"] == "frame"
        assert res["done"] >= 1


def test_live_distribute_clips(live_backend_or_offline):
    sel = asyncio.run(live_backend_or_offline.premiere("inspect_selection"))
    if not sel.get("has_selection"):
        with pytest.raises(Exception, match=r"Select a clip"):
            asyncio.run(live_backend_or_offline.premiere("distribute_clips", {"kind": "h-centers", "to": "frame"}))
    elif sel["selected_count"] < 3:
        with pytest.raises(Exception, match=r"Select at least 3 clips"):
            asyncio.run(live_backend_or_offline.premiere("distribute_clips", {"kind": "h-centers", "to": "frame"}))
    else:
        res = asyncio.run(live_backend_or_offline.premiere("distribute_clips", {"kind": "h-centers", "to": "frame"}))
        assert res["kind"] == "h-centers"
        assert res["to"] == "frame"
        assert res["done"] >= 3
