"""Range geometry and job lifecycle for the Premiere XML wrapper."""
import asyncio
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from cutdeck.contracts import CUT, KEEP, CutPlan, CutSpan, Timebase
from cutdeck.xml_recut import recut
from cutdeck.xml_sequence import frame_to_ticks
from cutdeck.xml_bridge import XmlJobs, range_from_ticks, reference_audio_track, serve, VERSION


@pytest.fixture(autouse=True)
def _media_check_stub(monkeypatch):
    """These tests drive the job with the xml_recut child stubbed; the source-media check
    it runs first is covered in test_cutdeck_xml_audio_extract.py."""
    from cutdeck import xml_bridge
    monkeypatch.setattr(xml_bridge, "check_reference_audio",
                        lambda *_: {"xml_track": 0, "clip_count": 1, "files": ["clip.wav"]})


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
                in_ticks=str(frame_to_ticks(60, tb)), out_ticks=str(frame_to_ticks(120, tb)),
                end_ticks=str(frame_to_ticks(300, tb)), ticks_per_frame=str(frame_to_ticks(1, tb)),
                audio_track=None, asr=True, sequence={
                    "ticks_per_frame": str(frame_to_ticks(1, tb)), "end_ticks": str(frame_to_ticks(300, tb)),
                    "audio_tracks": [{"enabled": True, "clips": [{
                        "path": "C:/media/clip.wav", "enabled": True, "start_ticks": "0",
                        "in_ticks": "0", "out_ticks": str(frame_to_ticks(300, tb))}]}]})


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
        assert clips[1].findtext("pproTicksIn") == str(frame_to_ticks(120, Timebase(30, 1)))


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


class EmptyStdout:
    """Stands in for a child process that printed nothing."""

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


def test_real_fixture_audio_grouping():
    xml = (Path(__file__).parent / "fixtures/cutdeck_recut_sample_scrubbed.xml").read_text(encoding="utf-8")
    tracks = ET.fromstring(xml).findall("sequence/media/audio/track")
    count = sum(t.get("currentExplodedTrackIndex", "0") == "0" for t in tracks)
    assert reference_audio_track(xml, {"audio_track": 1, "audio_track_count": count}) == 2


def test_job_runs_existing_cli_once_and_returns_the_cut_list(tmp_path, monkeypatch):
    calls = []

    async def subprocess_stub(*args, **kwargs):
        calls.append(args)
        Path(args[args.index("--cuts-json") + 1]).write_text(json.dumps(
            {"cuts_frames": [[70, 80]], "ticks_per_frame": "1", "sequence_duration_frames": 300,
             "report": {"cuts_applied": 1, "removed_frames": 10, "reasons": []}}), encoding="utf-8")

        class Process:
            stdout = EmptyStdout()

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
        assert result["cuts"]["cuts_frames"] == [[70, 80]]
        assert "--out" not in calls[0]
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


# --- sources with real media paths ----------------------------------------------

def source_with_audio(media_path, name="Original"):
    """Same shape as source(), plus one audio clip naming a real media file."""
    from cutdeck.xml_export import _pathurl
    return ('<xmeml><sequence id="original"><uuid>old</uuid>'
            f'<name>{name}</name><duration>300</duration>'
            '<rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate>'
            '<media><video><track><clipitem id="v0"><name>angle</name><start>0</start>'
            '<end>300</end><in>0</in><out>300</out></clipitem><locked>TRUE</locked></track>'
            '</video><audio><track><clipitem id="a0"><name>dialogue</name>'
            '<start>0</start><end>300</end><in>0</in><out>300</out>'
            f'<file id="f0"><pathurl>{_pathurl(media_path)}</pathurl></file>'
            '</clipitem></track></audio></media></sequence></xmeml>')


# --- refusals before the expensive part (issue #28) ------------------------------

def test_start_refusal_fails_the_job_instead_of_leaving_it_prepared(tmp_path):
    async def scenario():
        jobs = XmlJobs(tmp_path)
        job = await jobs.dispatch({"type": "prepare", **{**context(), "in_ticks": "1"}})
        Path(job["source_path"]).write_text(source(), encoding="utf-8")
        request = {"type": "start", "job_id": job["job_id"]}
        started = await jobs.dispatch(request)
        assert started["state"] == "failed"
        assert started["message"].startswith("Cannot start: in_ticks is not aligned")
        assert (await jobs.dispatch(request))["state"] == "failed"  # never retried
        assert jobs.active is None and not jobs.tasks
    asyncio.run(scenario())


def test_missing_source_media_fails_before_the_worker_starts(tmp_path, monkeypatch):
    from cutdeck import xml_bridge
    from cutdeck.xml_sequence import check_reference_audio
    monkeypatch.setattr(xml_bridge, "check_reference_audio", check_reference_audio)
    spawned = []

    async def spawn(*args, **kwargs):
        spawned.append(args)
        raise AssertionError("worker must not start")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async def scenario():
        jobs = XmlJobs(tmp_path / "jobs")
        job = await jobs.dispatch({"type": "prepare", **context()})
        Path(job["source_path"]).write_text(source_with_audio(tmp_path / "offline.mp4"),
                                            encoding="utf-8")
        await jobs.dispatch({"type": "start", "job_id": job["job_id"]})
        await asyncio.gather(*jobs.tasks)
        return await jobs.dispatch({"type": "status", "job_id": job["job_id"]})
    status = asyncio.run(scenario())
    assert status["state"] == "failed"
    assert status["message"].startswith("Cannot analyze this sequence: source media is missing")
    assert not spawned


def test_reference_label_uses_premiere_track_numbers():
    from cutdeck.xml_bridge import reference_label
    stereo = ('<track totalExplodedTrackCount="2" currentExplodedTrackIndex="{0}"/>')
    xml = ('<xmeml><sequence><media><audio>' + stereo.format(0) + stereo.format(1)
           + stereo.format(0) + stereo.format(1) + '</audio></media></sequence></xmeml>')
    checked = {"xml_track": 2, "files": [r"D:\shoot\lav.wav", r"D:\shoot\lav2.wav"]}
    assert reference_label(xml, checked) == "A2 (lav.wav +1 more)"
    assert reference_label(xml, {**checked, "xml_track": 3}) == "XML audio track 4 (lav.wav +1 more)"


def test_failure_detail_is_the_exception_line_not_the_stack(tmp_path):
    from cutdeck.xml_bridge import failure_detail
    log = tmp_path / "process.log"
    log.write_text("PROGRESS:5:Extracting audio\nTraceback (most recent call last):\n"
                   '  File "x.py", line 1, in <module>\n    boom()\n'
                   "RuntimeError: ffmpeg failed extracting D:\a.mov\n\n", encoding="utf-8")
    assert failure_detail(str(log)) == "RuntimeError: ffmpeg failed extracting D:\a.mov"
    assert failure_detail(str(tmp_path / "absent.log")) is None
