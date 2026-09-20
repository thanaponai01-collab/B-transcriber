"""Unit tests for cutdeck.xml_bridge — handling prepare_sync and start_sync."""

import asyncio
from pathlib import Path
import pytest

from cutdeck.xml_bridge import XmlJobs, VERSION

SAMPLE_XML_PATH = Path(__file__).parent / "fixtures" / "cutdeck_recut_sample_scrubbed.xml"


def test_xml_jobs_prepare_sync(tmp_path):
    async def _test():
        jobs = XmlJobs(tmp_path)

        # Hello check
        hello_res = await jobs.dispatch({"type": "hello", "version": VERSION})
        assert hello_res == {"version": VERSION}

        # Prepare sync request
        req = {
            "type": "prepare_sync",
            "project_id": "proj_123",
            "sequence_id": "seq_456",
            "sequence_name": "MultiCam_Test",
            "audio_track": 0,
            "audio_track_count": 2,
        }
        prep_res = await jobs.dispatch(req)

        assert prep_res["job_type"] == "sync"
        assert prep_res["state"] == "prepared"
        assert prep_res["result_name"] == "MultiCam_Test_Synced"
        assert Path(prep_res["source_path"]).name == "source.xml"
        assert Path(prep_res["output_path"]).name == "synced.xml"

    asyncio.run(_test())


def test_xml_jobs_sync_lifecycle(tmp_path):
    async def _test():
        jobs = XmlJobs(tmp_path)

        req = {
            "type": "prepare_sync",
            "project_id": "proj_123",
            "sequence_id": "seq_456",
            "sequence_name": "MultiCam_Test",
            "audio_track": 0,
            "audio_track_count": 6,
        }
        prep_res = await jobs.dispatch(req)
        job_id = prep_res["job_id"]

        # Write the sample XML to source_path to simulate Premiere export
        source_path = Path(prep_res["source_path"])
        source_path.write_text(SAMPLE_XML_PATH.read_text(encoding="utf-8"), encoding="utf-8")

        # Start sync
        start_res = await jobs.dispatch({"type": "start", "job_id": job_id})
        assert start_res["state"] == "running"

        # Wait for the background task to complete
        if jobs.tasks:
            await asyncio.gather(*jobs.tasks)

        # Check status
        status_res = await jobs.dispatch({"type": "status", "job_id": job_id})
        assert status_res["state"] in ("ready", "failed")
        if status_res["state"] == "ready":
            assert "report" in status_res
            assert status_res["report"]["sequence_name"] == "fixture sequence_Synced"

    asyncio.run(_test())


def test_parse_progress():
    from cutdeck.xml_bridge import parse_progress

    assert parse_progress("PROGRESS:50:Transcribing speech\r\n") == {"pct": 50, "stage": "Transcribing speech"}
    assert parse_progress("PROGRESS:150:Overshoot")["pct"] == 100
    assert parse_progress("wrote out.xml") is None
    assert parse_progress("PROGRESS:abc:x") is None


def test_xml_jobs_cut_reports_progress_while_running(tmp_path, monkeypatch):
    """`status` must show the stage the subprocess last announced, mid-run."""
    import json
    import sys
    from cutdeck import xml_bridge

    go = tmp_path / "go"
    # Stand-in for xml_recut: announce a stage, hold until the test has looked, finish.
    fake = f"""
import sys, json, time, pathlib
print('PROGRESS:50:Transcribing speech', flush=True)
print('a plain log line', flush=True)
while not pathlib.Path({str(go)!r}).exists():
    time.sleep(0.02)
report = sys.argv[sys.argv.index('--report') + 1]
json.dump({{'cuts_applied': 0}}, open(report, 'w'))
"""
    real_exec = asyncio.create_subprocess_exec

    def fake_exec(*args, **kwargs):
        return real_exec(sys.executable, "-u", "-c", fake, *args[args.index("--report") - 1:], **kwargs)

    monkeypatch.setattr(xml_bridge.asyncio, "create_subprocess_exec", fake_exec)
    # Only _run's subprocess handling is under test, not the export-dependent lookups.
    monkeypatch.setattr(xml_bridge, "range_from_ticks", lambda *_: (0, 10))
    monkeypatch.setattr(xml_bridge, "reference_audio_track", lambda *_: None)
    monkeypatch.setattr(xml_bridge, "result_path", lambda job, _xml: Path(job["output_path"]))

    async def _test():
        jobs = XmlJobs(tmp_path / "jobs")
        prep = await jobs.dispatch({
            "type": "prepare", "project_id": "p", "sequence_id": "s", "sequence_name": "Seq",
            "audio_track": None, "audio_track_count": 1, "asr": False,
            "in_ticks": "0", "out_ticks": "1", "end_ticks": "1", "ticks_per_frame": "1"})
        Path(prep["source_path"]).write_text(SAMPLE_XML_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        started = await jobs.dispatch({"type": "start", "job_id": prep["job_id"]})
        assert started["state"] == "running" and "progress" not in started

        status = {}
        for _ in range(200):
            status = await jobs.dispatch({"type": "status", "job_id": prep["job_id"]})
            if "progress" in status:
                break
            await asyncio.sleep(0.05)
        assert status["state"] == "running"
        assert status["progress"] == {"pct": 50, "stage": "Transcribing speech"}

        go.write_text("x")
        await asyncio.gather(*jobs.tasks)
        final = await jobs.dispatch({"type": "status", "job_id": prep["job_id"]})
        assert final["state"] == "no_cuts", final.get("message")
        log = Path(final["log_path"]).read_text(encoding="utf-8")
        assert "PROGRESS:50:Transcribing speech" in log and "a plain log line" in log

    asyncio.run(_test())
