"""ClubFriday backend: quote SRT rules and the session flow, with a fake helper and extractor."""
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import clubfriday.server as server


def q(start, end, *lines):
    return {"start_ms": start, "end_ms": end, "lines": list(lines)}


def test_quotes_srt_orders_by_start_and_formats_stamps():
    out = server.quotes_srt([q(3_661_005, 3_662_000, "b"), q(0, 1500, "a1", "a2")])
    assert out == ("1\n00:00:00,000 --> 00:00:01,500\na1\na2\n\n"
                   "2\n01:01:01,005 --> 01:01:02,000\nb\n\n")


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
        server.quotes_srt(quotes)


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
    fake_sequence = SimpleNamespace(tracks=[object()], ticks_per_frame=254016000000 // 25)
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
