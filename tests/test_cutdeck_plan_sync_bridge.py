"""cutdeck.xml_bridge `plan_sync`: native Sync's matching job (docs/HANDOFF_CUTDECK_NATIVE_SYNC.md
step 2A). The helper matches clips by audio; the panel places them. Audio is served by the
synthetic Shoot of test_cutdeck_sync_plan.py, so no ffmpeg or real media is needed."""

import asyncio
import json
from pathlib import Path
import threading

import pytest

from cutdeck import xml_bridge
from cutdeck.xml_bridge import VERSION, XmlJobs
from tests.test_cutdeck_sync_plan import Shoot, event


def _media(folder, *names):
    paths = []
    for name in names:
        path = folder / name
        path.write_bytes(b"")
        paths.append(str(path))
    return paths


def _one_clip(path):
    return {"type": "plan_sync", "clips": [{"id": "a", "path": path, "duration_s": 5}]}


@pytest.mark.parametrize("clips, message", [
    (None, "non-empty list"),
    ([], "non-empty list"),
    ([{"id": "a", "path": "relative.mp4", "duration_s": 5}], "absolute path"),
    ([{"id": "a", "path": "MISSING", "duration_s": 5}], "absolute path"),
    ([{"id": "", "path": "A", "duration_s": 5}], "unique"),
    ([{"id": "a", "path": "A", "duration_s": 5}, {"id": "a", "path": "A", "duration_s": 5}], "unique"),
    ([{"id": "a", "path": "A", "duration_s": 0}], "positive"),
    ([{"id": "a", "path": "A", "duration_s": "5"}], "positive"),
    ([{"id": "a", "path": "A", "duration_s": True}], "positive"),
])
def test_bad_request_is_refused_without_claiming_the_slot(tmp_path, clips, message):
    (a,) = _media(tmp_path, "A.mp4")
    for clip in clips or []:
        clip["path"] = {"A": a, "MISSING": str(tmp_path / "gone.mp4")}.get(clip["path"], clip["path"])

    async def _test():
        jobs = XmlJobs(tmp_path / "jobs")
        with pytest.raises(ValueError, match=message):
            await jobs.dispatch({"type": "plan_sync", "clips": clips})
        assert jobs.active is None and not jobs.jobs

    asyncio.run(_test())


def test_places_clips_and_reports_progress(tmp_path, monkeypatch):
    shoot = Shoot()
    talk = event(40.0, seed=1)
    shoot.clip("cam1", talk, "talk", 0.0, 30.0)
    shoot.clip("cam2", talk, "talk", 12.0, 40.0)
    shoot.add("drone", None)
    ids = ["cam1", "cam2", "drone"]
    paths = dict(zip(ids, _media(tmp_path, "cam1.mp4", "cam2.mp4", "drone.mp4")))
    live = {}
    stages = []

    def loader(path, rate, start_s, duration_s):
        stages.append(live["job"]["progress"]["stage"])
        return shoot.loader(path, rate, start_s, duration_s)

    monkeypatch.setattr(xml_bridge, "_load_audio", loader)

    async def _test():
        jobs = XmlJobs(tmp_path / "jobs")
        started = await jobs.dispatch({"type": "plan_sync", "clips": [
            {"id": cid, "path": paths[cid], "duration_s": 30.0} for cid in ids]})
        assert started["state"] == "running" and started["job_type"] == "plan_sync"
        live["job"] = jobs.jobs[started["job_id"]]  # the dict the worker thread updates
        await asyncio.gather(*jobs.tasks)
        assert jobs.active is None
        return await jobs.dispatch({"type": "status", "job_id": started["job_id"]})

    done = asyncio.run(_test())
    assert done["state"] == "ready", done.get("message")
    plan = done["plan"]
    assert plan["sessions"] == 1
    got = {p["id"]: p for p in plan["placements"]}
    assert list(got) == ids, "placements keep the request's order"
    assert set(got["cam1"]) == {"id", "status", "start_s", "session", "matched_to", "confidence",
                                "drift_ms", "reason", "media_duration_s"}
    assert abs((got["cam2"]["start_s"] - got["cam1"]["start_s"]) - 12.0) < 0.001
    assert got["cam2"]["status"] == "synced" and got["cam2"]["matched_to"] == "cam1"
    assert got["drone"]["status"] == "no_audio" and got["drone"]["media_duration_s"] is None
    assert abs(got["cam1"]["media_duration_s"] - 30.0) < 0.01
    assert stages[:3] == ["Reading audio 0/3", "Reading audio 1/3", "Reading audio 2/3"]
    assert any(s.startswith("Matching") for s in stages)
    saved = json.loads((tmp_path / "jobs" / done["job_id"] / "job.json").read_text(encoding="utf-8"))
    assert saved["plan"] == plan


def test_holds_the_one_job_slot(tmp_path, monkeypatch):
    (a,) = _media(tmp_path, "A.mp4")
    release = threading.Event()

    def blocked_loader(*_):
        release.wait(5)
        raise RuntimeError("no audio stream")

    monkeypatch.setattr(xml_bridge, "_load_audio", blocked_loader)

    async def _test():
        jobs = XmlJobs(tmp_path / "jobs")
        first = await jobs.dispatch(_one_clip(a))
        with pytest.raises(ValueError, match="already processing"):
            await jobs.dispatch(_one_clip(a))
        with pytest.raises(ValueError, match="already processing"):
            await jobs.dispatch({"type": "prepare", "project_id": "p", "sequence_id": "s", "sequence_name": "n"})
        release.set()
        await asyncio.gather(*jobs.tasks)
        # An unreadable clip is a finding in the plan, not a failed job.
        assert jobs.jobs[first["job_id"]]["state"] == "ready"
        assert jobs.jobs[first["job_id"]]["plan"]["placements"][0]["status"] == "no_audio"
        second = await jobs.dispatch(_one_clip(a))
        await asyncio.gather(*jobs.tasks)
        assert jobs.jobs[second["job_id"]]["state"] == "ready"

    asyncio.run(_test())


def test_failure_is_reported_and_frees_the_slot(tmp_path, monkeypatch):
    (a,) = _media(tmp_path, "A.mp4")

    def broken(*_args, **_kwargs):
        raise MemoryError("out of memory")

    monkeypatch.setattr("cutdeck.sync_plan.plan_sync", broken)

    async def _test():
        jobs = XmlJobs(tmp_path / "jobs")
        job = await jobs.dispatch(_one_clip(a))
        await asyncio.gather(*jobs.tasks)
        assert jobs.active is None
        return jobs.jobs[job["job_id"]]

    job = asyncio.run(_test())
    assert job["state"] == "failed" and "out of memory" in job["message"]


def test_version_bump_is_shared_with_the_panel(tmp_path):
    """A panel that sends plan_sync to an old helper must be refused at hello, not mid-job."""
    workflow = (Path(__file__).parent.parent / "uxp" / "cutdeck" / "workflow.js").read_text(encoding="utf-8")
    assert int(VERSION.rsplit("-", 1)[1]) >= 2  # plan_sync arrived in -2
    assert f'const VERSION = "{VERSION}";' in workflow

    async def _test():
        with pytest.raises(ValueError, match="version mismatch"):
            await XmlJobs(tmp_path).dispatch({"type": "hello", "version": "cutdeck-xml-1"})

    asyncio.run(_test())


def test_realistic_200_clip_request_fits_the_socket(tmp_path, monkeypatch):
    """The socket's max_size is 65536 bytes: 200 clips with long Windows paths must get through."""
    from websockets.asyncio.client import connect
    folder = tmp_path / "2026-09-24 Client Name - Wedding Ceremony and Reception" / "Day 1" / "CAM_B_Sony_FX3"
    folder.mkdir(parents=True)
    paths = _media(folder, *[f"C{n:04d}_ceremony_wide_angle_backup.MP4" for n in range(200)])
    assert min(len(p) for p in paths) >= 150, "paths as long as a real shoot's"

    def no_audio(*_):
        raise RuntimeError("stub")

    monkeypatch.setattr(xml_bridge, "_load_audio", no_audio)
    request = {"type": "plan_sync", "clips": [
        {"id": f"clip{n}", "path": p, "duration_s": 1234.567891} for n, p in enumerate(paths)]}

    async def _test():
        jobs = XmlJobs(tmp_path / "jobs")
        server = await xml_bridge.serve(jobs, 0)
        try:
            port = server.sockets[0].getsockname()[1]
            async with connect(f"ws://127.0.0.1:{port}") as socket:
                await socket.send(json.dumps(request))
                reply = json.loads(await socket.recv())
            await asyncio.gather(*jobs.tasks)
        finally:
            server.close()
            await server.wait_closed()
        return reply

    reply = asyncio.run(_test())
    assert reply["ok"], reply
    assert len(reply["clips"]) == 200
