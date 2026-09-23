"""Local job service for CutDeck's processing tools: the one job owner.

The UXP panel and the MCP server (`cutdeck.ai_backend`) are both clients of this
socket, so there is one job_id space and one GPU lock.
One subprocess at a time keeps GPU use serial and the socket responsive.
Jobs survive panel disconnection; files remain in output/premiere for recovery.
The client cannot choose commands. Panel jobs receive a unique export path; the
MCP `submit_*` verbs take local input files but only ever write inside the job folder.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
from xml.etree import ElementTree as ET

from cutdeck.xml_audio_extract import check_reference_audio, reference_media_path
from cutdeck.xml_recut import XmlRecutRefusal, _sequence_timebase, _PPRO_TICKS_PER_SECOND

ROOT = Path(__file__).resolve().parent.parent
PORT = 7891
VERSION = "cutdeck-xml-1"


_PROGRESS_LINE = re.compile(r"PROGRESS:(\d{1,3}):(.+)")


def parse_progress(line: str) -> dict | None:
    """Read a `PROGRESS:<pct>:<stage>` line written by xml_recut, else None."""
    match = _PROGRESS_LINE.fullmatch(line.strip())
    if match is None:
        return None
    return {"pct": min(int(match.group(1)), 100), "stage": match.group(2).strip()}


def _track_groups(source_xml: str) -> list[int]:
    """The first XML track index of each Premiere audio track.

    Real exports expand each stereo track into two XML tracks. Treating A2
    as XML index 1 would silently analyze A1 again. Verify the grouping.
    """
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
    return groups


def reference_audio_track(source_xml: str, request: dict) -> int | None:
    """Map Premiere's logical track to FCP7's exploded channel tracks."""
    selected = request.get("audio_track")
    if selected is None:
        return None  # Preserve the working command's default exactly.
    groups = _track_groups(source_xml)
    if len(groups) != request.get("audio_track_count") or not 0 <= selected < len(groups):
        raise ValueError("Export audio tracks differ from the timeline; refresh and try again")
    return groups[selected]


def reference_label(source_xml: str, checked: dict) -> str:
    """What the status line says is being analyzed, in Premiere's own track names."""
    try:
        track = f"A{_track_groups(source_xml).index(checked['xml_track']) + 1}"
    except ValueError:
        track = f"XML audio track {checked['xml_track'] + 1}"
    files = checked["files"]
    more = f" +{len(files) - 1} more" if len(files) > 1 else ""
    return f"{track} ({Path(files[0]).name}{more})"


_LOG_NOISE = re.compile(r"PROGRESS:|Traceback \(most recent call last\)|\s")


def failure_detail(log_path: str) -> str | None:
    """The last meaningful line of a child's log: the exception or refusal, not a stack frame."""
    try:
        lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines[-200:]):
        if line.strip() and not _LOG_NOISE.match(line):
            return line.strip()[:300]
    return None


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


def _input_file(value, suffix: str | None = None) -> str:
    path = Path(value) if isinstance(value, str) else None
    if path is None or not path.is_absolute() or not path.is_file():
        raise ValueError("Input must be an absolute path to an existing local file")
    if suffix and path.suffix.lower() != suffix:
        raise ValueError(f"Expected an exported FCP7 {suffix} sequence")
    return str(path.resolve())


def _rough_cut_arguments(req: dict) -> dict:
    """Validate an MCP `submit_rough_cut` request; nothing runs on a bad one."""
    preset = req.get("preset", "aggressive")
    speech_protection = req.get("speech_protection", True)
    audio_track = req.get("audio_track")
    start_frame, end_frame = req.get("start_frame"), req.get("end_frame")
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
    return dict(sequence_xml=_input_file(req.get("sequence_xml"), ".xml"), preset=preset,
                speech_protection=speech_protection, audio_track=audio_track,
                start_frame=start_frame, end_frame=end_frame)


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
        if kind == "prepare" or kind == "prepare_sync":
            job_id, folder = self._allocate()
            is_sync = (kind == "prepare_sync")
            context_keys = ("project_id", "sequence_id", "sequence_name", "audio_track", "audio_track_count")
            if not is_sync:
                context_keys += ("in_ticks", "out_ticks", "end_ticks", "ticks_per_frame", "asr")
            context = {key: req.get(key) for key in context_keys}
            if not all(isinstance(context[k], str) and context[k] for k in
                       ("project_id", "sequence_id", "sequence_name")):
                raise ValueError("Missing source project or sequence identity")
            track = context["audio_track"]
            if track is not None and (type(track) is not int or track < 0):
                raise ValueError("Audio track must be a non-negative index")
            if not is_sync and type(context["asr"]) is not bool:
                raise ValueError("Speech protection must be true or false")
            result_name = f"{context['sequence_name']}_Synced" if is_sync else f"{context['sequence_name']} — CutDeck {job_id[:8]}"
            out_filename = "synced.xml" if is_sync else "rough_cut.xml"
            log_filename = "sync.log" if is_sync else "process.log"
            job = {"job_id": job_id, "job_type": "sync" if is_sync else "cut", "state": "prepared", "context": context,
                   "source_path": str(folder / "source.xml"),
                   "output_path": str(folder / out_filename),
                   "result_name": result_name,
                   "log_path": str(folder / log_filename)}
            self.jobs[job_id] = job
            self._save(job)
            return dict(job)
        if kind == "submit_transcribe":
            media = _input_file(req.get("media_path"))
            job_id, folder = self._allocate()
            job = {"job_id": job_id, "job_type": "transcribe", "kind": "transcribe",
                   "state": "running", "arguments": {"media_path": media},
                   "result_path": str(folder / "result.json"),
                   "log_path": str(folder / "process.log")}
            return self._launch(job, self._run_transcribe(job))
        if kind == "submit_rough_cut":
            arguments = _rough_cut_arguments(req)
            job_id, folder = self._allocate()
            job = {"job_id": job_id, "job_type": "cut", "kind": "rough_cut_xml",
                   "state": "running", "arguments": arguments,
                   "context": {"asr": arguments["speech_protection"]},
                   "preset": arguments["preset"],
                   "source_path": arguments["sequence_xml"],
                   "output_path": str(folder / "rough_cut.xml"),
                   "result_name": f"{Path(arguments['sequence_xml']).stem} — CutDeck {job_id[:8]}",
                   "xml_audio_track": arguments["audio_track"],
                   "log_path": str(folder / "process.log")}
            if arguments["start_frame"] is not None:
                job["range_frames"] = [arguments["start_frame"], arguments["end_frame"]]
            return self._launch(job, self._run(job))
        job = self.jobs.get(req.get("job_id"))
        if job is None:
            raise ValueError("Unknown job; start a new operation")
        if kind == "status":
            return dict(job)
        if kind == "start" or kind == "start_sync":
            if job["state"] != "prepared":
                return dict(job)  # duplicate request must never run a second time
            if self.active:
                raise ValueError("CutDeck is already processing a sequence")
            source = Path(job["source_path"])
            source_xml = source.read_text(encoding="utf-8-sig")
            try:
                return self._start(job, source_xml)
            except (ValueError, XmlRecutRefusal, ET.ParseError) as exc:
                # A refusal is final for this export: fail the job so the panel shows
                # why and clears it, instead of offering to resume a start that can't run.
                job["state"] = "failed"
                job["message"] = f"Cannot start: {exc}"
                self._save(job)
                return dict(job)
        raise ValueError("Unknown request type")

    def _start(self, job: dict, source_xml: str) -> dict:
        if job.get("job_type") == "sync":
            job["xml_audio_track"] = reference_audio_track(source_xml, job["context"]) if job["context"].get("audio_track") is not None else 0
            job["output_path"] = str(result_path(job, source_xml))
            job["state"] = "running"
            return self._launch(job, self._run_sync(job))
        start, end = range_from_ticks(source_xml, job["context"])
        job["xml_audio_track"] = reference_audio_track(source_xml, job["context"])
        # Only now does the export exist, so only now is the footage location known.
        job["output_path"] = str(result_path(job, source_xml))
        job["range_frames"] = [start, end]
        job["state"] = "running"
        return self._launch(job, self._run(job))

    def _allocate(self) -> tuple[str, Path]:
        """Claim the one GPU slot's next job folder, or refuse if the helper is busy."""
        if self.active:
            raise ValueError("CutDeck is already processing a sequence")
        if len(self.jobs) >= 1000:
            raise ValueError("Restart the helper before creating more jobs")
        job_id = uuid.uuid4().hex
        folder = self.directory / job_id
        folder.mkdir()
        return job_id, folder

    def _launch(self, job: dict, coroutine) -> dict:
        self.jobs[job["job_id"]] = job
        self.active = job["job_id"]
        self._save(job)
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return dict(job)

    def _save(self, job):
        (self.directory / job["job_id"] / "job.json").write_text(
            json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    async def _run(self, job):
        process = None
        try:
            folder = self.directory / job["job_id"]
            report_path = folder / "report.json"
            job["progress"] = {"pct": 2, "stage": "Checking source media"}
            source_xml = Path(job["source_path"]).read_text(encoding="utf-8-sig")
            try:
                checked = await asyncio.to_thread(
                    check_reference_audio, source_xml, job["xml_audio_track"])
            except XmlRecutRefusal as exc:
                raise RuntimeError(f"Cannot analyze this sequence: {exc}") from None
            job["reference"] = reference_label(source_xml, checked)
            args =[sys.executable, "-u", "-m", "cutdeck.xml_recut", job["source_path"],
                    "--out", job["output_path"], "--report", str(report_path),
                    "--config", str(ROOT / "transcribe/config.yaml"), "--no-save-plan"]
            if job.get("preset", "aggressive") == "aggressive":
                args += ["--overlay", str(ROOT / "transcribe/config.aggressive_cut.yaml")]
            if "range_frames" in job:
                start, end = job["range_frames"]
                args += ["--range-start-frame", str(start), "--range-end-frame", str(end)]
            if job["context"]["asr"]:
                args.append("--asr")
            if job["xml_audio_track"] is not None:
                args += ["--audio-track", str(job["xml_audio_track"])]
            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            with open(job["log_path"], "wb") as log:
                process = await asyncio.create_subprocess_exec(
                    *args, cwd=ROOT, env=env, stdout=asyncio.subprocess.PIPE,
                    stderr=subprocess.STDOUT, limit=1 << 20,
                    **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
                # Tee to the log so it stays the full record; progress lines also
                # update the job that `status` requests read while we run.
                async for raw_line in process.stdout:
                    log.write(raw_line)
                    log.flush()
                    progress = parse_progress(raw_line.decode("utf-8", errors="replace"))
                    if progress is not None:
                        job["progress"] = progress
                code = await process.wait()
            if code:
                detail = failure_detail(job["log_path"])
                raise RuntimeError(f"CutDeck processing failed (exit {code})"
                                   + (f": {detail}" if detail else "")
                                   + f". See {job['log_path']}")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            job["report"] = report
            job["state"] = "ready" if report["cuts_applied"] else "no_cuts"
            if job["state"] == "no_cuts":
                # A no-cut result just copies the source; don't leave it sitting in
                # the editor's media folder. The job folder's own copy is kept.
                output = Path(job["output_path"])
                if output.parent != folder:
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
            if process and process.returncode is None:
                # e.g. unreadable output: never report idle while the child still holds the GPU.
                process.terminate()
                await process.wait()
            job["state"] = "failed"
            job["message"] = str(exc)
        finally:
            self.active = None
            self._save(job)

    async def _run_transcribe(self, job):
        """Whole-file ASR in the existing worker subprocess; its result.json is the record."""
        process = None
        folder = self.directory / job["job_id"]
        try:
            with open(job["log_path"], "wb") as log:
                process = await asyncio.create_subprocess_exec(
                    sys.executable, "-u", "-m", "cutdeck.ai_worker", str(folder),
                    cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                    stdout=log, stderr=subprocess.STDOUT,
                    **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
                code = await process.wait()
            if code:
                raise RuntimeError(f"Transcription failed (exit {code}). See {job['log_path']}")
            json.loads(Path(job["result_path"]).read_text(encoding="utf-8"))
            job["state"] = "ready"
        except asyncio.CancelledError:
            if process and process.returncode is None:
                process.terminate()
                await process.wait()
            job["state"] = "failed"
            job["message"] = "Helper stopped during processing; start a new transcription"
            raise
        except Exception as exc:
            if process and process.returncode is None:
                process.terminate()
                await process.wait()
            job["state"] = "failed"
            job["message"] = str(exc)
        finally:
            self.active = None
            self._save(job)

    async def _run_sync(self, job):
        try:
            source = Path(job["source_path"])
            source_xml = source.read_text(encoding="utf-8-sig")
            ref_track = job.get("xml_audio_track") or 0

            from cutdeck.xml_sync import sync_sequence_xml
            synced_xml, report = await asyncio.to_thread(
                sync_sequence_xml,
                source_xml,
                ref_track_idx=ref_track,
            )

            out_path = Path(job["output_path"])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + synced_xml,
                encoding="utf-8",
            )

            job["report"] = {
                "sequence_name": report.sequence_name,
                "total_groups": report.total_groups,
                "synced_groups": report.synced_groups,
                "unsynced_groups": report.unsynced_groups,
                "unsynced_reasons": report.unsynced_reasons,
            }
            job["state"] = "ready"
        except asyncio.CancelledError:
            job["state"] = "failed"
            job["message"] = "Helper stopped during sync; start a new sync"
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
