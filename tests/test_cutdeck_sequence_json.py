"""Rough Cut input as JSON (docs/arch-design-helper-v2.md move 6): the panel's native read of the
audio tracks must reach the analysis exactly as a real Premiere XML export did."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import pytest
import soundfile as sf

from cutdeck import sequence_model
from cutdeck.sequence_model import check_reference_audio, from_fcp7_xml, from_panel_json
from cutdeck.xml_bridge import XmlJobs, range_from_ticks, reference_audio_track
from cutdeck.xml_sequence import PPRO_TICKS_PER_SECOND, resolve_file_path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "cutdeck_recut_sample_scrubbed.xml"
TPF_30 = PPRO_TICKS_PER_SECOND // 30


def _panel_read_of_the_fixture() -> dict:
    """What the panel reads natively from the sequence the fixture was exported from: one entry per
    Premiere audio track (the export splits each stereo track into two XML tracks)."""
    sequence = ET.fromstring(FIXTURE.read_text(encoding="utf-8")).find("sequence")
    tracks = []
    for track in sequence.findall("media/audio/track"):
        if track.get("currentExplodedTrackIndex", "0") != "0":
            continue
        clips = [{"path": str(resolve_file_path(sequence, c.find("file").get("id"))),
                  "enabled": c.findtext("enabled") == "TRUE",
                  "start_ticks": str(int(c.findtext("start")) * TPF_30),
                  "in_ticks": c.findtext("pproTicksIn"), "out_ticks": c.findtext("pproTicksOut")}
                 for c in track.findall("clipitem")]
        tracks.append({"enabled": track.findtext("enabled", "TRUE") == "TRUE", "clips": clips})
    return {"ticks_per_frame": str(TPF_30), "end_ticks": str(int(sequence.findtext("duration")) * TPF_30),
            "audio_tracks": tracks}


def test_the_real_export_and_the_panel_read_are_the_same_sequence():
    exported = from_fcp7_xml(FIXTURE.read_text(encoding="utf-8"))
    assert exported == from_panel_json(_panel_read_of_the_fixture())
    assert len(exported.tracks) == 6  # the export's exploded stereo channels are regrouped


@pytest.mark.parametrize("premiere_track", [None, 0, 1, 2, 3, 4, 5])
def test_both_routes_pick_the_same_reference_track_and_clips(premiere_track):
    exported = from_fcp7_xml(FIXTURE.read_text(encoding="utf-8"))
    panel = from_panel_json(_panel_read_of_the_fixture())
    request = {"audio_track": premiere_track, "audio_track_count": 6}
    index = reference_audio_track(exported, request)
    assert index == reference_audio_track(panel, request) == premiere_track
    assert exported.reference_track(index) == panel.reference_track(index)


def test_cuts_json_from_both_routes_matches_frame_for_frame(tmp_path):
    """The whole analysis (real ffmpeg extraction, VAD, cut rules) on the same audio, fed each way."""
    tone = tmp_path / "tone.wav"
    rate = 48000
    audio = np.zeros(rate * 6, dtype=np.float32)
    audio[rate:rate * 2] = 0.5 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate)
    audio[rate * 4:rate * 5] = 0.5 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate)
    sf.write(tone, audio, rate)
    read = {"ticks_per_frame": str(TPF_30), "end_ticks": str(180 * TPF_30), "audio_tracks": [
        {"enabled": True, "clips": [{"path": str(tone), "enabled": True, "start_ticks": "0",
                                     "in_ticks": "0", "out_ticks": str(6 * PPRO_TICKS_PER_SECOND)}]}]}
    xml = tmp_path / "export.xml"
    xml.write_text(_xml_export_of(read), encoding="utf-8")
    (tmp_path / "sequence.json").write_text(json.dumps(read), encoding="utf-8")
    cuts = {}
    for name in ("export.xml", "sequence.json"):
        out = tmp_path / f"{name}.cuts.json"
        run = subprocess.run([sys.executable, "-m", "cutdeck.xml_recut", str(tmp_path / name), "--cuts-json",
                              str(out), "--no-save-plan", "--config", str(ROOT / "transcribe/config.yaml"),
                              "--overlay", str(ROOT / "transcribe/config.aggressive_cut.yaml")],
                             cwd=ROOT, capture_output=True, text=True)
        assert run.returncode == 0, run.stdout + run.stderr
        cuts[name] = json.loads(out.read_text(encoding="utf-8"))
    assert cuts["export.xml"]["cuts_frames"], "the silences between the tones should be cut"
    assert cuts["export.xml"]["cuts_frames"] == cuts["sequence.json"]["cuts_frames"]


def _xml_export_of(read: dict) -> str:
    """A minimal FCP7 export of a one-track panel read, as Premiere writes it (pproTicks, pathurl)."""
    from cutdeck.xml_export import _pathurl
    clip = read["audio_tracks"][0]["clips"][0]
    frames = lambda ticks: int(ticks) // TPF_30  # noqa: E731
    return f"""<?xml version="1.0" encoding="UTF-8"?><xmeml version="4"><sequence id="s"><name>t</name>
<duration>{frames(read["end_ticks"])}</duration><rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate>
<media><audio><track><clipitem id="c1"><name>t</name><enabled>TRUE</enabled><start>{frames(clip["start_ticks"])}</start>
<end>{frames(clip["out_ticks"])}</end><in>0</in><out>{frames(clip["out_ticks"])}</out>
<pproTicksIn>{clip["in_ticks"]}</pproTicksIn><pproTicksOut>{clip["out_ticks"]}</pproTicksOut>
<file id="f1"><pathurl>{_pathurl(clip["path"])}</pathurl></file></clipitem><enabled>TRUE</enabled></track></audio></media></sequence></xmeml>"""


def test_load_reads_both_a_sequence_json_and_a_prepared_job_from_before_the_model(tmp_path):
    """Jobs prepared by an earlier helper hold `source.xml`; they must still start."""
    read = _panel_read_of_the_fixture()
    (tmp_path / "sequence.json").write_text(json.dumps(read), encoding="utf-8")
    (tmp_path / "source.xml").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    assert sequence_model.load(tmp_path / "sequence.json") == sequence_model.load(tmp_path / "source.xml")


def test_the_live_range_check_accepts_the_panel_read():
    read = _panel_read_of_the_fixture()
    context = {"in_ticks": str(60 * TPF_30), "out_ticks": str(120 * TPF_30), "end_ticks": read["end_ticks"],
               "ticks_per_frame": read["ticks_per_frame"]}
    assert range_from_ticks(from_panel_json(read), context) == (60, 120)
    assert range_from_ticks(from_fcp7_xml(FIXTURE.read_text(encoding="utf-8")), context) == (60, 120)


def test_a_mixdown_from_json_puts_the_audio_where_the_clip_sits(tmp_path):
    """Real ffmpeg: a 1 s tone placed at 1 s in a 3 s sequence lands at 1 s in the mixdown."""
    from cutdeck.xml_audio_extract import extract_mixdown
    rate = 48000
    tone = tmp_path / "tone.wav"
    sf.write(tone, 0.5 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate).astype(np.float32), rate)
    read = {"ticks_per_frame": str(TPF_30), "end_ticks": str(90 * TPF_30), "audio_tracks": [
        {"enabled": True, "clips": [{"path": str(tone), "enabled": True, "start_ticks": str(30 * TPF_30),
                                     "in_ticks": "0", "out_ticks": str(PPRO_TICKS_PER_SECOND)}]}]}
    sequence = from_panel_json(read)
    assert check_reference_audio(sequence, 0)["files"] == [str(tone)]
    audio, sr = sf.read(extract_mixdown(sequence, str(tmp_path / "mix.wav"), 0), dtype="float32")
    level = lambda a, b: float(np.sqrt(np.mean(audio[int(a * sr):int(b * sr)] ** 2)))  # noqa: E731
    assert len(audio) == 3 * sr
    assert level(0.05, 0.95) < 1e-3 and level(2.05, 2.95) < 1e-3
    assert level(1.05, 1.95) > 0.3


@pytest.mark.parametrize("tpf, expected", [
    (PPRO_TICKS_PER_SECOND // 30, (30, False)), (PPRO_TICKS_PER_SECOND // 25, (25, False)),
    (8475667200, (30, True)), (10594584000, (24, True)), (4237833600, (60, True))])
def test_frame_rates_become_the_xml_rate(tpf, expected):
    assert sequence_model.timebase(tpf) == expected


def _read(**clip):
    return {"ticks_per_frame": str(TPF_30), "end_ticks": str(90 * TPF_30), "audio_tracks": [
        {"enabled": True, "clips": [{"path": "C:/m/a.wav", "enabled": True, "start_ticks": "0",
                                     "in_ticks": "0", "out_ticks": "100", **clip}]}]}


@pytest.mark.parametrize("sequence, message", [
    (None, "must be an object"),
    ({**_read(), "ticks_per_frame": "12345"}, "frame rate"),
    ({**_read(), "ticks_per_frame": 8467200000}, "ticks_per_frame"),
    ({**_read(), "audio_tracks": []}, "no audio tracks"),
    (_read(path=None), "no media file"),
    (_read(path="relative/a.wav"), "no media file"),
    (_read(enabled="yes"), "malformed"),
    (_read(out_ticks="0"), "Out before its In"),
    (_read(start_ticks="-5"), "start_ticks"),
])
def test_a_bad_read_is_refused_whole(sequence, message):
    with pytest.raises(ValueError, match=message):
        from_panel_json(sequence)


def test_prepare_writes_the_sequence_and_a_refused_prepare_leaves_nothing(tmp_path):
    context = {"type": "prepare", "project_id": "p", "sequence_id": "s", "sequence_name": "Seq & <1>",
               "audio_track": 0, "audio_track_count": 1, "asr": False, "in_ticks": "0",
               "out_ticks": str(30 * TPF_30), "end_ticks": str(90 * TPF_30), "ticks_per_frame": str(TPF_30)}

    async def _test():
        jobs = XmlJobs(tmp_path)
        job = await jobs.dispatch({**context, "sequence": _read()})
        source = sequence_model.load(job["source_path"])
        assert Path(job["source_path"]).name == "sequence.json"
        assert range_from_ticks(source, context) == (0, 30)
        before = sorted(p.name for p in tmp_path.iterdir())
        with pytest.raises(ValueError, match="no media file"):
            await jobs.dispatch({**context, "sequence": _read(path=None)})
        assert sorted(p.name for p in tmp_path.iterdir()) == before

    asyncio.run(_test())
