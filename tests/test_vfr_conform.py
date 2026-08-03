"""Phase 4.3 — VFR conform: transcode a CFR proxy before frame-accurate export
(IMPLEMENT_IMPROVEMENTS.md Phase 4.3 / GAP-2 other half).

xml_export.to_xml() still hard-refuses a VFR timebase (unchanged, tested in
test_cutdeck_xml_export.py). These tests cover the new opt-in conform path:
transcribe.timebase.conform_vfr() and cutdeck.xml_export's config gate.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from transcribe.timebase import Timebase, conform_vfr


VFR_TB = Timebase(fps_num=30000, fps_den=1001, duration_ms=5000, is_vfr=True)
CFR_TB = Timebase(fps_num=30000, fps_den=1001, duration_ms=5000, is_vfr=False)


def test_conform_vfr_invokes_ffmpeg_and_reprobes(tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fake")

    with patch("transcribe.timebase.shutil.which", return_value="/usr/bin/ffmpeg"), \
         patch("transcribe.timebase.subprocess.run") as mock_run, \
         patch("transcribe.timebase.probe", return_value=CFR_TB) as mock_probe:
        proxy_path, new_tb = conform_vfr(str(src), VFR_TB, out_dir=str(tmp_path))

    assert proxy_path == str(tmp_path / "clip.cfr_proxy.mp4")
    assert new_tb.is_vfr is False
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "ffmpeg"
    assert "-vsync" in cmd and "cfr" in cmd
    assert "30000/1001" in cmd
    mock_probe.assert_called_once_with(proxy_path)


def test_conform_vfr_raises_if_proxy_still_vfr(tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fake")

    with patch("transcribe.timebase.shutil.which", return_value="/usr/bin/ffmpeg"), \
         patch("transcribe.timebase.subprocess.run"), \
         patch("transcribe.timebase.probe", return_value=VFR_TB):
        with pytest.raises(RuntimeError, match="still reports VFR"):
            conform_vfr(str(src), VFR_TB, out_dir=str(tmp_path))


def test_conform_vfr_requires_ffmpeg_on_path(tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fake")
    with patch("transcribe.timebase.shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="ffmpeg not found"):
            conform_vfr(str(src), VFR_TB, out_dir=str(tmp_path))


def test_conform_vfr_disabled_by_default(tmp_path):
    from cutdeck.xml_export import _conform_vfr_enabled

    cfg = tmp_path / "config.yaml"
    cfg.write_text("engine_a: faster_whisper\n", encoding="utf-8")
    assert _conform_vfr_enabled(str(cfg)) is False


def test_conform_vfr_enabled_reads_config_flag(tmp_path):
    from cutdeck.xml_export import _conform_vfr_enabled

    cfg = tmp_path / "config.yaml"
    cfg.write_text("conform_vfr: true\n", encoding="utf-8")
    assert _conform_vfr_enabled(str(cfg)) is True


def test_conform_vfr_enabled_missing_config_defaults_false():
    from cutdeck.xml_export import _conform_vfr_enabled

    assert _conform_vfr_enabled("does/not/exist.yaml") is False
