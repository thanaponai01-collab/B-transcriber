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

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from transcribe.db import store
from transcribe.flywheel.diff import diff_corrections
from transcribe.pipeline.align_force import export_srt, export_vtt

_HERE = Path(__file__).parent
_DB_PATH = Path("transcriber.db")

app = FastAPI(title="Transcriber Editor")
app.mount("/static", StaticFiles(directory=str(_HERE / "static"), html=True), name="static")


def _conn():
    return store.connect(_DB_PATH)


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
    # Merge saved corrections into the view: reopening a corrected job must show
    # the corrected text, not silently present the raw ASR output again.
    corrections = {c.token_idx: c.corrected_text for c in store.get_corrections(conn, job_id)}
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
                "text": corrections.get(t.idx, t.text),
                "raw_text": t.text,
                "corrected": t.idx in corrections,
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

    original = {t.idx: t for t in store.get_tokens(conn, job_id)}
    original_tokens = [
        {"idx": t.idx, "text": t.text, "source_engine": t.source_engine}
        for t in original.values()
    ]
    pairs = diff_corrections(
        original_tokens,
        [{"idx": t.idx, "text": t.text, "reason": t.reason} for t in req.tokens],
    )

    for pair in pairs:
        # create_correction replaces any prior row for this (job, token), so
        # repeated saves refine the correction instead of stacking duplicates.
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

    # A token sent back matching its raw text is a revert: drop any stale
    # correction so exports and the flywheel stop seeing the old edit.
    reverted = 0
    changed = {p.token_idx for p in pairs}
    existing = {c.token_idx for c in store.get_corrections(conn, job_id)}
    for t in req.tokens:
        orig = original.get(t.idx)
        if orig is not None and t.idx not in changed and t.idx in existing and t.text == orig.text:
            store.delete_correction(conn, job_id, t.idx)
            reverted += 1

    conn.close()
    return {"saved": len(pairs), "reverted": reverted}


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
