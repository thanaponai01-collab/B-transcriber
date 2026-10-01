"""Web editor endpoints: unknown jobs and bad input must be refused, not
answered with an empty export or a 500."""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from transcribe.db import store
from transcribe.editor import server


@pytest.fixture
def client(monkeypatch):
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    db = Path(f.name)
    store.init_db(db)
    monkeypatch.setattr(server, "_DB_PATH", db)
    conn = store.connect(db)
    a = Path(f.name).with_suffix(".wav")
    a.write_bytes(b"x")
    media_id = store.create_media(conn, str(a))
    job_id = store.create_job(conn, media_id, "mock", "passthrough", "v")
    store.bulk_create_tokens(conn, [{
        "job_id": job_id, "idx": 0, "text": "hello", "start_ms": 0, "end_ms": 1000,
        "script": "latin", "confidence": 1.0, "source_engine": "a", "speaker_id": None,
    }])
    conn.close()
    c = TestClient(server.app, raise_server_exceptions=False)
    c.job_id = job_id
    return c


@pytest.mark.parametrize("fmt", ["srt", "vtt"])
def test_export_unknown_job_is_404(client, fmt):
    assert client.get(f"/jobs/999999/export/{fmt}").status_code == 404


@pytest.mark.parametrize("fps", ["-5", "0", "nan", "inf"])
def test_export_bad_fps_is_422(client, fps):
    assert client.get(f"/jobs/{client.job_id}/export/srt?fps={fps}").status_code == 422


def test_export_valid_job_still_works(client):
    r = client.get(f"/jobs/{client.job_id}/export/srt?fps=25")
    assert r.status_code == 200 and "hello" in r.text


def test_empty_correction_does_not_export_a_blank_cue(client):
    client.post(f"/jobs/{client.job_id}/save", json={"tokens": [{"idx": 0, "text": ""}]})
    r = client.get(f"/jobs/{client.job_id}/export/srt")
    assert r.status_code == 200 and "-->" not in r.text
