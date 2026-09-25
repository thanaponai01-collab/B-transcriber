"""Local job service for CutDeck's processing tools: the one job owner, and the hub between
its clients and Premiere (docs/arch-design-helper-v2.md).

The UXP panel and the MCP server (`cutdeck.ai_backend`) are both clients of this
socket, so there is one job_id space. GPU jobs (rough cut, transcribe) run one at a time;
Sync matching runs in its own CPU lane beside them.
Jobs survive panel disconnection and a helper restart (each job's job.json in output/premiere).
The client cannot choose commands. Panel jobs receive a unique job folder; the
MCP `submit_*` verbs take local input files but only ever write inside the job folder.

Protocol: a request may carry an `id`, echoed on its reply; requests on one connection are
answered as they finish, not in order. `watch` pushes {"event": "job"} updates for one job.
The panel registers as the Premiere driver; `premiere` requests from any client are forwarded
to it as {"call": ...} messages from a fixed command list, and its `driver_reply` answers them.
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

from cutdeck.driver_commands import COMMANDS, MAX_MARKERS  # noqa: F401 (MAX_MARKERS: tests)
from cutdeck import frame_bounds, sequence_json, text_properties
from cutdeck.xml_sequence import (PPRO_TICKS_PER_SECOND, XmlRecutRefusal, audio_track_groups,
                                  check_reference_audio, sequence_timebase)

ROOT = Path(__file__).resolve().parent.parent
PORT = 7891
VERSION = "cutdeck-xml-5"  # -2: plan_sync (native Sync); -3: panel rough cuts are native only; -4: frame_bounds
# -5: v2 protocol (ids, watch, Premiere driver) and Rough Cut input as JSON
MAX_MESSAGE = 1 << 24  # 16 MiB: the MCP client's limit too; a JSON sequence read can pass 64 KB
TERMINAL_STATES = frozenset({"ready", "no_cuts", "failed", "interrupted"})


_PROGRESS_LINE = re.compile(r"PROGRESS:(\d{1,3}):(.+)")


def parse_progress(line: str) -> dict | None:
    """Read a `PROGRESS:<pct>:<stage>` line written by xml_recut, else None."""
    match = _PROGRESS_LINE.fullmatch(line.strip())
    if match is None:
        return None
    return {"pct": min(int(match.group(1)), 100), "stage": match.group(2).strip()}


def reference_audio_track(source_xml: str, request: dict) -> int | None:
    """Map Premiere's logical track to FCP7's exploded channel tracks."""
    selected = request.get("audio_track")
    if selected is None:
        return None  # Preserve the working command's default exactly.
    groups = audio_track_groups(source_xml)
    if len(groups) != request.get("audio_track_count") or not 0 <= selected < len(groups):
        raise ValueError("Export audio tracks differ from the timeline; refresh and try again")
    return groups[selected]


def reference_label(source_xml: str, checked: dict) -> str:
    """What the status line says is being analyzed, in Premiere's own track names."""
    try:
        track = f"A{audio_track_groups(source_xml).index(checked['xml_track']) + 1}"
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


def range_from_ticks(source_xml: str, request: dict) -> tuple[int, int]:
    """Validate live sequence geometry against the export using exact integers."""
    sequence = ET.fromstring(source_xml).find("sequence")
    if sequence is None:
        raise ValueError("Export contains no sequence")
    tb = sequence_timebase(sequence)
    tick_num = PPRO_TICKS_PER_SECOND * tb.fps_den
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


def _plan_sync_clips(req: dict) -> list:
    """Validate a `plan_sync` request's clips; nothing runs on a bad one."""
    from cutdeck.sync_plan import ClipInput
    clips = req.get("clips")
    if not isinstance(clips, list) or not clips:
        raise ValueError("plan_sync needs a non-empty list of clips")
    result, seen = [], set()
    for clip in clips:
        if not isinstance(clip, dict):
            raise ValueError("Each clip must be an object")
        clip_id, duration = clip.get("id"), clip.get("duration_s")
        if not isinstance(clip_id, str) or not clip_id or clip_id in seen:
            raise ValueError("Each clip needs a unique, non-empty string id")
        if type(duration) not in (int, float) or not 0 < duration < 1e6:
            raise ValueError(f"Clip {clip_id}: duration_s must be a positive number of seconds")
        seen.add(clip_id)
        result.append(ClipInput(clip_id, Path(_input_file(clip.get("path"))), float(duration)))
    return result


def _load_audio(path, sample_rate, start_s, duration_s):
    """sync_plan's Loader argument order, over cutdeck.sync's keyword-only extractor."""
    from cutdeck.sync import extract_mono_audio
    return extract_mono_audio(path, start_s=start_s, duration_s=duration_s, sample_rate=sample_rate)


def plan_to_json(plan) -> dict:
    return {"placements": [{"id": p.clip_id, "status": p.status, "start_s": p.start_s,
                            "session": p.session, "matched_to": p.matched_to,
                            "confidence": p.confidence, "drift_ms": p.drift_ms, "reason": p.reason,
                            "media_duration_s": plan.media_duration_s.get(p.clip_id)}
                           for p in plan.placements],
            "sessions": plan.sessions, "duration_s": plan.duration_s}


class Client:
    """One socket connection. Pushes (job events, driver calls) are sent from their own tasks,
    so a slow client never holds up the job that produced them."""

    def __init__(self, socket):
        self.socket = socket
        self._sends: set[asyncio.Task] = set()

    def push(self, message: dict):
        task = asyncio.ensure_future(self._send(message))
        self._sends.add(task)
        task.add_done_callback(self._sends.discard)

    async def _send(self, message: dict):
        try:
            await self.socket.send(json.dumps(message, ensure_ascii=False))
        except Exception:
            pass  # a closed connection: its watchers and calls are dropped on disconnect


class VersionMismatch(ValueError):
    """`hello` from a panel of another version. The reply still says what this helper is, so the
    panel can tell "outdated helper running" (restart it) from "no helper" (launch one)."""

    def __init__(self):
        super().__init__("Panel/helper version mismatch")
        self.details = {"code": "version_mismatch", "version": VERSION, "pid": os.getpid()}


class XmlJobs:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, dict] = {}
        self.tasks: set[asyncio.Task] = set()
        self.active: str | None = None  # the GPU lane: rough cut, transcribe
        self.cpu_active: str | None = None  # the CPU lane: Sync matching
        self.restarting = False
        self.stop = asyncio.Event()  # set once a `restart` reply has been sent
        self.watchers: dict[str, set[Client]] = {}
        self.driver: Client | None = None
        self.driver_commands: list[str] = []
        self.calls: dict[str, tuple[Client, asyncio.Future]] = {}

    async def dispatch(self, req: dict, client: Client | None = None) -> dict:
        if not isinstance(req, dict):
            raise ValueError("Expected an object")
        kind = req.get("type")
        if kind == "hello":
            if req.get("version") != VERSION:
                raise VersionMismatch()
            return {"version": VERSION, "pid": os.getpid()}
        if kind == "restart":
            # The panel asks on every start so edited helper code is picked up. A running job's
            # child would be orphaned, so never while one runs.
            if self.active or self.cpu_active:
                raise ValueError("CutDeck is processing a job; it restarts once that finishes")
            self.restarting = True
            return {"restarting": True}
        if kind == "register_driver":
            if client is None:
                raise ValueError("Only a connected panel can be the Premiere driver")
            commands = req.get("commands")
            if not isinstance(commands, list) or not set(commands) <= set(COMMANDS):
                raise ValueError("Unknown driver commands")
            self.driver, self.driver_commands = client, list(commands)
            print(f"driver registered: {', '.join(commands)}", flush=True)
            return {"registered": True}
        if kind == "premiere_status":
            return {"connected": self.driver is not None, "commands": list(self.driver_commands)}
        if kind == "premiere":
            return {"result": await self._call_driver(req)}
        if kind == "watch":
            job = self._job(req.get("job_id"))
            if client is not None and job["state"] not in TERMINAL_STATES:
                self.watchers.setdefault(job["job_id"], set()).add(client)
            return dict(job)
        if kind == "prepare":
            # Everything is checked before a job folder is claimed: a refused prepare leaves nothing.
            context_keys = ("project_id", "sequence_id", "sequence_name", "audio_track", "audio_track_count",
                            "in_ticks", "out_ticks", "end_ticks", "ticks_per_frame", "asr")
            context = {key: req.get(key) for key in context_keys}
            if not all(isinstance(context[k], str) and context[k] for k in
                       ("project_id", "sequence_id", "sequence_name")):
                raise ValueError("Missing source project or sequence identity")
            track = context["audio_track"]
            if track is not None and (type(track) is not int or track < 0):
                raise ValueError("Audio track must be a non-negative index")
            if type(context["asr"]) is not bool:
                raise ValueError("Speech protection must be true or false")
            # The panel's native read of the audio tracks, instead of an XML export (move 6).
            sequence = sequence_json.validate(req.get("sequence"))
            job_id, folder = self._allocate()
            (folder / "source.xml").write_text(
                sequence_json.to_fcp7_xml(sequence, context["sequence_name"]), encoding="utf-8")
            job = {"job_id": job_id, "job_type": "cut", "state": "prepared", "context": context,
                   "source_path": str(folder / "source.xml"),
                   "result_name": f"{context['sequence_name']} — CutDeck {job_id[:8]}",
                   "log_path": str(folder / "process.log"),
                   # The panel cuts natively from this list; the XML output route is retired
                   # for the panel (HANDOFF_CUTDECK_NATIVE_ROUGH_CUT Phase 6).
                   "output": "native"}
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
        if kind == "plan_sync":
            clips = _plan_sync_clips(req)
            job_id, folder = self._allocate("cpu")
            job = {"job_id": job_id, "job_type": "plan_sync", "state": "running",
                   "clips": [{"id": c.id, "path": str(c.path), "duration_s": c.duration_s} for c in clips],
                   "progress": {"pct": 0, "stage": "Reading audio"}}
            return self._launch(job, self._run_plan_sync(job, clips), "cpu")
        if kind == "frame_bounds":
            # Transform panel: where a Graphic's text is drawn, from two saved frames. On a worker
            # thread, so other clients are answered while the PNGs are compared.
            return await asyncio.to_thread(frame_bounds.measure_request, req, _input_file)
        if kind == "measure_text":
            text = req.get("text", "")
            font = req.get("font_name", "")
            size = float(req.get("font_size", 100.0))
            scale_x = float(req.get("scale_x", 100.0))
            scale_y = float(req.get("scale_y", 100.0))
            bounds = text_properties.measure_text_bounds(text, font, size, scale_x, scale_y)
            return {"bounds": bounds}
        if kind == "text_properties":
            project_path = _input_file(req.get("project_path"), ".prproj")
            texts = await asyncio.to_thread(text_properties.extract_project_text_properties, project_path)
            return {"texts": texts}
        if kind == "submit_rough_cut":
            arguments = _rough_cut_arguments(req)
            job_id, folder = self._allocate()
            job = {"job_id": job_id, "job_type": "cut", "kind": "rough_cut", "output": "native",
                   "state": "running", "arguments": arguments,
                   "context": {"asr": arguments["speech_protection"]},
                   "preset": arguments["preset"],
                   "source_path": arguments["sequence_xml"],
                   "xml_audio_track": arguments["audio_track"],
                   "log_path": str(folder / "process.log")}
            if arguments["start_frame"] is not None:
                job["range_frames"] = [arguments["start_frame"], arguments["end_frame"]]
            return self._launch(job, self._run(job))
        job = self._job(req.get("job_id"))
        if kind == "status":
            return dict(job)
        if kind == "start":
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
        start, end = range_from_ticks(source_xml, job["context"])
        job["xml_audio_track"] = reference_audio_track(source_xml, job["context"])
        job["range_frames"] = [start, end]
        job["state"] = "running"
        return self._launch(job, self._run(job))

    def _job(self, job_id) -> dict:
        """A job from memory, or from its job.json when an earlier helper made it. A job that
        earlier helper was running died with it: it reads as `interrupted`, never as running."""
        job = self.jobs.get(job_id)
        if job is not None:
            return job
        path = (self.directory / job_id / "job.json"
                if isinstance(job_id, str) and re.fullmatch(r"[0-9a-f]{32}", job_id) else None)
        try:
            job = json.loads(path.read_text(encoding="utf-8")) if path else None
        except (OSError, ValueError):
            job = None
        if not isinstance(job, dict) or job.get("job_id") != job_id:
            raise ValueError("Unknown job; start a new operation")
        if job.get("state") == "running":
            job["state"] = "interrupted"
            job["message"] = "The CutDeck helper restarted while this job ran; start it again"
            self._save(job)
        self.jobs[job_id] = job
        return job

    def _allocate(self, lane: str = "gpu") -> tuple[str, Path]:
        """Claim a lane's next job folder, or refuse if that lane is busy."""
        if lane == "gpu" and self.active:
            raise ValueError("CutDeck is already processing a sequence")
        if lane == "cpu" and self.cpu_active:
            raise ValueError("CutDeck is already matching a sync")
        if len(self.jobs) >= 1000:
            raise ValueError("Restart the helper before creating more jobs")
        job_id = uuid.uuid4().hex
        folder = self.directory / job_id
        folder.mkdir()
        return job_id, folder

    def _launch(self, job: dict, coroutine, lane: str = "gpu") -> dict:
        self.jobs[job["job_id"]] = job
        if lane == "gpu":
            self.active = job["job_id"]
        else:
            self.cpu_active = job["job_id"]
        self._save(job)
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return dict(job)

    def _save(self, job):
        (self.directory / job["job_id"] / "job.json").write_text(
            json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    def _notify(self, job):
        """Push the job's current state to every connection watching it."""
        done = job["state"] in TERMINAL_STATES
        watchers = self.watchers.pop(job["job_id"], set()) if done else self.watchers.get(job["job_id"], set())
        for client in watchers:
            client.push({"event": "job", "job": dict(job)})

    async def _call_driver(self, req: dict):
        """Forward one fixed command to the panel and wait for its answer."""
        command, args = req.get("command"), req.get("args") or {}
        if command not in COMMANDS or not isinstance(args, dict):
            raise ValueError(f"Unknown Premiere command; one of: {', '.join(COMMANDS)}")
        driver = self.driver
        if driver is None:
            raise ValueError("No CutDeck panel is connected: open the CutDeck panel in Premiere")
        if command not in self.driver_commands:
            raise ValueError(f"The connected panel does not offer {command}; update the panel")
        args = COMMANDS[command].prepare(args, self._job)
        call_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.calls[call_id] = (driver, future)
        driver.push({"call": call_id, "command": command, "args": args})
        try:
            return await asyncio.wait_for(future, COMMANDS[command].timeout_s)
        except asyncio.TimeoutError:
            raise ValueError(f"The CutDeck panel did not finish {command} in time") from None
        finally:
            self.calls.pop(call_id, None)

    def driver_reply(self, req: dict):
        entry = self.calls.get(req.get("call"))
        if entry is None or entry[1].done():
            return  # timed out, or not a call we made
        if req.get("ok"):
            entry[1].set_result(req.get("result"))
        else:
            entry[1].set_exception(ValueError(str(req.get("message") or "The CutDeck panel refused")))

    def disconnect(self, client: Client):
        for watchers in self.watchers.values():
            watchers.discard(client)
        if self.driver is client:
            self.driver, self.driver_commands = None, []
            print("driver disconnected", flush=True)
        for driver, future in list(self.calls.values()):
            if driver is client and not future.done():
                future.set_exception(ValueError("The CutDeck panel disconnected before it answered"))

    async def _run(self, job):
        process = None
        try:
            folder = self.directory / job["job_id"]
            job["progress"] = {"pct": 2, "stage": "Checking source media"}
            source_xml = Path(job["source_path"]).read_text(encoding="utf-8-sig")
            try:
                checked = await asyncio.to_thread(
                    check_reference_audio, source_xml, job["xml_audio_track"])
            except XmlRecutRefusal as exc:
                raise RuntimeError(f"Cannot analyze this sequence: {exc}") from None
            job["reference"] = reference_label(source_xml, checked)
            # Every job returns the native cut list; nothing writes XML any more
            # (HANDOFF_CUTDECK_NATIVE_ROUGH_CUT Phase 6).
            cuts_path = folder / "cuts.json"
            args = [sys.executable, "-u", "-m", "cutdeck.xml_recut", job["source_path"],
                    "--cuts-json", str(cuts_path),
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
                        self._notify(job)
                code = await process.wait()
            if code:
                detail = failure_detail(job["log_path"])
                raise RuntimeError(f"CutDeck processing failed (exit {code})"
                                   + (f": {detail}" if detail else "")
                                   + f". See {job['log_path']}")
            cuts = json.loads(cuts_path.read_text(encoding="utf-8"))
            job["cuts"] = cuts
            job["report"] = cuts["report"]
            job["state"] = "ready" if cuts["cuts_frames"] else "no_cuts"
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
            self._notify(job)

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
            self._notify(job)

    async def _run_plan_sync(self, job, clips):
        loop = asyncio.get_running_loop()

        def progress(done, total, stage):  # runs on the worker thread; one dict swap is atomic
            job["progress"] = {"pct": round(100 * done / total) if total else 0,
                               "stage": f"{stage} {done}/{total}"}
            loop.call_soon_threadsafe(self._notify, job)
        try:
            from cutdeck.sync_plan import plan_sync
            plan = await asyncio.to_thread(plan_sync, clips, _load_audio, progress)
            job["plan"] = plan_to_json(plan)
            job["state"] = "ready"
        except asyncio.CancelledError:
            job["state"] = "failed"
            job["message"] = "Helper stopped during sync; start a new sync"
            raise
        except Exception as exc:
            job["state"] = "failed"
            job["message"] = f"Sync matching failed: {exc}"
        finally:
            self.cpu_active = None
            self._save(job)
            self._notify(job)


async def serve(jobs: XmlJobs, port: int = PORT):
    from websockets.asyncio.server import serve as ws_serve

    async def answer(client: Client, raw):
        req_id = None
        try:
            req = json.loads(raw)
            if isinstance(req, dict):
                req_id = req.get("id")
                if req.get("type") == "driver_reply":
                    jobs.driver_reply(req)  # an answer to a call we sent; it gets no reply
                    return
            response = {"ok": True, **await jobs.dispatch(req, client)}
        except Exception as exc:
            response = {"ok": False, "message": str(exc), **getattr(exc, "details", {})}
        if req_id is not None:
            response["id"] = req_id
        try:
            await client.socket.send(json.dumps(response, ensure_ascii=False))
        except Exception:
            return  # the client went away; what it asked for still happened
        if jobs.restarting:
            jobs.stop.set()

    async def connection(socket):
        # Each message is answered in its own task: a long `premiere` call or `frame_bounds`
        # never holds up the `status` or `driver_reply` behind it on the same socket.
        client = Client(socket)
        answers: set[asyncio.Task] = set()
        try:
            async for raw in socket:
                task = asyncio.create_task(answer(client, raw))
                answers.add(task)
                task.add_done_callback(answers.discard)
        except Exception:
            pass  # a dropped connection ends like a closed one
        finally:
            jobs.disconnect(client)
            if answers:
                await asyncio.wait(answers)

    # Reject ordinary website origins; the local UXP client has no web origin.
    return await ws_serve(connection, "127.0.0.1", port,
                          origins=[None, "null", "file://"], max_size=MAX_MESSAGE)


def spawn_replacement(port: int, jobs_dir: Path):
    """Start a fresh helper, windowless, that outlives this one.

    CREATE_NO_WINDOW, not DETACHED_PROCESS: a detached helper has no console at all, so every
    console tool it runs (ffmpeg/ffprobe) gets a NEW visible window from Windows. With a hidden
    console of its own, its children inherit that instead and nothing pops up."""
    log = open(jobs_dir / "helper.log", "ab")
    extra = ({"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
             if os.name == "nt" else {"start_new_session": True})
    subprocess.Popen([sys.executable, "-m", "cutdeck.xml_bridge", "--port", str(port), "--jobs-dir", str(jobs_dir)],
                     cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **extra)


def _record_startup_failure(log: Path, message: str):
    """A helper launched by Start CutDeck (Hidden).vbs has an invisible console, so say why it
    stopped in helper.log, where the panel's start timeout points. A restarted helper's stderr
    already is helper.log (spawn_replacement), so its traceback is enough there."""
    try:
        if log.exists() and os.path.samestat(os.fstat(sys.stderr.fileno()), log.stat()):
            return
    except (OSError, ValueError, AttributeError):
        pass  # no usable stderr: write the line
    import datetime
    with open(log, "a", encoding="utf-8") as out:
        out.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="CutDeck Premiere XML helper")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--jobs-dir", type=Path, default=ROOT / "output/premiere")
    args = parser.parse_args()

    async def run():
        jobs = XmlJobs(args.jobs_dir)
        try:
            server = await serve(jobs, args.port)
        except OSError as exc:
            _record_startup_failure(jobs.directory / "helper.log",
                                    f"CutDeck could not listen on 127.0.0.1:{args.port}: {exc}. Another "
                                    "CutDeck helper (or another program) already holds the port.")
            raise
        print(f"CutDeck ready on ws://127.0.0.1:{args.port}", flush=True)
        async with server:
            await jobs.stop.wait()
            server.close()
            await server.wait_closed()  # free the port before the replacement binds it
        spawn_replacement(args.port, jobs.directory)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
