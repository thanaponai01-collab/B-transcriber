"""MCP tools are a client of the :7891 helper: one job owner, one job_id space (issue #42)."""
import asyncio
from pathlib import Path
import sys

import pytest

from cutdeck.ai_backend import Backend
from cutdeck.xml_bridge import XmlJobs, serve

SAMPLE_XML = Path(__file__).parent / "fixtures" / "cutdeck_recut_sample_scrubbed.xml"


@pytest.fixture(autouse=True)
def _media_check_stub(monkeypatch):
    """These tests drive the job with the xml_recut child stubbed; the source-media check
    it runs first is covered in test_cutdeck_xml_audio_extract.py."""
    from cutdeck import xml_bridge
    monkeypatch.setattr(xml_bridge, "check_reference_audio",
                        lambda *_: {"xml_track": 0, "clip_count": 1, "files": ["clip.wav"]})

_FAKE_WORKER = (
    "import json, sys, pathlib;"
    "f = pathlib.Path(sys.argv[1]);"
    "json.dump({'kind': 'transcribe', 'timing_unit': 'milliseconds', 'granularity': 'phrase_cues',"
    " 'cues': [{'text': str(i)} for i in range(5)]}, open(f / 'result.json', 'w'))"
)


def _serve(tmp_path, monkeypatch, *, worker=_FAKE_WORKER):
    """A real helper socket on an ephemeral port; the worker subprocess is swapped for a stub."""
    real_exec = asyncio.create_subprocess_exec

    async def stub_exec(*args, **kwargs):
        if "cutdeck.ai_worker" in args:
            return await real_exec(sys.executable, "-c", worker, args[-1], **kwargs)
        return await real_exec(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", stub_exec)
    return XmlJobs(tmp_path)


async def _with_helper(jobs, body):
    server = await serve(jobs, 0)
    try:
        port = server.sockets[0].getsockname()[1]
        return await body(Backend(port))
    finally:
        server.close()
        await server.wait_closed()


def test_mcp_started_transcribe_is_visible_to_panel_status(tmp_path, monkeypatch):
    media = tmp_path / "clip.wav"
    media.write_bytes(b"RIFF")
    jobs = _serve(tmp_path / "jobs", monkeypatch)

    async def body(backend):
        started = await backend.transcribe(str(media))
        job_id = started["job_id"]
        await asyncio.gather(*jobs.tasks)
        # The panel's own `status` verb, same job_id: the whole point of the move.
        panel_view = await jobs.dispatch({"type": "status", "job_id": job_id})
        assert panel_view["job_id"] == job_id and panel_view["state"] == "ready"
        # And the MCP view maps it onto the published vocabulary.
        assert (await backend.status(job_id))["state"] == "succeeded"
        page = await backend.result(job_id, offset=3, limit=2)
        assert [c["text"] for c in page["cues"]] == ["3", "4"]
        assert page["total_cues"] == 5 and page["next_offset"] is None
        first = await backend.result(job_id, offset=0, limit=2)
        assert first["next_offset"] == 2

    asyncio.run(_with_helper(jobs, body))


def test_mcp_started_rough_cut_is_visible_to_panel_status(tmp_path, monkeypatch):
    jobs = _serve(tmp_path / "jobs", monkeypatch)
    source = tmp_path / "seq.xml"
    source.write_text(SAMPLE_XML.read_text(encoding="utf-8"), encoding="utf-8")

    async def body(backend):
        started = await backend.rough_cut(str(source), speech_protection=False)
        job_id = started["job_id"]
        assert started["kind"] == "rough_cut"
        assert started["state"] in {"running", "failed", "succeeded"}
        panel_view = await jobs.dispatch({"type": "status", "job_id": job_id})
        assert panel_view["job_id"] == job_id
        await asyncio.gather(*jobs.tasks)
        assert (await backend.status(job_id))["job_id"] == job_id
        # The user's own export is an input, never an output: it must be untouched.
        assert source.read_text(encoding="utf-8") == SAMPLE_XML.read_text(encoding="utf-8")

    asyncio.run(_with_helper(jobs, body))


def test_one_gpu_lock_across_panel_and_mcp(tmp_path, monkeypatch):
    media = tmp_path / "clip.wav"
    media.write_bytes(b"RIFF")
    jobs = _serve(tmp_path / "jobs", monkeypatch, worker="import time; time.sleep(30)")

    async def body(backend):
        await backend.transcribe(str(media))
        # The panel asking for a cut while MCP holds the GPU must be refused by the same lock.
        with pytest.raises(ValueError, match="already processing"):
            await jobs.dispatch({"type": "prepare", "project_id": "p", "sequence_id": "s",
                                 "sequence_name": "n", "audio_track": None,
                                 "audio_track_count": 1, "asr": False,
                                 "sequence": {"ticks_per_frame": "1", "end_ticks": "1", "audio_tracks": [{"enabled": True, "clips": [{"path": "C:/media/clip.wav", "enabled": True, "start_ticks": "0", "in_ticks": "0", "out_ticks": "1"}]}]}})
        with pytest.raises(ValueError, match="already processing"):
            await backend.transcribe(str(media))
        for task in jobs.tasks:
            task.cancel()
        await asyncio.gather(*jobs.tasks, return_exceptions=True)

    asyncio.run(_with_helper(jobs, body))


@pytest.mark.parametrize("kwargs, message", [
    (dict(preset="fast"), "preset"),
    (dict(speech_protection="yes"), "speech_protection"),
    (dict(audio_track=-1), "audio_track"),
    (dict(start_frame=5), "frame bounds"),
    (dict(start_frame=9, end_frame=3), "frame bounds"),
])
def test_rough_cut_rejects_bad_arguments(tmp_path, monkeypatch, kwargs, message):
    jobs = _serve(tmp_path / "jobs", monkeypatch)
    source = tmp_path / "seq.xml"
    source.write_text("<xmeml/>", encoding="utf-8")

    async def body(backend):
        with pytest.raises(ValueError, match=message):
            await backend.rough_cut(str(source), **kwargs)
        assert not jobs.jobs  # refused before any job exists

    asyncio.run(_with_helper(jobs, body))


def test_inputs_must_be_absolute_existing_files(tmp_path, monkeypatch):
    jobs = _serve(tmp_path / "jobs", monkeypatch)

    async def body(backend):
        with pytest.raises(ValueError, match="absolute path"):
            await backend.transcribe("relative.wav")
        with pytest.raises(ValueError, match="absolute path"):
            await backend.transcribe(str(tmp_path / "missing.wav"))
        wrong = tmp_path / "seq.txt"
        wrong.write_text("x")
        with pytest.raises(ValueError, match=r"\.xml"):
            await backend.rough_cut(str(wrong))

    asyncio.run(_with_helper(jobs, body))


def test_helper_not_running_is_a_clear_error(tmp_path):
    async def go():
        with pytest.raises(RuntimeError, match="xml_bridge"):
            await Backend(1).status("0" * 32)  # nothing listens on port 1

    asyncio.run(go())


def test_unknown_or_malformed_job_id(tmp_path, monkeypatch):
    jobs = _serve(tmp_path / "jobs", monkeypatch)

    async def body(backend):
        for bad in ("nope", "0" * 32):
            with pytest.raises(ValueError, match="Unknown job"):
                await backend.status(bad)

    asyncio.run(_with_helper(jobs, body))


def test_published_capabilities_vocabulary_is_unchanged():
    # Public MCP contract (issue #42 "Door"): these five names may not change silently.
    assert Backend(1).capabilities()["job_states"] == [
        "queued", "running", "succeeded", "failed", "interrupted"]


def test_state_mapping_covers_every_helper_state():
    for helper_state in ("prepared", "running", "ready", "no_cuts", "failed", "interrupted"):
        assert xml_bridge_state(helper_state) in Backend(1).capabilities()["job_states"]


def xml_bridge_state(state):
    from cutdeck.ai_backend import MCP_STATE
    return MCP_STATE[state]


# --- correctness gate additions -------------------------------------------------

_FAKE_RECUT = (
    "import json, sys;"
    "a = sys.argv; out = a[a.index('--cuts-json') + 1]; cuts = [[10, 20]] if a[-1] == 'CUTS' else [];"
    "json.dump({'cuts_frames': cuts, 'ticks_per_frame': '8467200000', 'sequence_duration_frames': 300,"
    " 'report': {'cuts_applied': len(cuts), 'removed_frames': 10 * len(cuts), 'reasons': []}}, open(out, 'w'))"
)


def _serve_recut(tmp_path, monkeypatch, cuts):
    """Helper whose xml_recut child is a stub that reports `cuts` applied."""
    real_exec = asyncio.create_subprocess_exec

    async def stub_exec(*args, **kwargs):
        if "cutdeck.xml_recut" in args:
            tail = "CUTS" if cuts else "NONE"
            return await real_exec(sys.executable, "-c", _FAKE_RECUT, *args[4:], tail, **kwargs)
        return await real_exec(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", stub_exec)
    return XmlJobs(tmp_path)


def test_no_cuts_job_never_deletes_the_users_export(tmp_path, monkeypatch):
    # An MCP job's source lives in the user's folder: an input, never touched or removed.
    jobs = _serve_recut(tmp_path / "jobs", monkeypatch, cuts=False)
    source = tmp_path / "seq.xml"
    source.write_text(SAMPLE_XML.read_text(encoding="utf-8"), encoding="utf-8")

    async def body(backend):
        job_id = (await backend.rough_cut(str(source), speech_protection=False))["job_id"]
        await asyncio.gather(*jobs.tasks)
        assert (await jobs.dispatch({"type": "status", "job_id": job_id}))["state"] == "no_cuts"
        assert (await backend.status(job_id))["state"] == "succeeded"
        assert source.read_text(encoding="utf-8") == SAMPLE_XML.read_text(encoding="utf-8")
        assert not list((tmp_path / "jobs" / job_id).glob("*.xml")), "no XML is written any more"

    asyncio.run(_with_helper(jobs, body))


def test_cut_job_result_is_the_cut_list(tmp_path, monkeypatch):
    jobs = _serve_recut(tmp_path / "jobs", monkeypatch, cuts=True)
    source = tmp_path / "seq.xml"
    source.write_text(SAMPLE_XML.read_text(encoding="utf-8"), encoding="utf-8")

    async def body(backend):
        job_id = (await backend.rough_cut(str(source), speech_protection=False,
                                          start_frame=0, end_frame=100))["job_id"]
        running = await backend.result(job_id)  # not finished: state view, not a result
        assert running["state"] in {"running", "succeeded"}
        await asyncio.gather(*jobs.tasks)
        result = await backend.result(job_id)
        assert result["kind"] == "rough_cut"
        assert result["cuts_frames"] == [[10, 20]] and result["ticks_per_frame"] == "8467200000"
        assert result["report"]["cuts_applied"] == 1
        assert "output_path" not in result

    asyncio.run(_with_helper(jobs, body))


def test_frame_range_starting_at_zero_is_valid(tmp_path, monkeypatch):
    jobs = _serve_recut(tmp_path / "jobs", monkeypatch, cuts=True)
    source = tmp_path / "seq.xml"
    source.write_text(SAMPLE_XML.read_text(encoding="utf-8"), encoding="utf-8")

    async def body(backend):
        job = await backend.rough_cut(str(source), start_frame=0, end_frame=1)
        assert job["arguments"]["start_frame"] == 0
        await asyncio.gather(*jobs.tasks)

    asyncio.run(_with_helper(jobs, body))


def test_racing_submits_yield_exactly_one_job(tmp_path, monkeypatch):
    # Concurrency property: a concurrent caller sees "free" or "taken", never both claim it.
    media = tmp_path / "clip.wav"
    media.write_bytes(b"RIFF")
    jobs = _serve(tmp_path / "jobs", monkeypatch, worker="import time; time.sleep(30)")

    async def body(backend):
        outcomes = await asyncio.gather(*(backend.transcribe(str(media)) for _ in range(6)),
                                        return_exceptions=True)
        accepted = [o for o in outcomes if isinstance(o, dict)]
        assert len(accepted) == 1 and len(jobs.jobs) == 1
        assert all(isinstance(o, ValueError) for o in outcomes if not isinstance(o, dict))
        for task in jobs.tasks:
            task.cancel()
        await asyncio.gather(*jobs.tasks, return_exceptions=True)

    asyncio.run(_with_helper(jobs, body))


def test_paging_visits_every_cue_exactly_once(tmp_path, monkeypatch):
    media = tmp_path / "clip.wav"
    media.write_bytes(b"RIFF")
    jobs = _serve(tmp_path / "jobs", monkeypatch)

    async def body(backend):
        job_id = (await backend.transcribe(str(media)))["job_id"]
        await asyncio.gather(*jobs.tasks)
        for limit in (1, 2, 5, 7):
            seen, offset = [], 0
            while offset is not None:
                page = await backend.result(job_id, offset=offset, limit=limit)
                seen += [c["text"] for c in page["cues"]]
                offset = page["next_offset"]
            assert seen == ["0", "1", "2", "3", "4"]
        for bad in (dict(offset=-1), dict(limit=0), dict(limit=501), dict(offset="1")):
            with pytest.raises(ValueError, match="offset"):
                await backend.result(job_id, **bad)

    asyncio.run(_with_helper(jobs, body))


def test_failed_worker_is_a_structured_failure_with_error(tmp_path, monkeypatch):
    media = tmp_path / "clip.wav"
    media.write_bytes(b"RIFF")
    jobs = _serve(tmp_path / "jobs", monkeypatch, worker="import sys; sys.exit(3)")

    async def body(backend):
        job_id = (await backend.transcribe(str(media)))["job_id"]
        await asyncio.gather(*jobs.tasks)
        view = await backend.status(job_id)
        assert view["state"] == "failed" and "exit 3" in view["error"]
        assert (await backend.result(job_id))["state"] == "failed"
        assert jobs.active is None  # the GPU slot is released on failure
        await backend.transcribe(str(media))  # and a new job is accepted

    asyncio.run(_with_helper(jobs, body))
