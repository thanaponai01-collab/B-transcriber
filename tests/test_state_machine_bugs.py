"""State-machine bugs found in docs/state-machines.md, fixed 2026-11-09. Each test failed on
the code before its fix for the reason in its docstring."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

import clubfriday.server as cf_server
from cutdeck.helper import Jobs


def test_helper_refuses_new_job_once_it_agreed_to_restart(tmp_path, monkeypatch):
    """`restart` is refused while a job runs, so restarting and an active job must never coexist.
    But nothing re-checks `restarting` when a job is created: a submit that lands after the restart
    reply is launched, then cancelled when the helper exits ("Helper stopped during processing")."""
    media = tmp_path / "a.wav"
    media.write_bytes(b"RIFF")

    async def idle(self, job):
        await asyncio.sleep(10)
    monkeypatch.setattr(Jobs, "_run_transcribe", idle)

    async def body():
        jobs = Jobs(tmp_path / "jobs")
        assert (await jobs.dispatch({"type": "restart"})) == {"restarting": True}
        try:
            with pytest.raises(ValueError, match="restarting"):
                await jobs.dispatch({"type": "submit_transcribe", "media_path": str(media)})
        finally:
            for task in jobs.tasks:
                task.cancel()
        assert not (jobs.restarting and jobs.active), "restarting with a job running"

    asyncio.run(body())


class _ForgottenJobBackend:
    """The helper accepted the audio, then no longer knows the job (its job.json is gone or
    unreadable): `status` is refused with ValueError("Unknown job…") on every later poll."""

    def __init__(self, project_path):
        self.context = {"sequence_name": "Ep 1", "sequence_id": "s1", "project_id": "p1",
                        "project_path": str(project_path)}

    async def premiere_status(self):
        return {"connected": True, "commands": ["read_audio_range"]}

    async def premiere(self, command, args=None):
        return {"sequence": {}, "context": self.context}

    async def transcribe(self, media_path):
        return {"job_id": "job1"}

    async def result(self, job_id, offset=0, limit=100):
        raise ValueError("Unknown job; start a new operation")


def test_clubfriday_session_fails_when_helper_forgets_its_job(tmp_path, monkeypatch):
    """A refused status ("Unknown job") is permanent, unlike a stopped helper (RuntimeError).
    get_session treats both as a connection blip, so the session stays 'transcribing' and the
    page polls it forever. The panel's own Resume already treats "Unknown job" as final."""
    from types import SimpleNamespace
    from transcribe.timebase import Timebase
    seq = SimpleNamespace(tracks=[object()], ticks_per_frame=254016000000 // 25, timebase=Timebase(25, 1))
    monkeypatch.setattr(cf_server, "from_panel_json", lambda _: seq)
    monkeypatch.setattr(cf_server, "range_from_ticks", lambda s, c: (25, 75))
    project = tmp_path / "p.prproj"
    project.write_text("x")

    def extractor(snapshot, path, track):
        open(path, "wb").write(b"RIFF")
        return {"audio_track": 0, "offset_ms": 0}

    app = cf_server.create_app(tmp_path / "sessions", _ForgottenJobBackend(project), extractor)
    with TestClient(app) as client:
        sid = client.post("/api/sessions", json={}).json()["id"]
        for _ in range(100):
            session = client.get(f"/api/sessions/{sid}").json()
            if session.get("helper_job_id") or session["state"] == "failed":
                break
            time.sleep(0.05)
        for _ in range(3):  # the page keeps polling
            session = client.get(f"/api/sessions/{sid}").json()
        assert session["state"] == "failed", f"stuck in {session['state']!r}"
        assert "start a new range" in session["error"]
