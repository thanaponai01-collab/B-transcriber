"""Issues #20/#21 acceptance — CutPlan from a live clip descriptor, exercised
entirely through cutdeck.bridge.handle_message (the primary test seam per
issue #17's testing decisions — plan_from_live_clip has no seam of its own).

Reuses the synthetic multi-silence WAV fixture pattern from
tests/test_cutdeck_sequence_mixdown.py rather than inventing new
silence-detection test data.
"""

import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from cutdeck.bridge import BRIDGE_VERSION, handle_message, serve  # noqa: E402
from cutdeck.contracts import CutConfig  # noqa: E402
from transcribe.pipeline import ingest as ingest_mod  # noqa: E402
from transcribe.timebase import frame_to_ms, ms_to_frame  # noqa: E402

SR = 16000
NTSC2997 = {"fps_num": 30000, "fps_den": 1001}
CFG = CutConfig()  # defaults: min_silence_ms=900, pad_pre_ms=250, pad_post_ms=120

# Hand-computed from _synthetic_multi_silence_wav's construction, same math
# tests/test_cutdeck_sequence_mixdown.py uses: cut_start = silence_start +
# pad_post_ms, cut_end = silence_end - pad_pre_ms.
CUT1 = (1500 + CFG.pad_post_ms, 3000 - CFG.pad_pre_ms)   # (1620, 2750)
CUT2 = (4000 + CFG.pad_post_ms, 5500 - CFG.pad_pre_ms)   # (4120, 5250)


def _synthetic_multi_silence_wav():
    """speech[0-1.5s] silence[1.5-3.0s] speech[3.0-4.0s] silence[4.0-5.5s] speech[5.5-6.5s]."""
    import soundfile as sf

    def loud(seconds):
        t = np.linspace(0, seconds, int(SR * seconds), endpoint=False)
        return (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)

    def quiet(seconds):
        return np.zeros(int(SR * seconds), dtype=np.float32)

    audio = np.concatenate([loud(1.5), quiet(1.5), loud(1.0), quiet(1.5), loud(1.0)])
    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    f.close()
    sf.write(f.name, audio, SR)
    return f.name


def _stub_multi_silence(tensor, model, **kwargs):
    bounds_s = [(0.0, 1.5), (3.0, 4.0), (5.5, 6.5)]
    return [{"start": int(s * SR), "end": int(e * SR)} for s, e in bounds_s]


def _stub_all_speech(tensor, model, **kwargs):
    """No silence anywhere — one speech span covering the whole clip."""
    return [{"start": 0, "end": 6_500 * SR // 1000}]


@pytest.fixture
def multi_silence_media(monkeypatch):
    path = _synthetic_multi_silence_wav()
    monkeypatch.setattr(ingest_mod, "_load_silero", lambda: (object(), _stub_multi_silence))
    yield path


@pytest.fixture
def all_speech_media(monkeypatch):
    path = _synthetic_multi_silence_wav()
    monkeypatch.setattr(ingest_mod, "_load_silero", lambda: (object(), _stub_all_speech))
    yield path


def _plan_req(media_path, **overrides):
    req = {
        "type": "plan",
        "media_path": media_path,
        "clip_start_ms": 0,
        "in_point_ms": 0,
        "out_point_ms": 6500,
        "timebase": dict(NTSC2997),
        "speed": 1.0,
        "reversed": False,
    }
    req.update(overrides)
    return req


def _regions_by_idx_span(mark_plan):
    return [(r["in_frame"], r["out_frame"]) for r in mark_plan["regions"]]


# ── hello / protocol ─────────────────────────────────────────────────────────

def test_hello_matching_version_ok():
    resp = handle_message({"type": "hello", "version": BRIDGE_VERSION})
    assert resp == {"type": "hello", "version": BRIDGE_VERSION}


def test_hello_version_mismatch_is_a_loud_failure():
    resp = handle_message({"type": "hello", "version": "0.1"})
    assert resp["type"] == "error"
    assert resp["reason"] == "version_mismatch"
    assert "0.1" in resp["message"]


def test_unknown_message_type_is_a_structured_error():
    resp = handle_message({"type": "surprise"})
    assert resp["type"] == "error"
    assert resp["reason"] == "unknown_message_type"


# ── plan happy path ──────────────────────────────────────────────────────────

def test_valid_descriptor_matches_hand_computed_silence(multi_silence_media, monkeypatch):
    from cutdeck.contracts import Timebase as TB
    tb = TB(fps_num=NTSC2997["fps_num"], fps_den=NTSC2997["fps_den"])

    resp = handle_message(
        _plan_req(multi_silence_media), cfg=CFG, rms_gate_enabled=False,
    )
    assert resp["type"] == "mark_plan"
    regions = resp["mark_plan"]["regions"]
    assert len(regions) == 2

    for region, (exp_start, exp_end) in zip(regions, [CUT1, CUT2]):
        assert region["reason"] == "silence"
        got_start_ms = frame_to_ms(region["in_frame"], tb)
        got_end_ms = frame_to_ms(region["out_frame"], tb)
        assert abs(got_start_ms - exp_start) <= 40   # within ~1 frame at 29.97
        assert abs(got_end_ms - exp_end) <= 40


def test_frame_numbers_back_convert_to_frame_snapped_ms(multi_silence_media):
    from cutdeck.contracts import Timebase as TB
    tb = TB(fps_num=NTSC2997["fps_num"], fps_den=NTSC2997["fps_den"])

    resp = handle_message(_plan_req(multi_silence_media), cfg=CFG, rms_gate_enabled=False)
    region = resp["mark_plan"]["regions"][0]
    # The frame number back-converts to the frame-snapped ms, not a raw
    # unsnapped ms: re-quantizing that ms must return the same frame.
    snapped_ms = frame_to_ms(region["in_frame"], tb)
    assert ms_to_frame(snapped_ms, tb) == region["in_frame"]


def test_no_silence_returns_valid_empty_mark_plan_not_error(all_speech_media):
    resp = handle_message(_plan_req(all_speech_media), cfg=CFG, rms_gate_enabled=False)
    assert resp["type"] == "mark_plan"
    assert resp["mark_plan"]["regions"] == []


def test_timebase_in_response_is_the_one_supplied_never_probed(multi_silence_media, monkeypatch):
    import transcribe.timebase as timebase_mod

    def _boom(*a, **kw):
        raise AssertionError("probe() must never be called on the live-clip path")

    monkeypatch.setattr(timebase_mod, "probe", _boom)

    odd_tb = {"fps_num": 24000, "fps_den": 1001}  # deliberately not probe()'s 25/1 default
    resp = handle_message(
        _plan_req(multi_silence_media, timebase=odd_tb), cfg=CFG, rms_gate_enabled=False,
    )
    assert resp["type"] == "mark_plan"
    assert resp["mark_plan"]["timebase"] == odd_tb


def test_no_asr_engine_imported(multi_silence_media):
    before = {m for m in sys.modules if m.startswith("engines")}
    handle_message(_plan_req(multi_silence_media), cfg=CFG, rms_gate_enabled=False)
    after = {m for m in sys.modules if m.startswith("engines")}
    assert after == before


# ── offset + clamping ────────────────────────────────────────────────────────

def test_nonzero_clip_start_and_inpoint_offset_correctly(multi_silence_media):
    # clip placed at 10s on the sequence; source clip visible range [2000, 5000)ms.
    resp = handle_message(
        _plan_req(multi_silence_media, clip_start_ms=10_000, in_point_ms=2_000, out_point_ms=5_000),
        cfg=CFG, rms_gate_enabled=False,
    )
    assert resp["type"] == "mark_plan"
    from cutdeck.contracts import Timebase as TB
    tb = TB(**NTSC2997)
    regions = resp["mark_plan"]["regions"]
    assert len(regions) == 2

    # cut1 [1620,2750] clamped to visible [2000,5000) -> [2000,2750], offset +8000
    exp1 = (2000 + 8000, 2750 + 8000)
    # cut2 [4120,5250] clamped to visible [2000,5000) -> [4120,5000], offset +8000
    exp2 = (4120 + 8000, 5000 + 8000)
    for region, (exp_start, exp_end) in zip(regions, [exp1, exp2]):
        got_start_ms = frame_to_ms(region["in_frame"], tb)
        got_end_ms = frame_to_ms(region["out_frame"], tb)
        assert abs(got_start_ms - exp_start) <= 40
        assert abs(got_end_ms - exp_end) <= 40


def test_silence_outside_visible_range_produces_no_mark(multi_silence_media):
    # visible range [0, 1500) ends exactly where the first silence begins.
    resp = handle_message(
        _plan_req(multi_silence_media, clip_start_ms=0, in_point_ms=0, out_point_ms=1_500),
        cfg=CFG, rms_gate_enabled=False,
    )
    assert resp["type"] == "mark_plan"
    assert resp["mark_plan"]["regions"] == []


# ── refusals ──────────────────────────────────────────────────────────────────

def test_vfr_timebase_is_a_structured_refusal(multi_silence_media):
    vfr_tb = {"fps_num": 30000, "fps_den": 1001, "is_vfr": True}
    resp = handle_message(
        _plan_req(multi_silence_media, timebase=vfr_tb), cfg=CFG, rms_gate_enabled=False,
    )
    assert resp["type"] == "error"
    assert resp["reason"] == "vfr"


def test_speed_change_is_a_structured_refusal(multi_silence_media):
    resp = handle_message(
        _plan_req(multi_silence_media, speed=1.5), cfg=CFG, rms_gate_enabled=False,
    )
    assert resp["type"] == "error"
    assert resp["reason"] == "speed_change"


def test_reversed_clip_is_a_structured_refusal(multi_silence_media):
    resp = handle_message(
        _plan_req(multi_silence_media, reversed=True), cfg=CFG, rms_gate_enabled=False,
    )
    assert resp["type"] == "error"
    assert resp["reason"] == "reversed"


def test_speed_and_reversed_refusals_have_distinct_reasons(multi_silence_media):
    r1 = handle_message(_plan_req(multi_silence_media, speed=2.0), cfg=CFG, rms_gate_enabled=False)
    r2 = handle_message(_plan_req(multi_silence_media, reversed=True), cfg=CFG, rms_gate_enabled=False)
    assert r1["reason"] != r2["reason"]


def test_missing_timebase_is_refused_and_probe_never_called(multi_silence_media, monkeypatch):
    import transcribe.timebase as timebase_mod

    def _boom(*a, **kw):
        raise AssertionError("probe() must never be called")

    monkeypatch.setattr(timebase_mod, "probe", _boom)

    req = _plan_req(multi_silence_media)
    del req["timebase"]
    resp = handle_message(req, cfg=CFG, rms_gate_enabled=False)
    assert resp["type"] == "error"
    assert resp["reason"] == "missing_timebase"


def test_missing_media_path_is_a_structured_refusal():
    req = _plan_req("")
    resp = handle_message(req, cfg=CFG)
    assert resp["type"] == "error"
    assert resp["reason"] == "missing_field"


def test_unreadable_media_path_is_a_structured_refusal():
    resp = handle_message(_plan_req("Z:/does/not/exist/nope.wav"), cfg=CFG)
    assert resp["type"] == "error"
    assert resp["reason"] == "unreadable_media"


# ── socket smoke test (thin — the behaviour lives in handle_message) ────────

def test_websocket_round_trip_smoke():
    async def _run():
        server = await serve(host="127.0.0.1", port=17890)
        try:
            import websockets

            async with websockets.connect("ws://127.0.0.1:17890") as ws:
                await ws.send(json.dumps({"type": "hello", "version": BRIDGE_VERSION}))
                raw = await ws.recv()
                return json.loads(raw)
        finally:
            server.close()
            await server.wait_closed()

    resp = asyncio.run(_run())
    assert resp == {"type": "hello", "version": BRIDGE_VERSION}
