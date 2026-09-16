"""Transport-independent jobs for CutDeck's existing processing tools.

No model code runs in the server. A serial subprocess worker owns each job;
stdout/stderr go to its log, never onto the MCP protocol stream.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent.parent


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class Backend:
    """One owner per job directory, one GPU job at a time."""

    def __init__(self, directory: Path = ROOT / "output/ai"):
        self.directory = directory.resolve()
        self.jobs: dict[str, dict] = {}
        self.tasks: set[asyncio.Task] = set()
        self.serial = asyncio.Lock()
        self._lock_file = None

    def start(self) -> None:
        if self._lock_file is not None:
            raise RuntimeError("Backend already started")
        self.directory.mkdir(parents=True, exist_ok=True)
        lock = (self.directory / "server.lock").open("a+b")
        try:
            lock.seek(0)
            if os.name == "nt":
                import msvcrt
                if not lock.read(1):
                    lock.write(b"0")
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            lock.close()
            raise RuntimeError("Another CutDeck AI backend owns this job directory") from exc
        self._lock_file = lock
        try:
            for path in self.directory.glob("*/job.json"):
                job = json.loads(path.read_text(encoding="utf-8"))
                if job["state"] in {"queued", "running"}:
                    job.update(state="interrupted", error="Backend stopped before completion; submit a new job")
                    write_json(path, job)
                self.jobs[job["job_id"]] = job
        except Exception:
            lock.close()
            self._lock_file = None
            raise

    async def close(self) -> None:
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._lock_file:
            self._lock_file.close()
            self._lock_file = None

    def capabilities(self) -> dict:
        return {
            "version": "1", "tools": ["transcribe", "rough_cut_xml"],
            "live_premiere_control": False,
            "rough_cut_input": "Exported FCP7 sequence XML with accessible source media",
            "rough_cut_output": "New XML file; import into Premiere separately",
            "transcript_timing": "Phrase cues in milliseconds relative to input media",
            "job_states": ["queued", "running", "succeeded", "failed", "interrupted"],
            "serial_processing": True,
        }

    @staticmethod
    def _file(value: str) -> str:
        path = Path(value)
        if not path.is_absolute() or not path.is_file():
            raise ValueError("Input must be an absolute path to an existing local file")
        return str(path.resolve())

    def transcribe(self, media_path: str) -> dict:
        return self._submit("transcribe", {"media_path": self._file(media_path)})

    def rough_cut(self, sequence_xml: str, speech_protection: bool = True,
                  preset: str = "aggressive", audio_track: int | None = None,
                  start_frame: int | None = None, end_frame: int | None = None) -> dict:
        source = self._file(sequence_xml)
        if Path(source).suffix.lower() != ".xml":
            raise ValueError("Expected an exported FCP7 .xml sequence")
        if preset not in {"aggressive", "standard"}:
            raise ValueError("preset must be aggressive or standard")
        if type(speech_protection) is not bool:
            raise ValueError("speech_protection must be boolean")
        if audio_track is not None and (type(audio_track) is not int or audio_track < 0):
            raise ValueError("audio_track must be a non-negative XML audio track index")
        if start_frame is not None or end_frame is not None:
            if (type(start_frame) is not int or type(end_frame) is not int
                    or not 0 <= start_frame < end_frame):
                raise ValueError("Provide both frame bounds with 0 <= start_frame < end_frame")
        return self._submit("rough_cut_xml", dict(sequence_xml=source,
            speech_protection=speech_protection, preset=preset, audio_track=audio_track,
            start_frame=start_frame, end_frame=end_frame))

    def _submit(self, kind: str, arguments: dict) -> dict:
        if self._lock_file is None:
            raise RuntimeError("Backend is not started")
        if sum(j["state"] in {"queued", "running"} for j in self.jobs.values()) >= 16:
            raise ValueError("Job queue is full; wait for existing jobs")
        job_id = uuid.uuid4().hex
        folder = self.directory / job_id
        folder.mkdir()
        job = dict(job_id=job_id, kind=kind, state="queued", arguments=arguments,
                   created_at=datetime.now(timezone.utc).isoformat(),
                   log_path=str(folder / "process.log"))
        self.jobs[job_id] = job
        write_json(folder / "job.json", job)
        task = asyncio.create_task(self._run(job))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return self.status(job_id)

    def status(self, job_id: str) -> dict:
        if not re.fullmatch(r"[0-9a-f]{32}", job_id) or job_id not in self.jobs:
            raise ValueError("Unknown job_id")
        return json.loads(json.dumps(self.jobs[job_id]))

    def result(self, job_id: str, offset: int = 0, limit: int = 100) -> dict:
        job = self.status(job_id)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("offset must be >= 0; limit must be between 1 and 500")
        if job["state"] != "succeeded":
            return job
        result = json.loads((self.directory / job_id / "result.json").read_text(encoding="utf-8"))
        if job["kind"] == "transcribe":
            cues = result.pop("cues")
            result.update(cues=cues[offset:offset + limit], total_cues=len(cues), offset=offset,
                          next_offset=offset + limit if offset + limit < len(cues) else None)
        return {"job_id": job_id, "state": "succeeded", **result}

    async def _run(self, job: dict) -> None:
        process = None
        folder = self.directory / job["job_id"]
        try:
            async with self.serial:
                job["state"] = "running"
                write_json(folder / "job.json", job)
                with Path(job["log_path"]).open("wb") as log:
                    process = await asyncio.create_subprocess_exec(
                        sys.executable, "-u", "-m", "cutdeck.ai_worker", str(folder),
                        cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                        stdout=log, stderr=subprocess.STDOUT,
                        **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
                    code = await process.wait()
                if code != 0:
                    raise RuntimeError(f"Processing failed (exit {code}); see process.log")
                json.loads((folder / "result.json").read_text(encoding="utf-8"))
                job["state"] = "succeeded"
        except asyncio.CancelledError:
            if process is not None and process.returncode is None:
                process.terminate()
                await process.wait()
            job.update(state="interrupted", error="Backend stopped; submit a new job")
            raise
        except Exception as exc:
            job.update(state="failed", error=str(exc))
        finally:
            write_json(folder / "job.json", job)
