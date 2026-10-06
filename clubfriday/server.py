"""Separate ClubFriday window; reuse the running CutDeck helper for Thai ASR.

Run: python -m clubfriday.server --port 8010
Audio comes from Premiere's marked reference track, without rendering its effects.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import json
from pathlib import Path
import re
import uuid
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from cutdeck.ai_backend import Backend, write_json
from cutdeck.sequence_model import from_panel_json, check_reference_audio
from cutdeck.xml_audio_extract import extract_mixdown
from cutdeck.xml_bridge import range_from_ticks
from cutdeck.xml_sequence import PPRO_TICKS_PER_SECOND

HERE = Path(__file__).parent


def quotes_srt(quotes: list[dict]) -> str:
    if not quotes:
        raise ValueError("Select at least one quote before exporting")

    def stamp(ms):
        hours, rest = divmod(ms, 3600000)
        minutes, rest = divmod(rest, 60000)
        seconds, millis = divmod(rest, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    blocks, previous_end = [], 0
    for index, quote in enumerate(sorted(quotes, key=lambda q: q["start_ms"]), 1):
        start, end = quote["start_ms"], quote["end_ms"]
        if start < previous_end or end <= start:
            raise ValueError("Quotes overlap or have invalid timing; remove duplicate or overlapping selections")
        lines = quote["lines"]
        if not 1 <= len(lines) <= 3 or any(not line.strip() or "\n" in line or "\r" in line for line in lines):
            raise ValueError("Use one to three non-empty lines for each exported quote")
        blocks.append(f"{index}\n{stamp(start)} --> {stamp(end)}\n" + "\n".join(lines))
        previous_end = end
    return "\n\n".join(blocks) + "\n\n"


def extract_range(snapshot: dict, path: str, audio_track: int | None) -> dict:
    sequence = from_panel_json(snapshot["sequence"])
    start, end = range_from_ticks(sequence, snapshot["context"])
    track = sequence.reference_track(audio_track)
    lo, hi = start * sequence.ticks_per_frame, end * sequence.ticks_per_frame
    for clip in snapshot["sequence"]["audio_tracks"][track.index]["clips"]:
        speed = clip.get("speed", 1)
        if speed != 1 and clip["enabled"]:
            clip_start = int(clip["start_ticks"])
            span = int(clip["out_ticks"]) - int(clip["in_ticks"])
            if clip_start < hi and (speed <= 0 or clip_start + span / speed > lo):
                raise ValueError("This range contains a speed-adjusted audio clip; use a normal-speed master track")
    # Offline material outside the marked range does not prevent this transcription.
    clips = tuple(c for c in track.clips if c.enabled and c.start_ticks < hi and c.end_ticks > lo)
    if not clips:
        raise ValueError(f"No enabled audio clips inside the range on A{track.index + 1}")
    tracks = tuple(replace(t, clips=clips) if t.index == track.index else t for t in sequence.tracks)
    sequence = replace(sequence, tracks=tracks)
    check_reference_audio(sequence, track.index)
    extract_mixdown(sequence, path, track.index, start, end, pad_seconds=0)
    return {"audio_track": track.index,
            "offset_ms": round(lo * 1000 / PPRO_TICKS_PER_SECOND)}


class StartRequest(BaseModel):
    audio_track: int | None = Field(default=None, ge=0, le=127)


class Quote(BaseModel):
    cue_indices: list[int] = Field(min_length=1)
    lines: list[str] = Field(min_length=1, max_length=3)


class QuoteRequest(BaseModel):
    quotes: list[Quote] = Field(max_length=500)


def create_app(directory: Path | None = None, backend=None, extractor=extract_range) -> FastAPI:
    directory = Path(directory or HERE.parent / "output" / "clubfriday")
    directory.mkdir(parents=True, exist_ok=True)
    backend = backend or Backend()
    tasks: set[asyncio.Task] = set()
    lock = asyncio.Lock()

    def folder(session_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", session_id):
            raise HTTPException(404, "Unknown ClubFriday session")
        return directory / session_id

    def load(session_id: str) -> dict:
        try:
            return json.loads((folder(session_id) / "session.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise HTTPException(404, "Unknown ClubFriday session")

    def save(session: dict):
        write_json(folder(session["id"]) / "session.json", session)

    async def export_path(session: dict, kind: str) -> Path:
        context = session["context"]
        project_path = context.get("project_path")
        if not project_path:
            active = await backend.premiere("read_sequence")
            if active.get("project_id") != context.get("project_id"):
                raise HTTPException(400, "Open the Premiere project that owns this saved range before exporting")
            project_path = active.get("project_path")
        if project_path and project_path.startswith("\\\\?\\"):
            project_path = project_path[4:]
            if project_path.startswith("UNC\\"):
                project_path = "\\\\" + project_path[4:]
        if not project_path or not Path(project_path).is_file():
            raise HTTPException(400, "Save the Premiere project, then reload the updated CutDeck panel before exporting")
        context["project_path"] = project_path
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", session["sequence_name"]).strip(" .")[:80] or "sequence"
        destination = Path(project_path).parent / "CutDeck" / "ClubFriday"
        destination.mkdir(parents=True, exist_ok=True)
        return destination / f"{name}-{session['id'][:8]}-{kind}.srt"

    async def process(session: dict, snapshot: dict, track: int | None):
        try:
            path = str(folder(session["id"]) / "range.wav")
            extracted = await asyncio.to_thread(extractor, snapshot, path, track)
            session.update(extracted)
            session["state"] = "transcribing"
            job = await backend.transcribe(path)
            session["helper_job_id"] = job["job_id"]
        except Exception as exc:
            session.update(state="failed", error=str(exc))
        finally:
            save(session)

    @asynccontextmanager
    async def lifespan(app):
        # A stopped extraction cannot silently appear to be running forever.
        for path in directory.glob("*/session.json"):
            session = json.loads(path.read_text(encoding="utf-8"))
            if session["state"] in ("extracting", "transcribing") and not session.get("helper_job_id"):
                session.update(state="failed", error="ClubFriday stopped before submitting audio; start a new range.")
                save(session)
        yield
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="ClubFriday", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        if request.method not in ("GET", "HEAD"):
            origin = request.headers.get("origin")
            expected = str(request.base_url).rstrip("/")
            if origin and origin != expected:
                return JSONResponse({"detail": "Open ClubFriday on its local address"}, status_code=403)
        return await call_next(request)

    @app.get("/")
    def home():
        return FileResponse(HERE / "static" / "index.html")

    @app.get("/api/premiere")
    async def premiere():
        try:
            status = await backend.premiere_status()
            if status["connected"]:
                status["sequence"] = await backend.premiere("read_sequence")
            return status
        except (RuntimeError, ValueError) as exc:
            return {"connected": False, "error": str(exc)}

    @app.get("/api/sessions")
    def list_sessions():
        paths = sorted(directory.glob("*/session.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [{k: s.get(k) for k in ("id", "sequence_name", "state", "in_ms", "out_ms")}
                for s in (json.loads(p.read_text(encoding="utf-8")) for p in paths)]

    @app.post("/api/sessions")
    async def start(req: StartRequest):
        async with lock:
            if tasks:
                raise HTTPException(409, "ClubFriday is already preparing audio")
            try:
                status = await backend.premiere_status()
                if not status["connected"]:
                    raise ValueError("Open the CutDeck panel in Premiere to connect the helper")
                if "read_audio_range" not in status["commands"]:
                    raise ValueError("Reload the updated CutDeck panel and restart its helper to enable range reading")
                snapshot = await backend.premiere("read_audio_range")
                sequence = from_panel_json(snapshot["sequence"])
                start_frame, end_frame = range_from_ticks(sequence, snapshot["context"])
                if req.audio_track is not None and req.audio_track >= len(sequence.tracks):
                    raise ValueError("That audio track does not exist in this sequence")
            except (ValueError, RuntimeError) as exc:
                raise HTTPException(400, str(exc))
            session_id = uuid.uuid4().hex
            folder(session_id).mkdir()
            context = snapshot["context"]
            session = {"id": session_id, "state": "extracting", "sequence_name": context["sequence_name"],
                       "sequence_id": context["sequence_id"], "context": context,
                       "in_ms": round(start_frame * sequence.ticks_per_frame * 1000 / PPRO_TICKS_PER_SECOND),
                       "out_ms": round(end_frame * sequence.ticks_per_frame * 1000 / PPRO_TICKS_PER_SECOND),
                       "cues": [], "quotes": []}
            write_json(folder(session_id) / "snapshot.json", snapshot)
            save(session)
            task = asyncio.create_task(process(session, snapshot, req.audio_track))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            return session

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
        async with lock:
            session = load(session_id)
            if session["state"] == "transcribing" and session.get("helper_job_id"):
                try:
                    result = await backend.result(session["helper_job_id"], limit=500)
                    if result["state"] == "succeeded":
                        cues = list(result["cues"])
                        while result.get("next_offset") is not None:
                            result = await backend.result(session["helper_job_id"], result["next_offset"], 500)
                            cues.extend(result["cues"])
                        offset = session["offset_ms"]
                        session["cues"] = [{"text": c["text"], "start_ms": round(c["start_ms"] + offset),
                                            "end_ms": round(c["end_ms"] + offset)} for c in cues]
                        session["state"] = "ready"
                    elif result["state"] in ("failed", "interrupted"):
                        session.update(state="failed", error=result.get("error", "Transcription failed"))
                    save(session)
                except (RuntimeError, ValueError) as exc:
                    # A disconnected helper can reconnect; do not destroy the saved job.
                    session["connection_error"] = str(exc)
            return session

    @app.get("/api/sessions/{session_id}/audio")
    def audio(session_id: str):
        load(session_id)
        path = folder(session_id) / "range.wav"
        if not path.is_file():
            raise HTTPException(404, "Range audio is not ready")
        return FileResponse(path, media_type="audio/wav")

    @app.put("/api/sessions/{session_id}/quotes")
    async def quotes(session_id: str, req: QuoteRequest):
        async with lock:
            session = load(session_id)
            if session["state"] != "ready":
                raise HTTPException(409, "Wait for transcription before selecting quotes")
            out = []
            for quote in req.quotes:
                indices = sorted(set(quote.cue_indices))
                if any(i < 0 or i >= len(session["cues"]) for i in indices):
                    raise HTTPException(400, "Quote refers to an unknown transcript cue")
                if indices != list(range(indices[0], indices[-1] + 1)):
                    raise HTTPException(400, "Choose consecutive cues for a quote")
                if not any(line.strip() for line in quote.lines):
                    raise HTTPException(400, "Quote text cannot be empty")
                out.append({"cue_indices": indices, "lines": quote.lines,
                            "start_ms": session["cues"][indices[0]]["start_ms"],
                            "end_ms": session["cues"][indices[-1]]["end_ms"]})
            session["quotes"] = out
            save(session)
            return session

    @app.get("/api/sessions/{session_id}/quotes.srt")
    async def export_srt(session_id: str):
        async with lock:
            session = load(session_id)
            if session["state"] != "ready":
                raise HTTPException(409, "Wait for transcription before exporting")
            try:
                contents = quotes_srt(session["quotes"])
            except ValueError as exc:
                raise HTTPException(400, str(exc))
            path = await export_path(session, "quotes")
            path.write_text(contents, encoding="utf-8-sig", newline="\r\n")
            save(session)
            return FileResponse(path, media_type="application/x-subrip",
                                filename=path.name, headers={"X-ClubFriday-Export-Path": quote(str(path))})

    @app.get("/api/sessions/{session_id}/transcript.srt")
    async def export_transcript(session_id: str):
        async with lock:
            session = load(session_id)
            if session["state"] != "ready":
                raise HTTPException(409, "Wait for transcription before exporting")
            try:
                contents = quotes_srt([{**cue, "lines": cue["text"].splitlines()}
                                      for cue in session["cues"]])
            except ValueError as exc:
                raise HTTPException(400, str(exc))
            path = await export_path(session, "transcript")
            path.write_text(contents, encoding="utf-8-sig", newline="\r\n")
            save(session)
            return FileResponse(path, media_type="application/x-subrip",
                                filename=path.name, headers={"X-ClubFriday-Export-Path": quote(str(path))})

    return app


def main():
    parser = argparse.ArgumentParser(description="ClubFriday transcript and quote window")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
