"""Range geometry and job lifecycle for the Premiere XML wrapper."""
import asyncio
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from cutdeck.contracts import CUT, KEEP, CutPlan, CutSpan, Timebase
from cutdeck.xml_recut import recut, _frame_to_ticks
from cutdeck.xml_bridge import XmlJobs, range_from_ticks, reference_audio_track, serve, VERSION


def source(ntsc=False):
    tracks = "".join(f'<track><clipitem id="v{i}"><name>angle</name><start>0</start>'
                     '<end>300</end><in>0</in><out>300</out><pproTicksIn>0</pproTicksIn>'
                     '<pproTicksOut>2540160000000</pproTicksOut></clipitem>'
                     '<locked>TRUE</locked></track>' for i in range(3))
    return ('<xmeml><sequence id="original"><uuid>old</uuid><name>Original</name><duration>300</duration>'
            f'<rate><timebase>30</timebase><ntsc>{str(ntsc).upper()}</ntsc></rate>'
            f'<media><video>{tracks}</video></media></sequence></xmeml>')


def context(ntsc=False):
    tb = Timebase(30000, 1001) if ntsc else Timebase(30, 1)
    return dict(project_id="project", sequence_id="sequence", sequence_name="Original",
                in_ticks=str(_frame_to_ticks(60, tb)), out_ticks=str(_frame_to_ticks(120, tb)),
                end_ticks=str(_frame_to_ticks(300, tb)), ticks_per_frame=str(_frame_to_ticks(1, tb)),
                audio_track=None, asr=True)


def plan():
    return CutPlan(job_id=1, media_sha256="x" * 64, timebase=Timebase(30, 1), spans=[
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=KEEP),
        CutSpan(idx=1, src_in_ms=1000, src_out_ms=5000, action=CUT),
        CutSpan(idx=2, src_in_ms=5000, src_out_ms=10000, action=KEEP)])


def test_scope_preserves_outside_content_and_shifts_all_tracks():
    result, report = recut(source(), plan(), frame_range=(60, 120))
    seq = ET.fromstring(result).find("sequence")
    assert seq.findtext("duration") == "240"
    assert report.removed_frames == 60
    for track in seq.findall("media/video/track"):
        clips = track.findall("clipitem")
        assert [(c.findtext("start"), c.findtext("end"), c.findtext("in"), c.findtext("out"))
                for c in clips] == [("0", "60", "0", "60"), ("60", "240", "120", "300")]
        assert clips[1].findtext("pproTicksIn") == str(_frame_to_ticks(120, Timebase(30, 1)))


def test_scope_no_cuts_is_unchanged():
    result, report = recut(source(), plan(), frame_range=(200, 250))
    assert result == source()
    assert report.cuts_applied == report.removed_frames == 0


@pytest.mark.parametrize("bounds", [(-1, 50), (40, 40), (50, 40), (0, 301)])
def test_invalid_range_refused(bounds):
    with pytest.raises(ValueError):
        recut(source(), plan(), frame_range=bounds)


@pytest.mark.parametrize("ntsc", [False, True])
def test_ticks_use_exact_xml_frame_rate(ntsc):
    assert range_from_ticks(source(ntsc), context(ntsc)) == (60, 120)


@pytest.mark.parametrize("key,value", [("in_ticks", "1"), ("out_ticks", "0"),
                                      ("end_ticks", "0"), ("ticks_per_frame", "1")])
def test_mismatched_live_geometry_refused(key, value):
    with pytest.raises(ValueError):
        range_from_ticks(source(), {**context(), key: value})


def test_selected_stereo_track_maps_to_first_channel_of_correct_group():
    tracks = ''.join(f'<track currentExplodedTrackIndex="{channel}" totalExplodedTrackCount="2"/>'
                     for _ in range(3) for channel in range(2))
    xml = f'<xmeml><sequence><media><audio>{tracks}</audio></media></sequence></xmeml>'
    assert reference_audio_track(xml, {"audio_track": 1, "audio_track_count": 3}) == 2
    assert reference_audio_track(xml, {"audio_track": 2, "audio_track_count": 3}) == 4
    with pytest.raises(ValueError, match="differ"):
        reference_audio_track(xml, {"audio_track": 1, "audio_track_count": 4})


def test_real_fixture_audio_grouping():
    xml = (Path(__file__).parent / "fixtures/cutdeck_recut_sample_scrubbed.xml").read_text(encoding="utf-8")
    tracks = ET.fromstring(xml).findall("sequence/media/audio/track")
    count = sum(t.get("currentExplodedTrackIndex", "0") == "0" for t in tracks)
    assert reference_audio_track(xml, {"audio_track": 1, "audio_track_count": count}) == 2


def test_job_runs_existing_cli_once_and_publishes_named_result(tmp_path, monkeypatch):
    calls = []

    async def subprocess_stub(*args, **kwargs):
        calls.append(args)
        Path(args[args.index("--out") + 1]).write_text(source(), encoding="utf-8")
        Path(args[args.index("--report") + 1]).write_text(
            json.dumps({"cuts_applied": 1, "removed_ms": 2000}), encoding="utf-8")

        class Process:
            async def wait(self):
                return 0
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", subprocess_stub)

    async def scenario():
        jobs = XmlJobs(tmp_path)
        job = await jobs.dispatch({"type": "prepare", **context()})
        Path(job["source_path"]).write_text(source(), encoding="utf-8")
        request = {"type": "start", "job_id": job["job_id"]}
        assert (await jobs.dispatch(request))["state"] == "running"
        assert (await jobs.dispatch(request))["state"] == "running"
        with pytest.raises(ValueError, match="already"):
            await jobs.dispatch({"type": "prepare", **context()})
        await asyncio.gather(*jobs.tasks)
        result = await jobs.dispatch({"type": "status", "job_id": job["job_id"]})
        assert result["state"] == "ready"
        seq = ET.parse(job["output_path"]).find("sequence")
        assert seq.findtext("name") == job["result_name"]
        assert seq.find("uuid") is None
        assert seq.get("id") != "original"
        assert len(calls) == 1
        assert "--asr" in calls[0] and "--no-save-plan" in calls[0]
        assert calls[0][calls[0].index("--range-start-frame") + 1] == "60"
        assert calls[0][calls[0].index("--range-end-frame") + 1] == "120"
    asyncio.run(scenario())


def test_worker_failure_releases_single_job_slot(tmp_path, monkeypatch):
    async def fail(*args, **kwargs):
        raise OSError("worker unavailable")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail)

    async def scenario():
        jobs = XmlJobs(tmp_path)
        job = await jobs.dispatch({"type": "prepare", **context()})
        Path(job["source_path"]).write_text(source(), encoding="utf-8")
        await jobs.dispatch({"type": "start", "job_id": job["job_id"]})
        await asyncio.gather(*jobs.tasks)
        result = await jobs.dispatch({"type": "status", "job_id": job["job_id"]})
        assert result["state"] == "failed"
        assert "worker unavailable" in result["message"]
        assert jobs.active is None
    asyncio.run(scenario())


def test_real_socket_handles_bad_input_and_reconnect(tmp_path):
    from websockets.asyncio.client import connect

    async def scenario():
        server = await serve(XmlJobs(tmp_path), port=0)
        async with server:
            url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
            async with connect(url) as socket:
                await socket.send("[]")
                assert not json.loads(await socket.recv())["ok"]
                await socket.send(json.dumps({"type": "prepare", **context()}))
                job = json.loads(await socket.recv())
                assert job["ok"]
            async with connect(url) as socket:
                await socket.send(json.dumps({"type": "status", "job_id": job["job_id"]}))
                assert json.loads(await socket.recv())["state"] == "prepared"
                await socket.send(json.dumps({"type": "hello", "version": VERSION}))
                assert json.loads(await socket.recv())["version"] == VERSION
    asyncio.run(scenario())
