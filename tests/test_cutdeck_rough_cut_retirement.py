"""Owner's retirement contract: JSON analysis survives; XML never reaches a worker."""
import asyncio
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_shared_modules_are_independent_of_xml():
    for name in ("helper", "rough_cut", "audio_extract", "sequence_timing"):
        module = importlib.import_module(f"cutdeck.{name}")
        assert "cutdeck.xml_" not in Path(module.__file__).read_text(encoding="utf-8"), "active XML dependency"


def test_xml_tools_are_not_published_or_dispatched(tmp_path):
    from cutdeck.ai_backend import Backend
    from cutdeck.helper import Jobs
    from cutdeck.mcp_server import create_server

    async def scenario():
        backend = Backend(1)
        names = {tool.name for tool in await create_server(backend).list_tools()}
        assert "rough_cut" not in names
        assert "premiere_rough_cut" in names
        assert "rough_cut" not in backend.capabilities()["tools"]
        jobs = Jobs(tmp_path)
        with pytest.raises(ValueError, match="retired.*premiere_rough_cut"):
            await jobs.dispatch({"type": "submit_rough_cut", "sequence_xml": "unused.xml"})
        assert not jobs.jobs and not list(tmp_path.iterdir())
    asyncio.run(scenario())


def test_xml_loader_and_old_cli_refuse_with_replacement(tmp_path):
    from cutdeck import sequence_model
    source = tmp_path / "source.xml"
    source.write_text("<xmeml/>", encoding="utf-8")
    with pytest.raises(ValueError, match="retired"):
        sequence_model.load(source)
    run = subprocess.run([sys.executable, "-m", "cutdeck.xml_recut", str(source)],
                         cwd=ROOT, capture_output=True, text=True)
    assert run.returncode != 0 and "retired" in run.stderr
    assert "premiere_rough_cut" in run.stderr
    assert list(tmp_path.iterdir()) == [source]


def test_old_prepared_xml_job_fails_without_spawning(tmp_path, monkeypatch):
    from cutdeck.helper import Jobs
    job_id = "a" * 32
    folder = tmp_path / job_id
    folder.mkdir()
    job = {"job_id": job_id, "job_type": "cut", "state": "prepared", "context": {},
           "source_path": str(folder / "source.xml")}
    (folder / "job.json").write_text(json.dumps(job), encoding="utf-8")
    async def forbidden(*args, **kwargs):
        pytest.fail("retired job spawned a worker")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    async def scenario():
        jobs = Jobs(tmp_path)
        result = await jobs.dispatch({"type": "start", "job_id": job_id})
        assert result["state"] == "failed" and "retired" in result["message"]
        assert not jobs.tasks and jobs.active is None
    asyncio.run(scenario())
