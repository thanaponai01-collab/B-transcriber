"""Local UXP job service wrapping the working XML CLI, without MCP.

One subprocess at a time keeps GPU use serial and the socket responsive.
Jobs survive panel disconnection; files remain in output/premiere for recovery.
The client cannot choose commands or paths: it receives a unique export path.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from xml.etree import ElementTree as ET

from cutdeck.xml_audio_extract import reference_media_path
from cutdeck.xml_recut import XmlRecutRefusal, _sequence_timebase, _PPRO_TICKS_PER_SECOND

ROOT = Path(__file__).resolve().parent.parent
PORT = 7891
VERSION = "cutdeck-xml-1"


def reference_audio_track(source_xml: str, request: dict) -> int | None:
    """Map Premiere's logical track to FCP7's exploded channel tracks.

    Real exports expand each stereo track into two XML tracks. Treating A2
    as XML index 1 would silently analyze A1 again. Verify the grouping.
    """
    selected = request.get("audio_track")
    if selected is None:
        return None  # Preserve the working command's default exactly.
    tracks = ET.fromstring(source_xml).findall("sequence/media/audio/track")
    groups = []
    index = 0
    while index < len(tracks):
        track = tracks[index]
        count = int(track.get("totalExplodedTrackCount", "1"))
        if count < 1 or index + count > len(tracks):
            raise ValueError("Cannot map the selected audio track from this export")
        for channel in range(count):
            item = tracks[index + channel]
            if (int(item.get("currentExplodedTrackIndex", "0")) != channel
                    or int(item.get("totalExplodedTrackCount", "1")) != count):
                raise ValueError("Audio channel grouping in the export is inconsistent")
        groups.append(index)
        index += count
    if len(groups) != request.get("audio_track_count") or not 0 <= selected < len(groups):
        raise ValueError("Export audio tracks differ from the timeline; refresh and try again")
    return groups[selected]


_ILLEGAL_FILENAME_CHARS = '<>:"/\\|?*'


def _safe_filename(name: str) -> str:
    """Premiere sequence names are free text; file names are not."""
    cleaned = "".join("-" if c in _ILLEGAL_FILENAME_CHARS or ord(c) < 32 else c for c in name)
    return cleaned.strip(" .") or "rough_cut"


def result_path(job: dict, source_xml: str) -> Path:
    """Where the finished rough cut is written: a ``CutDeck`` folder beside the footage.

    The editor works out of the media folder, so the file they import belongs there
    rather than inside this repo. Only the result moves — ``source.xml``, the log and
    the reports stay in the job folder, keeping media folders clean and recovery in
    one place.

    Falls back to the job folder when the media cannot be located or written to. A
    rough cut saved in the wrong place is recoverable; one that never gets written
    because the media sits on a disconnected drive is not.
    """
    try:
        media = reference_media_path(source_xml, job["xml_audio_track"])
        folder = media.parent / "CutDeck"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{_safe_filename(job['result_name'])}.xml"
    except (XmlRecutRefusal, OSError) as exc:
        job["output_note"] = f"Saved in the job folder instead of beside the footage: {exc}"
        return Path(job["source_path"]).parent / "rough_cut.xml"


def range_from_ticks(source_xml: str, request: dict) -> tuple[int, int]:
    """Validate live sequence geometry against the export using exact integers."""
    sequence = ET.fromstring(source_xml).find("sequence")
    if sequence is None:
        raise ValueError("Export contains no sequence")
    tb = _sequence_timebase(sequence)
    tick_num = _PPRO_TICKS_PER_SECOND * tb.fps_den
    duration = int(sequence.findtext("duration", "0"))

    def frame(key):
        value = request.get(key)
        if not isinstance(value, str) or not value.isdigit() or len(value) > 24:
            raise ValueError(f"Missing or invalid {key}; refresh the timeline range")
        numerator = int(value) * tb.fps_num
        result, remainder = divmod(numerator, tick_num)
        if remainder:
            raise ValueError(f"{key} is not aligned to the sequence frame grid")
        return result

    start, end = frame("in_ticks"), frame("out_ticks")
    req_end = frame("end_ticks")
    tb_fps = tb.fps_num / tb.fps_den
    max_pad_frames = max(30, int(tb_fps * 5))
    if abs(req_end - duration) > max_pad_frames:
        raise ValueError("Export duration differs from the captured full sequence; refusing to cut")
    if int(request.get("ticks_per_frame", "0")) * tb.fps_num != tick_num:
        raise ValueError("Export frame rate differs from the captured sequence")
    start = max(0, start)
    end = min(duration, end)
    if not 0 <= start < end <= duration:
        raise ValueError("Set valid timeline In/Out marks inside the sequence")
    return start, end


class XmlJobs:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, dict] = {}
        self.tasks: set[asyncio.Task] = set()
        self.active: str | None = None

    async def dispatch(self, req: dict) -> dict:
        if not isinstance(req, dict):
            raise ValueError("Expected an object")
        kind = req.get("type")
        if kind == "hello":
            if req.get("version") != VERSION:
                raise ValueError("Panel/helper version mismatch")
            return {"version": VERSION}
        if kind == "prepare":
            if self.active:
                raise ValueError("CutDeck is already processing a sequence")
            if len(self.jobs) >= 1000:
                raise ValueError("Restart the helper before creating more jobs")
            job_id = uuid.uuid4().hex
            folder = self.directory / job_id
            folder.mkdir()
            context = {key: req.get(key) for key in (
                "project_id", "sequence_id", "sequence_name", "in_ticks", "out_ticks",
                "end_ticks", "ticks_per_frame", "audio_track", "audio_track_count", "asr",
            )}
            if not all(isinstance(context[k], str) and context[k] for k in
                       ("project_id", "sequence_id", "sequence_name")):
                raise ValueError("Missing source project or sequence identity")
            track = context["audio_track"]
            if track is not None and (type(track) is not int or track < 0):
                raise ValueError("Audio track must be a non-negative index")
            if type(context["asr"]) is not bool:
                raise ValueError("Speech protection must be true or false")
            job = {"job_id": job_id, "state": "prepared", "context": context,
                   "source_path": str(folder / "source.xml"),
                   "output_path": str(folder / "rough_cut.xml"),
                   "result_name": f"{context['sequence_name']} — CutDeck {job_id[:8]}",
                   "log_path": str(folder / "process.log")}
            self.jobs[job_id] = job
            self._save(job)
            return dict(job)
        job = self.jobs.get(req.get("job_id"))
        if job is None:
            raise ValueError("Unknown job; start a new rough cut")
        if kind == "status":
            return dict(job)
        if kind == "start":
            if job["state"] != "prepared":
                return dict(job)  # duplicate request must never run a second cut
            if self.active:
                raise ValueError("CutDeck is already processing a sequence")
            source = Path(job["source_path"])
            source_xml = source.read_text(encoding="utf-8-sig")
            start, end = range_from_ticks(source_xml, job["context"])
            job["xml_audio_track"] = reference_audio_track(source_xml, job["context"])
            # Only now does the export exist, so only now is the footage location known.
            job["output_path"] = str(result_path(job, source_xml))
            job["range_frames"] = [start, end]
            job["state"] = "running"
            self.active = job["job_id"]
            self._save(job)
            task = asyncio.create_task(self._run(job))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            return dict(job)
        raise ValueError("Unknown request type")

    def _save(self, job):
        (Path(job["source_path"]).parent / "job.json").write_text(
            json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    async def _run(self, job):
        process = None
        try:
            folder = Path(job["source_path"]).parent
            report_path = folder / "report.json"
            start, end = job["range_frames"]
            args = [sys.executable, "-u", "-m", "cutdeck.xml_recut", job["source_path"],
                    "--out", job["output_path"], "--report", str(report_path),
                    "--config", str(ROOT / "transcribe/config.yaml"),
                    "--overlay", str(ROOT / "transcribe/config.aggressive_cut.yaml"),
                    "--range-start-frame", str(start), "--range-end-frame", str(end),
                    "--no-save-plan"]
            if job["context"]["asr"]:
                args.append("--asr")
            if job["xml_audio_track"] is not None:
                args += ["--audio-track", str(job["xml_audio_track"])]
            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            with open(job["log_path"], "wb") as log:
                process = await asyncio.create_subprocess_exec(
                    *args, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                    **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
                code = await process.wait()
            if code:
                raise RuntimeError(f"CutDeck processing failed (exit {code}). See {job['log_path']}")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            job["report"] = report
            job["state"] = "ready" if report["cuts_applied"] else "no_cuts"
            if job["state"] == "no_cuts":
                # A no-cut result just copies the source; don't leave it sitting in
                # the editor's media folder. The job folder's own copy is kept.
                output = Path(job["output_path"])
                if output.parent != Path(job["source_path"]).parent:
                    output.unlink(missing_ok=True)
            if job["state"] == "ready":
                path = Path(job["output_path"])
                root = ET.fromstring(path.read_text(encoding="utf-8"))
                seq = root.find("sequence")
                seq.find("name").text = job["result_name"]
                seq.set("id", "cutdeck-" + job["job_id"])
                # Avoid reusing Premiere's exported sequence identity on import.
                for identity in list(seq.findall("uuid")):
                    seq.remove(identity)
                path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'
                                + ET.tostring(root, encoding="unicode"), encoding="utf-8")
        except asyncio.CancelledError:
            if process and process.returncode is None:
                process.terminate()
                await process.wait()
            job["state"] = "failed"
            job["message"] = "Helper stopped during processing; start a new rough cut"
            raise
        except Exception as exc:
            job["state"] = "failed"
            job["message"] = str(exc)
        finally:
            self.active = None
            self._save(job)


async def serve(jobs: XmlJobs, port: int = PORT):
    from websockets.asyncio.server import serve as ws_serve

    async def connection(socket):
        async for raw in socket:
            try:
                req = json.loads(raw)
                response = {"ok": True, **await jobs.dispatch(req)}
            except Exception as exc:
                response = {"ok": False, "message": str(exc)}
            await socket.send(json.dumps(response, ensure_ascii=False))

    # Reject ordinary website origins; the local UXP client has no web origin.
    return await ws_serve(connection, "127.0.0.1", port,
                          origins=[None, "null", "file://"], max_size=65536)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="CutDeck Premiere XML helper")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--jobs-dir", type=Path, default=ROOT / "output/premiere")
    args = parser.parse_args()

    async def run():
        jobs = XmlJobs(args.jobs_dir)
        server = await serve(jobs, args.port)
        print(f"CutDeck ready on ws://127.0.0.1:{args.port}", flush=True)
        async with server:
            await asyncio.Future()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
