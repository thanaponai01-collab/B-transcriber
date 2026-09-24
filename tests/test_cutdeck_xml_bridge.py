"""Unit tests for cutdeck.xml_bridge — the rough-cut job lifecycle."""

import asyncio
import time
from pathlib import Path
import pytest

from cutdeck.xml_bridge import XmlJobs

SAMPLE_XML_PATH = Path(__file__).parent / "fixtures" / "cutdeck_recut_sample_scrubbed.xml"


@pytest.fixture(autouse=True)
def _media_check_stub(monkeypatch):
    """These tests drive the job with the xml_recut child stubbed; the source-media check
    it runs first is covered in test_cutdeck_xml_audio_extract.py."""
    from cutdeck import xml_bridge
    monkeypatch.setattr(xml_bridge, "check_reference_audio",
                        lambda *_: {"xml_track": 0, "clip_count": 1, "files": ["clip.wav"]})


def test_parse_progress():
    from cutdeck.xml_bridge import parse_progress

    assert parse_progress("PROGRESS:50:Transcribing speech\r\n") == {"pct": 50, "stage": "Transcribing speech"}
    assert parse_progress("PROGRESS:150:Overshoot")["pct"] == 100
    assert parse_progress("PROGRESS:5:  Extracting audio  ") == {"pct": 5, "stage": "Extracting audio"}
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
cuts = sys.argv[sys.argv.index('--cuts-json') + 1]
json.dump({{'cuts_frames': [], 'ticks_per_frame': '1', 'sequence_duration_frames': 1,
           'report': {{'cuts_applied': 0}}}}, open(cuts, 'w'))
"""
    real_exec = asyncio.create_subprocess_exec

    def fake_exec(*args, **kwargs):
        return real_exec(sys.executable, "-u", "-c", fake, *args[4:], **kwargs)

    monkeypatch.setattr(xml_bridge.asyncio, "create_subprocess_exec", fake_exec)
    # Only _run's subprocess handling is under test, not the export-dependent lookups.
    monkeypatch.setattr(xml_bridge, "range_from_ticks", lambda *_: (0, 10))
    monkeypatch.setattr(xml_bridge, "reference_audio_track", lambda *_: None)

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
            if status.get("progress", {}).get("pct") == 50:  # past the helper's own media check
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


def _run_cut_with_fake_child(tmp_path, monkeypatch, script):
    """Drive one cut job whose xml_recut child is `script` (given the real child's
    arguments in sys.argv); return (jobs, final status)."""
    import sys
    from cutdeck import xml_bridge

    real_exec = asyncio.create_subprocess_exec
    spawned = []

    async def spawn(*a, **k):
        proc = await real_exec(sys.executable, "-u", "-c", script, *a[4:], **k)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(xml_bridge.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(xml_bridge, "range_from_ticks", lambda *_: (0, 10))
    monkeypatch.setattr(xml_bridge, "reference_audio_track", lambda *_: None)

    async def _drive():
        jobs = XmlJobs(tmp_path / "jobs")
        prep = await jobs.dispatch({
            "type": "prepare", "project_id": "p", "sequence_id": "s", "sequence_name": "Seq",
            "audio_track": None, "audio_track_count": 1, "asr": False,
            "in_ticks": "0", "out_ticks": "1", "end_ticks": "1", "ticks_per_frame": "1"})
        Path(prep["source_path"]).write_text(SAMPLE_XML_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        await jobs.dispatch({"type": "start", "job_id": prep["job_id"]})
        await asyncio.wait_for(asyncio.gather(*jobs.tasks), 30)
        status = await jobs.dispatch({"type": "status", "job_id": prep["job_id"]})
        return jobs, status, spawned[0].returncode

    return asyncio.run(_drive())


def test_failed_child_keeps_last_progress_and_log(tmp_path, monkeypatch):
    script = """
import sys
print('PROGRESS:40:Detecting speech', flush=True)
print('boom', file=sys.stderr, flush=True)
sys.exit(3)
"""
    jobs, status, _ = _run_cut_with_fake_child(tmp_path, monkeypatch, script)
    assert status["state"] == "failed" and "exit 3): boom." in status["message"]
    assert status["progress"] == {"pct": 40, "stage": "Detecting speech"}
    assert "boom" in Path(status["log_path"]).read_text(encoding="utf-8")
    assert jobs.active is None


def test_oversize_output_line_does_not_orphan_the_child(tmp_path, monkeypatch):
    """A >limit line (tqdm-style output) must fail the job cleanly and stop the child.
    Otherwise the helper reports itself idle while the child still holds the GPU."""
    script = """
import sys, time
sys.stdout.write('x' * (2 << 20) + chr(10)); sys.stdout.flush()
time.sleep(60)
"""
    jobs, status, child_returncode = _run_cut_with_fake_child(tmp_path, monkeypatch, script)
    assert status["state"] == "failed"
    assert jobs.active is None
    assert child_returncode is not None, "child still running after the job failed"


_NATIVE_CHILD = """
import json, sys
path = sys.argv[sys.argv.index('--cuts-json') + 1]
cuts = json.loads(sys.argv[-1])
json.dump({'cuts_frames': cuts, 'ticks_per_frame': '8475667200', 'sequence_duration_frames': 300,
           'report': {'cuts_applied': len(cuts), 'removed_frames': 0, 'reasons': []}},
          open(path, 'w'))
"""


@pytest.mark.parametrize("cuts, state", [([[10, 20]], "ready"), ([], "no_cuts")])
def test_panel_jobs_return_a_cut_list_and_write_no_xml(tmp_path, monkeypatch, cuts, state):
    """The panel's XML output route is retired: every panel job is native."""
    import json
    script = _NATIVE_CHILD.replace("sys.argv[-1]", repr(json.dumps(cuts)))
    _, status, _ = _run_cut_with_fake_child(tmp_path, monkeypatch, script)
    assert status["output"] == "native"
    assert status["state"] == state
    assert status["cuts"]["cuts_frames"] == cuts
    assert status["report"]["cuts_applied"] == len(cuts)
    assert "output_path" not in status
    assert not list(Path(status["log_path"]).parent.glob("*.xml")) or         [p.name for p in Path(status["log_path"]).parent.glob("*.xml")] == ["source.xml"]


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows console flags")
def test_restarted_helper_gets_a_hidden_console_not_none(tmp_path, monkeypatch):
    """A DETACHED_PROCESS helper has no console, so each ffmpeg/ffprobe it runs pops a visible
    console window (reproduced 2026-09-24). CREATE_NO_WINDOW gives it a hidden one to inherit."""
    import subprocess
    from cutdeck import xml_bridge
    seen = {}
    monkeypatch.setattr(xml_bridge.subprocess, "Popen", lambda *a, **k: seen.update(k))
    xml_bridge.spawn_replacement(7891, tmp_path)
    assert seen["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert not seen["creationflags"] & subprocess.DETACHED_PROCESS
