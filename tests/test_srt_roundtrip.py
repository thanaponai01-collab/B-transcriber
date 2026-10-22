"""tools/srt_roundtrip: the comparison judges captions by frame, from the sequence's own timebase."""
from tools.srt_roundtrip import compare, stress_cues
from transcribe.subtitles import read_subtitles, write_subtitles
from transcribe.timebase import Timebase, ms_to_frame

NTSC_TPF = 8475667200  # PREMIERE_FACTS: getTimebase at 29.97
NTSC = Timebase(30000, 1001)


def report_for(srt: str, shift_frames: int = 0, drop: int = 0) -> dict:
    cues = read_subtitles(srt)[drop:]
    items = [{"start_ticks": str((ms_to_frame(c["start_ms"], NTSC) + shift_frames) * NTSC_TPF),
              "end_ticks": str((ms_to_frame(c["end_ms"], NTSC) + shift_frames) * NTSC_TPF)} for c in cues]
    return {"ticks_per_frame": str(NTSC_TPF), "sequence_name": "t", "tracks": [{"index": 0, "items": items}]}


def test_snapped_stress_file_passes_when_premiere_keeps_every_frame():
    srt = write_subtitles(stress_cues(NTSC), "srt", fps=29.97)
    lines, ok = compare(srt, report_for(srt))
    assert ok, lines
    assert lines[0].startswith("sequence 't' at 30000/1001 fps")


def test_a_one_frame_shift_or_a_dropped_cue_fails():
    srt = write_subtitles(stress_cues(NTSC), "srt", fps=29.97)
    assert not compare(srt, report_for(srt, shift_frames=1))[1]
    lines, ok = compare(srt, report_for(srt, drop=1))
    assert not ok and any("dropped or merged" in line for line in lines)


def test_raw_stress_file_has_the_cases_snapping_fixes():
    raw = read_subtitles(write_subtitles(stress_cues(NTSC), "srt"))
    frames = [(ms_to_frame(c["start_ms"], NTSC), ms_to_frame(c["end_ms"], NTSC)) for c in raw]
    assert any(s == e for s, e in frames)                          # a cue under one frame
    assert any(a[0] == b[0] for a, b in zip(frames, frames[1:]))   # two cues starting on one frame
