"""Rough Cut input as JSON (docs/arch-design-helper-v2.md move 6): the panel's native read of the
audio tracks must reach the analysis exactly as a real Premiere XML export did."""
import asyncio
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import pytest
import soundfile as sf

from cutdeck import sequence_json
from cutdeck.xml_bridge import XmlJobs, range_from_ticks, reference_audio_track
from cutdeck.xml_sequence import (PPRO_TICKS_PER_SECOND, check_reference_audio, clip_source_span_seconds,
                                  enabled_clips, resolve_file_path, select_audio_track, sequence_timebase)

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


def _what_the_analysis_reads(xml: str, premiere_track):
    """Everything check_reference_audio / extract_mixdown / xml_recut take from the XML."""
    xml_track = reference_audio_track(xml, {"audio_track": premiere_track,
                                            "audio_track_count": len(_panel_read_of_the_fixture()["audio_tracks"])})
    sequence = ET.fromstring(xml).find("sequence")
    tb = sequence_timebase(sequence)
    track = select_audio_track(sequence, xml_track)
    clips = [(int(c.findtext("start")), clip_source_span_seconds(c, tb),
              resolve_file_path(sequence, c.find("file").get("id"))) for c in enabled_clips(track)]
    return tb, int(sequence.findtext("duration")), clips


@pytest.mark.parametrize("premiere_track", [None, 0, 1, 2, 3, 4, 5])
def test_json_reaches_the_analysis_exactly_as_the_real_export_did(premiere_track):
    exported = FIXTURE.read_text(encoding="utf-8")
    generated = sequence_json.to_fcp7_xml(sequence_json.validate(_panel_read_of_the_fixture()))
    assert _what_the_analysis_reads(generated, premiere_track) == _what_the_analysis_reads(exported, premiere_track)


def test_the_live_range_check_accepts_the_generated_sequence():
    read = _panel_read_of_the_fixture()
    xml = sequence_json.to_fcp7_xml(sequence_json.validate(read))
    context = {"in_ticks": str(60 * TPF_30), "out_ticks": str(120 * TPF_30), "end_ticks": read["end_ticks"],
               "ticks_per_frame": read["ticks_per_frame"]}
    assert range_from_ticks(xml, context) == (60, 120)


def test_a_mixdown_from_json_puts_the_audio_where_the_clip_sits(tmp_path):
    """Real ffmpeg: a 1 s tone placed at 1 s in a 3 s sequence lands at 1 s in the mixdown."""
    from cutdeck.xml_audio_extract import extract_mixdown
    rate = 48000
    tone = tmp_path / "tone.wav"
    sf.write(tone, 0.5 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate).astype(np.float32), rate)
    read = {"ticks_per_frame": str(TPF_30), "end_ticks": str(90 * TPF_30), "audio_tracks": [
        {"enabled": True, "clips": [{"path": str(tone), "enabled": True, "start_ticks": str(30 * TPF_30),
                                     "in_ticks": "0", "out_ticks": str(PPRO_TICKS_PER_SECOND)}]}]}
    xml = sequence_json.to_fcp7_xml(sequence_json.validate(read))
    assert check_reference_audio(xml, 0)["files"] == [str(tone)]
    audio, sr = sf.read(extract_mixdown(xml, str(tmp_path / "mix.wav"), 0), dtype="float32")
    level = lambda a, b: float(np.sqrt(np.mean(audio[int(a * sr):int(b * sr)] ** 2)))  # noqa: E731
    assert len(audio) == 3 * sr
    assert level(0.05, 0.95) < 1e-3 and level(2.05, 2.95) < 1e-3
    assert level(1.05, 1.95) > 0.3


@pytest.mark.parametrize("tpf, expected", [
    (PPRO_TICKS_PER_SECOND // 30, (30, False)), (PPRO_TICKS_PER_SECOND // 25, (25, False)),
    (8475667200, (30, True)), (10594584000, (24, True)), (4237833600, (60, True))])
def test_frame_rates_become_the_xml_rate(tpf, expected):
    assert sequence_json.timebase(tpf) == expected


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
        sequence_json.validate(sequence)


def test_prepare_writes_the_source_and_a_refused_prepare_leaves_nothing(tmp_path):
    context = {"type": "prepare", "project_id": "p", "sequence_id": "s", "sequence_name": "Seq & <1>",
               "audio_track": 0, "audio_track_count": 1, "asr": False, "in_ticks": "0",
               "out_ticks": str(30 * TPF_30), "end_ticks": str(90 * TPF_30), "ticks_per_frame": str(TPF_30)}

    async def _test():
        jobs = XmlJobs(tmp_path)
        job = await jobs.dispatch({**context, "sequence": _read()})
        source = Path(job["source_path"]).read_text(encoding="utf-8")
        assert ET.fromstring(source).findtext("sequence/name") == "Seq & <1>"
        assert range_from_ticks(source, context) == (0, 30)
        before = sorted(p.name for p in tmp_path.iterdir())
        with pytest.raises(ValueError, match="no media file"):
            await jobs.dispatch({**context, "sequence": _read(path=None)})
        assert sorted(p.name for p in tmp_path.iterdir()) == before

    asyncio.run(_test())
