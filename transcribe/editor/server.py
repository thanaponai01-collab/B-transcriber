"""Phase 8 — Web editor backend (FastAPI).

Scope: correction-capture only. No accounts, no dashboard.
Endpoints:
  GET  /jobs                       → list jobs
  GET  /jobs/{job_id}              → job + tokens
  GET  /jobs/{job_id}/audio        → stream audio file
  POST /jobs/{job_id}/save         → accept corrected tokens, write correction rows
  GET  /jobs/{job_id}/export/srt   → download corrected SRT
  GET  /jobs/{job_id}/export/vtt   → download corrected VTT
"""

from __future__ import annotations

import io
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from transcribe.db import store
from transcribe.flywheel.diff import diff_corrections
from transcribe.pipeline.align_force import export_srt, export_vtt

_HERE = Path(__file__).parent
_DB_PATH = Path("transcriber.db")
_CONFIG_PATH = Path("config.yaml")

app = FastAPI(title="Transcriber Editor")
app.mount("/static", StaticFiles(directory=str(_HERE / "static"), html=True), name="static")


def _conn():
    return store.connect(_DB_PATH)


def _config() -> dict:
    if _CONFIG_PATH.exists():
        return yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")


@app.get("/jobs")
def list_jobs():
    conn = _conn()
    jobs = store.list_jobs(conn)
    conn.close()
    return [
        {
            "id": j.id,
            "media_id": j.media_id,
            "engine_a": j.engine_a,
            "engine_b": j.engine_b,
            "status": j.status,
            "created_at": j.created_at,
        }
        for j in jobs
    ]


@app.get("/jobs/{job_id}")
def get_job(job_id: int):
    conn = _conn()
    job = store.get_job(conn, job_id)
    if job is None:
        conn.close()
        raise HTTPException(404, "Job not found")
    tokens = store.get_tokens(conn, job_id)
    media = store.get_media(conn, job.media_id)
    conn.close()
    return {
        "job": {
            "id": job.id,
            "media_id": job.media_id,
            "engine_a": job.engine_a,
            "engine_b": job.engine_b,
            "status": job.status,
            "created_at": job.created_at,
        },
        "media_path": media.path if media else None,
        "tokens": [
            {
                "idx": t.idx,
                "text": t.text,
                "start_ms": t.start_ms,
                "end_ms": t.end_ms,
                "script": t.script,
                "confidence": t.confidence,
                "source_engine": t.source_engine,
            }
            for t in tokens
        ],
    }


@app.get("/jobs/{job_id}/audio")
def get_audio(job_id: int):
    conn = _conn()
    job = store.get_job(conn, job_id)
    if job is None:
        conn.close()
        raise HTTPException(404, "Job not found")
    media = store.get_media(conn, job.media_id)
    conn.close()
    if media is None or not Path(media.path).exists():
        raise HTTPException(404, "Audio file not found")
    return FileResponse(media.path, media_type="audio/mpeg")


class TokenPatch(BaseModel):
    idx: int
    text: str
    # GAP-7: optional one-tap reason tag. Never required — must not block a save.
    reason: str | None = None


class SaveRequest(BaseModel):
    tokens: list[TokenPatch]


@app.post("/jobs/{job_id}/save")
def save_corrections(job_id: int, req: SaveRequest):
    conn = _conn()
    job = store.get_job(conn, job_id)
    if job is None:
        conn.close()
        raise HTTPException(404, "Job not found")

    original_tokens = [
        {"idx": t.idx, "text": t.text, "source_engine": t.source_engine}
        for t in store.get_tokens(conn, job_id)
    ]
    pairs = diff_corrections(
        original_tokens,
        [{"idx": t.idx, "text": t.text, "reason": t.reason} for t in req.tokens],
    )

    for pair in pairs:
        store.create_correction(
            conn,
            job_id=job_id,
            token_idx=pair.token_idx,
            raw_text=pair.raw_text,
            corrected_text=pair.corrected_text,
            source_engine=pair.source_engine,
            reason=pair.reason,
            corrected_span=pair.corrected_span,
        )

    conn.close()
    return {"saved": len(pairs)}


@app.get("/jobs/{job_id}/export/srt")
def export_srt_endpoint(job_id: int):
    conn = _conn()
    tokens = store.get_tokens(conn, job_id)
    corrections = {c.token_idx: c.corrected_text for c in store.get_corrections(conn, job_id)}
    conn.close()

    token_dicts = []
    for t in tokens:
        text = corrections.get(t.idx, t.text)
        token_dicts.append({"text": text, "start_ms": t.start_ms, "end_ms": t.end_ms})

    buf = io.StringIO()
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".srt", delete=False, mode="w", encoding="utf-8") as f:
        tmp = f.name
    export_srt(token_dicts, tmp)
    content = Path(tmp).read_text(encoding="utf-8")
    os.unlink(tmp)
    return PlainTextResponse(content, media_type="text/plain; charset=utf-8",
                             headers={"Content-Disposition": f"attachment; filename=job{job_id}.srt"})


@app.get("/jobs/{job_id}/export/vtt")
def export_vtt_endpoint(job_id: int):
    conn = _conn()
    tokens = store.get_tokens(conn, job_id)
    corrections = {c.token_idx: c.corrected_text for c in store.get_corrections(conn, job_id)}
    conn.close()

    token_dicts = []
    for t in tokens:
        text = corrections.get(t.idx, t.text)
        token_dicts.append({"text": text, "start_ms": t.start_ms, "end_ms": t.end_ms})

    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".vtt", delete=False, mode="w", encoding="utf-8") as f:
        tmp = f.name
    export_vtt(token_dicts, tmp)
    content = Path(tmp).read_text(encoding="utf-8")
    os.unlink(tmp)
    return PlainTextResponse(content, media_type="text/vtt; charset=utf-8",
                             headers={"Content-Disposition": f"attachment; filename=job{job_id}.vtt"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
