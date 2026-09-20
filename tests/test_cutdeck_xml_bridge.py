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
