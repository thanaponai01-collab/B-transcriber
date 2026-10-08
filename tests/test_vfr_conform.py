"""Phase 4.3 — VFR conform: transcode a CFR proxy before frame-accurate work
(IMPLEMENT_IMPROVEMENTS.md Phase 4.3 / GAP-2 other half). Covers
transcribe.timebase.conform_vfr(): ffmpeg is invoked and the proxy re-probed.
"""

from unittest.mock import patch

import pytest

from cutdeck.contracts import Timebase
from transcribe.timebase import conform_vfr


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
