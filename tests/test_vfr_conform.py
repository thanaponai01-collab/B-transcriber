"""Phase 4.3 — VFR conform: transcode a CFR proxy before frame-accurate export
(IMPLEMENT_IMPROVEMENTS.md Phase 4.3 / GAP-2 other half).

xml_export.to_xml() still hard-refuses a VFR timebase (unchanged, tested in
test_cutdeck_xml_export.py). These tests cover the new opt-in conform path:
transcribe.timebase.conform_vfr() and cutdeck.xml_export's config gate.

2026-08-10 (TODO_LEDGER.md GAP-2 follow-up): the unit-level pieces above were
already correct in isolation, but nothing exercised cutdeck.xml_export.main()
end-to-end -- which is the only way this code actually runs in production.
That gap hid a real bug: cutdeck/plan.py's CutPlan JSON round-trip (to_dict/
from_dict, what save_plan/load_plan use) silently dropped Timebase.is_vfr,
so a real VFR source's plan came back is_vfr=False the instant it was saved
and reloaded from the DB -- exactly what main() always does. Both the
refusal path and the conform path were therefore dead code in the real CLI
flow despite passing every existing unit test. Fixed in cutdeck/plan.py;
the tests below drive main() through the real DB round-trip so this class of
bug can't hide again.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from cutdeck import xml_export
from cutdeck.contracts import CutPlan, CutSpan, KEEP, Timebase
from cutdeck.plan import save_plan
from transcribe.timebase import conform_vfr


VFR_TB = Timebase(fps_num=30000, fps_den=1001, duration_ms=5000, is_vfr=True)
CFR_TB = Timebase(fps_num=30000, fps_den=1001, duration_ms=5000, is_vfr=False)


def _seed_vfr_plan(tmp_path):
    """A minimal job/media/plan fixture with a real (VFR) Timebase, saved
    through the same store round-trip main() reads back."""
    from transcribe.db import store

    media_path = tmp_path / "clip.mp4"
    media_path.write_bytes(b"fake video bytes")

    db = tmp_path / "test.db"
    store.init_db(db)
    conn = store.connect(db)
    media_id = store.create_media(conn, str(media_path))
    store.set_media_timebase(conn, media_id, VFR_TB.fps_num, VFR_TB.fps_den, is_vfr=True)
    job_id = store.create_job(conn, media_id, "faster_whisper", "passthrough", "1.0")

    spans = [CutSpan(idx=0, src_in_ms=0, src_out_ms=VFR_TB.duration_ms, action=KEEP)]
    plan = CutPlan(job_id=job_id, media_sha256="x" * 64, timebase=VFR_TB, spans=spans)
    plan_id = save_plan(conn, plan)
    conn.close()
    return db, plan_id, media_path


def test_main_refuses_persisted_vfr_plan_without_conform_flag(tmp_path):
    """The bug this closes: before the is_vfr round-trip fix, this exact flow
    -- save a VFR plan, reload it via main() -- silently exported instead of
    refusing, because the reloaded plan always reported is_vfr=False."""
    db, plan_id, _media_path = _seed_vfr_plan(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("engine_a: faster_whisper\n", encoding="utf-8")  # conform_vfr unset -> False

    with pytest.raises(ValueError, match="VFR"):
        xml_export.main(["--plan-id", str(plan_id), "--db", str(db), "--config", str(cfg),
                          "--out", str(tmp_path / "out.xml")])


def test_main_conforms_and_exports_persisted_vfr_plan_when_enabled(tmp_path):
    db, plan_id, media_path = _seed_vfr_plan(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("conform_vfr: true\n", encoding="utf-8")
    proxy_path = tmp_path / "clip.cfr_proxy.mp4"
    proxy_path.write_bytes(b"fake proxy bytes")
    out = tmp_path / "out.xml"

    with patch("transcribe.timebase.conform_vfr", return_value=(str(proxy_path), CFR_TB)) as mock_conform:
        xml_export.main(["--plan-id", str(plan_id), "--db", str(db), "--config", str(cfg),
                          "--out", str(out)])

    mock_conform.assert_called_once()
    assert mock_conform.call_args[0][0] == str(media_path)  # conformed the ORIGINAL vfr source
    assert out.exists()
    xml_text = out.read_text(encoding="utf-8")
    assert "clip.cfr_proxy.mp4" in xml_text  # exported against the proxy, not the vfr original


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
