"""MCP-facing view of CutDeck's jobs; the jobs themselves live in the :7891 helper.

`cutdeck.xml_bridge` owns every job (one job_id space, one GPU lock). This module
only speaks to it over the same one-shot websocket exchange the UXP panel uses,
and keeps the two things MCP promises its agents: the published capabilities and
the job-state vocabulary, plus paged transcript results.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from cutdeck.xml_bridge import PORT, VERSION

ROOT = Path(__file__).resolve().parent.parent

# The helper's states, in MCP's published vocabulary. `interrupted` stays in the
# published list but the helper never emits it: it keeps jobs in memory, so a
# restarted helper answers "Unknown job" instead.
MCP_STATE = {"prepared": "queued", "running": "running", "ready": "succeeded",
             "no_cuts": "succeeded", "failed": "failed"}
_KIND = {"cut": "rough_cut", "transcribe": "transcribe"}


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class Backend:
    """A client of the running helper. Every call is one request/response exchange."""

    def __init__(self, port: int = PORT):
        self.port = port

    def capabilities(self) -> dict:
        return {
            "version": "2", "tools": ["transcribe", "rough_cut"],
            "live_premiere_control": False,
            "rough_cut_input": "Exported FCP7 sequence XML with accessible source media",
            "rough_cut_output": ("Cut list: [start_frame, end_frame) spans on the sequence frame "
                                 "grid plus ticks_per_frame; the CutDeck panel's Rough Cut applies "
                                 "these natively. No XML is written."),
            "transcript_timing": "Phrase cues in milliseconds relative to input media",
            "job_states": ["queued", "running", "succeeded", "failed", "interrupted"],
            "serial_processing": True,
        }

    async def _ask(self, request: dict) -> dict:
        from websockets.asyncio.client import connect
        try:
            async with connect(f"ws://127.0.0.1:{self.port}", max_size=1 << 24) as socket:
                for message in ({"type": "hello", "version": VERSION}, request):
                    await socket.send(json.dumps(message))
                    reply = json.loads(await socket.recv())
                    if not reply.get("ok"):
                        raise ValueError(reply.get("message", "Helper refused the request"))
        except OSError as exc:
            raise RuntimeError(
                f"CutDeck helper is not running on 127.0.0.1:{self.port}; "
                "start it with: python -m cutdeck.xml_bridge") from exc
        return reply

    @staticmethod
    def _view(job: dict) -> dict:
        view = {"job_id": job["job_id"], "kind": _KIND.get(job.get("job_type"), job.get("job_type")),
                "state": MCP_STATE[job["state"]], "log_path": job.get("log_path")}
        if job.get("arguments") is not None:
            view["arguments"] = job["arguments"]
        if job["state"] == "failed":
            view["error"] = job.get("message", "Processing failed")
        return view

    async def transcribe(self, media_path: str) -> dict:
        return self._view(await self._ask({"type": "submit_transcribe", "media_path": media_path}))

    async def rough_cut(self, sequence_xml: str, speech_protection: bool = True,
                        preset: str = "aggressive", audio_track: int | None = None,
                        start_frame: int | None = None, end_frame: int | None = None) -> dict:
        return self._view(await self._ask({
            "type": "submit_rough_cut", "sequence_xml": sequence_xml,
            "speech_protection": speech_protection, "preset": preset, "audio_track": audio_track,
            "start_frame": start_frame, "end_frame": end_frame}))

    async def status(self, job_id: str) -> dict:
        if not isinstance(job_id, str) or not re.fullmatch(r"[0-9a-f]{32}", job_id):
            raise ValueError("Unknown job_id")
        return self._view(await self._ask({"type": "status", "job_id": job_id}))

    async def result(self, job_id: str, offset: int = 0, limit: int = 100) -> dict:
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("offset must be >= 0; limit must be between 1 and 500")
        job = await self._ask({"type": "status", "job_id": job_id})
        view = self._view(job)
        if view["state"] != "succeeded":
            return view
        if job.get("job_type") == "transcribe":
            result = json.loads(Path(job["result_path"]).read_text(encoding="utf-8"))
            cues = result.pop("cues")
            result.update(cues=cues[offset:offset + limit], total_cues=len(cues), offset=offset,
                          next_offset=offset + limit if offset + limit < len(cues) else None)
        elif job.get("job_type") == "cut":
            cuts = job.get("cuts") or {"cuts_frames": [], "report": job.get("report")}
            result = {"kind": "rough_cut", "cuts_frames": cuts.get("cuts_frames", []),
                      "ticks_per_frame": cuts.get("ticks_per_frame"),
                      "sequence_duration_frames": cuts.get("sequence_duration_frames"),
                      "report": cuts.get("report")}
        else:
            return view
        return {"job_id": job_id, "state": "succeeded", **result}
