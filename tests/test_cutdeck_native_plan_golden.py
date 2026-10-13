"""The native planner's frozen capture remains an independent oracle after XML retirement."""
import hashlib
import json
from pathlib import Path

GOLDEN = Path(__file__).parent / "fixtures/cutdeck_native_plan_golden.json"


def test_native_golden_capture_is_unchanged():
    assert hashlib.sha256(GOLDEN.read_bytes()).hexdigest() == "25a154d2c9f6780f9a5bd26788f420c1933387171ad47017e70c0b33917aae81"
    captured = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert captured["cuts_frames"] == [[10, 40], [200, 300], [1000, 1100], [5000, 5003], [32900, 32948]]
    assert captured["ticks_per_frame"] == "8467200000"
    assert captured["before"] and captured["after"]
