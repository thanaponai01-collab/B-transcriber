"""Verification test for issue #76: sync SYSTEM_SPEC.md with codebase and ENGINES.md."""
from pathlib import Path
import re

SPEC_PATH = Path(__file__).resolve().parent.parent / "SYSTEM_SPEC.md"


def test_system_spec_contains_required_modules():
    text = SPEC_PATH.read_text(encoding="utf-8")

    # 1. Required modules present
    assert "service.py" in text, "SYSTEM_SPEC.md must mention service.py"
    assert "coverage.py" in text, "SYSTEM_SPEC.md must mention coverage.py"
    assert "review.py" in text, "SYSTEM_SPEC.md must mention review.py"
    assert "qwen3_asr.py" in text, "SYSTEM_SPEC.md must mention qwen3_asr.py"


def test_system_spec_engine_table_statuses():
    text = SPEC_PATH.read_text(encoding="utf-8")

    # 2. Engine status table
    assert "qwen3_asr.py" in text
    assert re.search(r"`funasr\.py`.*?retired", text, re.IGNORECASE | re.DOTALL), (
        "funasr.py must be marked retired in SYSTEM_SPEC.md"
    )
    assert re.search(r"`typhoon_rt\.py`.*?rejected", text, re.IGNORECASE | re.DOTALL), (
        "typhoon_rt.py must be marked rejected in SYSTEM_SPEC.md"
    )
    assert re.search(r"`qwen3_asr\.py`.*?not activated", text, re.IGNORECASE | re.DOTALL), (
        "qwen3_asr.py must be marked built / not activated in SYSTEM_SPEC.md"
    )


def test_system_spec_metrics_version_and_signals():
    text = SPEC_PATH.read_text(encoding="utf-8")

    # 3. METRICS_VERSION = 4 and 5 gated signals
    assert "METRICS_VERSION = 4" in text, "SYSTEM_SPEC.md must document METRICS_VERSION = 4"
    assert "speech_coverage_miss" in text, "SYSTEM_SPEC.md must document speech_coverage_miss"
    assert "cue_boundary_error_rate" in text, "SYSTEM_SPEC.md must document cue_boundary_error_rate"
    assert "orphan_cues" in text, "SYSTEM_SPEC.md must document orphan_cues"
    assert "overlapping_cues" in text, "SYSTEM_SPEC.md must document overlapping_cues"
