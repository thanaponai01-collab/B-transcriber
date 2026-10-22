"""ClubFriday backend: quote SRT rules and the session flow, with a fake helper and extractor."""
import time
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

import clubfriday.server as server
from transcribe.timebase import Timebase

PAL = Timebase(25, 1)


def q(start, end, *lines):
    return {"start_ms": start, "end_ms": end, "lines": list(lines)}


def test_quotes_srt_orders_by_start_and_formats_stamps():
    out = server.quotes_srt([q(3_661_005, 3_662_000, "b"), q(0, 1500, "a1", "a2")], PAL)
    # snapped to 25 fps frames: 1500 ms is frame 37.5 -> 38 = 1520 ms
    assert out == ("1\n00:00:00,000 --> 00:00:01,520\na1\na2\n\n"
                   "2\n01:01:01,000 --> 01:01:02,000\nb\n\n")


@pytest.mark.parametrize("quotes", [
    [],
    [q(0, 1000, "a"), q(999, 2000, "b")],
    [q(1000, 1000, "a")],
    [q(0, 1000, "a", "b", "c", "d")],
    [q(0, 1000, "  ")],
    [q(0, 1000, "two\nlines")],
])
def test_quotes_srt_rejects_bad_input(quotes):
    with pytest.raises(ValueError):
        server.quotes_srt(quotes, PAL)


CUES = [{"text": "หนึ่ง", "start_ms": 0, "end_ms": 1000},
        {"text": "สอง", "start_ms": 1000, "end_ms": 2000},
        {"text": "สาม", "start_ms": 2500, "end_ms": 3000}]


class FakeBackend:
    def __init__(self, project_path):
        self.context = {"sequence_name": "Ep 1", "sequence_id": "s1", "project_id": "p1",
                        "project_path": str(project_path)}

    async def premiere_status(self):
        return {"connected": True, "commands": ["read_audio_range"]}

    async def premiere(self, command, args=None):
        if command == "read_sequence":
            return {"name": "Ep 1", "project_id": "p1"}
        assert command == "read_audio_range"
        return {"sequence": {}, "context": self.context}

    async def transcribe(self, media_path):
        return {"job_id": "job1"}

    async def result(self, job_id, offset=0, limit=100):
        assert job_id == "job1"
        return {"state": "succeeded", "cues": CUES, "next_offset": None}


def fake_extractor(snapshot, path, track):
    open(path, "wb").write(b"RIFF")
    return {"audio_track": 0, "offset_ms": 10_000}


@pytest.fixture
def client(tmp_path, monkeypatch):
    fake_sequence = SimpleNamespace(tracks=[object()], ticks_per_frame=254016000000 // 25, timebase=PAL)
    monkeypatch.setattr(server, "from_panel_json", lambda _: fake_sequence)
    monkeypatch.setattr(server, "range_from_ticks", lambda seq, ctx: (25, 75))
    project = tmp_path / "proj" / "p.prproj"
    project.parent.mkdir()
    project.write_text("x")
    app = server.create_app(tmp_path / "sessions", FakeBackend(project), fake_extractor)
    with TestClient(app) as c:
        yield c


def ready_session(client):
    session = client.post("/api/sessions", json={}).json()
    assert session["in_ms"] == 1000 and session["out_ms"] == 3000
    for _ in range(100):
        session = client.get(f"/api/sessions/{session['id']}").json()
        if session["state"] not in ("extracting", "transcribing"):
            return session
        time.sleep(0.05)
    raise AssertionError(f"never finished: {session['state']}")


def test_session_reaches_ready_with_cues_shifted_by_range_offset(client):
    session = ready_session(client)
    assert session["state"] == "ready"
    assert [(c["start_ms"], c["end_ms"]) for c in session["cues"]] == [
        (10_000, 11_000), (11_000, 12_000), (12_500, 13_000)]
    assert client.get(f"/api/sessions/{session['id']}/audio").content == b"RIFF"
    assert [s["id"] for s in client.get("/api/sessions").json()] == [session["id"]]


def test_quote_selection_rules(client):
    sid = ready_session(client)["id"]
    url = f"/api/sessions/{sid}/quotes"
    assert client.put(url, json={"quotes": [{"cue_indices": [0, 2], "lines": ["x"]}]}).status_code == 400
    assert client.put(url, json={"quotes": [{"cue_indices": [3], "lines": ["x"]}]}).status_code == 400
    assert client.put(url, json={"quotes": [{"cue_indices": [0], "lines": [" "]}]}).status_code == 400
    ok = client.put(url, json={"quotes": [{"cue_indices": [1, 0], "lines": ["x", "y"]}]})
    assert ok.status_code == 200
    assert ok.json()["quotes"][0]["start_ms"] == 10_000 and ok.json()["quotes"][0]["end_ms"] == 12_000


def test_exports_write_bom_crlf_srt_beside_the_project(client, tmp_path):
    sid = ready_session(client)["id"]
    client.put(f"/api/sessions/{sid}/quotes", json={"quotes": [{"cue_indices": [0], "lines": ["หนึ่ง"]}]})
    quotes = client.get(f"/api/sessions/{sid}/quotes.srt")
    assert quotes.status_code == 200
    saved = tmp_path / "proj" / "CutDeck" / "ClubFriday" / f"Ep 1-{sid[:8]}-quotes.srt"
    raw = saved.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw
    assert raw.decode("utf-8-sig") == "1\r\n00:00:10,000 --> 00:00:11,000\r\nหนึ่ง\r\n\r\n"
    full = client.get(f"/api/sessions/{sid}/transcript.srt")
    assert full.status_code == 200
    text = (saved.parent / f"Ep 1-{sid[:8]}-transcript.srt").read_bytes().decode("utf-8-sig")
    assert text.count("-->") == 3


def test_exports_snap_to_the_sequence_frame_rate(client, monkeypatch):
    sid = ready_session(client)["id"]
    ntsc = SimpleNamespace(tracks=[object()], timebase=Timebase(30000, 1001))
    monkeypatch.setattr(server, "from_panel_json", lambda _: ntsc)
    path = unquote(client.get(f"/api/sessions/{sid}/transcript.srt").headers["X-ClubFriday-Export-Path"])
    text = open(path, encoding="utf-8-sig").read()
    # 10 000 ms is frame 299.7 at 29.97 -> frame 300 = 10 010 ms
    assert "00:00:10,010 --> 00:00:11,011" in text


def test_exports_wait_for_ready_and_quotes(client):
    sid = ready_session(client)["id"]
    assert client.get(f"/api/sessions/{sid}/quotes.srt").status_code == 400  # no quotes chosen yet
    assert client.get("/api/sessions/" + "0" * 32 + "/quotes.srt").status_code == 404
    assert client.get("/api/sessions/not-an-id").status_code == 404


def test_post_from_another_origin_is_refused(client):
    r = client.post("/api/sessions", json={}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_home_serves_the_editor_page_and_premiere_reports_status(client):
    home = client.get("/")
    assert home.status_code == 200 and "text/html" in home.headers["content-type"]
    assert 'id="start"' in home.text
    status = client.get("/api/premiere").json()
    assert status["connected"] is True and status["commands"] == ["read_audio_range"]
    assert status["sequence"]["name"] == "Ep 1"


def test_split_quote_edit_keeps_cue_shares():
    assert server.split_quote_edit(["หนึ่ง", "สอง"], ["หนึ่ง สอง"]) == ["หนึ่ง", "สอง"]
    assert server.split_quote_edit(["หนึ่ง", "สอง"], ["หนึ่ง ส", "าม"]) == ["หนึ่ง", "สาม"]
    assert server.split_quote_edit(["ChatGBT ดี", "มาก"], ["ChatGPT ดี", " มาก"]) == ["ChatGPT ดี", "มาก"]


def test_quote_edit_becomes_correction_in_shared_store(tmp_path, monkeypatch):
    from transcribe.db import store
    db = tmp_path / "shared.db"
    store.init_db(db)
    conn = store.connect(db)
    (tmp_path / "range.wav").write_bytes(b"RIFF")
    media_id = store.create_media(conn, str(tmp_path / "range.wav"))
    job_id = store.create_job(conn, media_id, engine_a="faster_whisper", engine_b="passthrough",
                              pipeline_version="test")
    store.bulk_create_tokens(conn, [
        {"job_id": job_id, "idx": i, "text": c["text"], "start_ms": c["start_ms"], "end_ms": c["end_ms"],
         "script": "thai", "confidence": None, "source_engine": "a", "speaker_id": None}
        for i, c in enumerate(CUES)])
    conn.close()

    class StoreBackend(FakeBackend):
        async def result(self, job_id_, offset=0, limit=100):
            return {"state": "succeeded", "transcript_job_id": job_id, "next_offset": None,
                    "cues": [{**c, "idx": i} for i, c in enumerate(CUES)]}

    fake_sequence = SimpleNamespace(tracks=[object()], ticks_per_frame=254016000000 // 25, timebase=PAL)
    monkeypatch.setattr(server, "from_panel_json", lambda _: fake_sequence)
    monkeypatch.setattr(server, "range_from_ticks", lambda seq, ctx: (25, 75))
    project = tmp_path / "proj" / "p.prproj"
    project.parent.mkdir()
    project.write_text("x")
    app = server.create_app(tmp_path / "sessions", StoreBackend(project), fake_extractor, corrections_db=db)
    with TestClient(app) as c:
        sid = ready_session(c)["id"]
        url = f"/api/sessions/{sid}/quotes"
        assert c.put(url, json={"quotes": [{"cue_indices": [0, 1], "lines": ["หนึ่ง", " สี่"]}]}).status_code == 200
        conn = store.connect(db)
        rows = store.get_corrections(conn, job_id)
        assert [(r.token_idx, r.raw_text, r.corrected_text) for r in rows] == [(1, "สอง", "สี่")]
        # Editing the wording back to the transcript removes the correction.
        c.put(url, json={"quotes": [{"cue_indices": [0, 1], "lines": ["หนึ่ง สอง"]}]})
        assert store.get_corrections(conn, job_id) == []
        conn.close()
