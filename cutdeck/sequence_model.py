"""Validated sequence audio from the panel JSON snapshot, in exact Premiere ticks."""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path, PurePosixPath, PureWindowsPath

from cutdeck.contracts import Timebase
from cutdeck.sequence_timing import PPRO_TICKS_PER_SECOND, SequenceRefusal

MAX_TRACKS = 128
MAX_CLIPS = 20000


@dataclass(frozen=True)
class Clip:
    path: str | None  # None: a clip with no readable source media
    start_ticks: int  # where it sits on the sequence
    in_ticks: int     # source In / Out
    out_ticks: int
    enabled: bool
    speed: float = 1.0  # playback speed; 1.0 = normal. The analysis reads audio at normal speed only.

    @property
    def end_ticks(self) -> int:
        return self.start_ticks + self.out_ticks - self.in_ticks

    @property
    def media_path(self) -> str:
        """The source file, for an analysis that reads this clip's audio."""
        if self.path is None:
            raise SequenceRefusal("a clip has no source media path")
        return self.path


@dataclass(frozen=True)
class Track:
    index: int  # 0-based Premiere audio track (A1 is 0)
    muted: bool
    clips: tuple[Clip, ...]


@dataclass(frozen=True)
class Sequence:
    ticks_per_frame: int
    end_ticks: int
    tracks: tuple[Track, ...]

    @property
    def timebase(self) -> Timebase:
        base, ntsc = timebase(self.ticks_per_frame)
        return Timebase(fps_num=base * 1000, fps_den=1001) if ntsc else Timebase(fps_num=base, fps_den=1)

    @property
    def duration_frames(self) -> int:
        return self.end_ticks // self.ticks_per_frame

    def reference_track(self, index: int | None) -> Track:
        """The dialogue track VAD reads: ``index``, or the first switched-on track with clips.

        An explicit index is honored even when that track is switched off: the editor chose it,
        and a lav track muted in the mix is still the best thing to analyze. Nothing here guesses
        by loudness."""
        if not self.tracks:
            raise SequenceRefusal("sequence has no audio tracks to extract from")
        if index is not None:
            if not 0 <= index < len(self.tracks):
                raise SequenceRefusal(f"sequence has {len(self.tracks)} audio track(s), requested index "
                                      f"{index} (0-based)")
            return self.tracks[index]
        with_clips = [track for track in self.tracks if track.clips]
        if not with_clips:
            raise SequenceRefusal("no audio track has any clips")
        for track in with_clips:
            if not track.muted:
                return track
        raise SequenceRefusal("every audio track with clips is switched off; choose a Reference Audio track")


def _ticks(value, what: str) -> int:
    if not isinstance(value, str) or not value.isdigit() or len(value) > 24:
        raise ValueError(f"{what} must be a whole number of ticks as a string")
    return int(value)


def _is_absolute(path: str) -> bool:
    return PureWindowsPath(path).is_absolute() or PurePosixPath(path).is_absolute()


def timebase(ticks_per_frame: int) -> tuple[int, bool]:
    """(nominal fps, ntsc) for Premiere's ticks per frame."""
    if ticks_per_frame <= 0:
        raise ValueError("ticks_per_frame must be positive")
    whole, rest = divmod(PPRO_TICKS_PER_SECOND, ticks_per_frame)
    if not rest:
        return whole, False
    ntsc, rest = divmod(PPRO_TICKS_PER_SECOND * 1001, ticks_per_frame * 1000)
    if not rest:
        return ntsc, True
    raise ValueError("Unsupported sequence frame rate")


def from_panel_json(sequence) -> Sequence:
    """The panel's sequence read, checked; refused whole before any job folder is made."""
    if not isinstance(sequence, dict):
        raise ValueError("sequence must be an object")
    tpf = _ticks(sequence.get("ticks_per_frame"), "ticks_per_frame")
    timebase(tpf)
    end = _ticks(sequence.get("end_ticks"), "end_ticks")
    tracks = sequence.get("audio_tracks")
    if not isinstance(tracks, list) or not 0 < len(tracks) <= MAX_TRACKS:
        raise ValueError("The sequence has no audio tracks to analyse")
    out, total = [], 0
    for index, track in enumerate(tracks, start=1):
        if not isinstance(track, dict) or type(track.get("enabled")) is not bool or not isinstance(track.get("clips"), list):
            raise ValueError(f"Audio track A{index} is malformed")
        clips = []
        for clip in track["clips"]:
            total += 1
            if total > MAX_CLIPS:
                raise ValueError(f"More than {MAX_CLIPS} audio clips; mark a shorter In/Out range")
            if not isinstance(clip, dict) or type(clip.get("enabled")) is not bool:
                raise ValueError(f"A clip on A{index} is malformed")
            path = clip.get("path")
            if not isinstance(path, str) or not _is_absolute(path):
                # The XML route refused nested sequences outright; a clip with no media file
                # would otherwise be silence in the analysis.
                raise ValueError(f"A clip on A{index} has no media file (a nested sequence?); "
                                 "CutDeck can't analyse it")
            start = _ticks(clip.get("start_ticks"), "start_ticks")
            media_in = _ticks(clip.get("in_ticks"), "in_ticks")
            media_out = _ticks(clip.get("out_ticks"), "out_ticks")
            if media_out <= media_in:
                raise ValueError(f"A clip on A{index} has its Out before its In")
            speed = clip.get("speed", 1.0)
            if type(speed) not in (int, float) or not 0 < speed < float("inf"):
                raise ValueError(f"A clip on A{index} has a malformed speed")
            clips.append(Clip(path, start, media_in, media_out, clip["enabled"], float(speed)))
        out.append(Track(index - 1, not track["enabled"], tuple(clips)))
    return Sequence(tpf, end, tuple(out))


def _has_audio_stream(path: Path) -> bool | None:
    """True/False from ffprobe, or None when ffprobe cannot answer (missing, unreadable)."""
    if shutil.which("ffprobe") is None:
        return None
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-of", "json", "-show_entries", "stream=codec_type", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        return None
    try:
        streams = json.loads(result.stdout).get("streams", [])
    except ValueError:
        return None
    return any(stream.get("codec_type") == "audio" for stream in streams)


def check_reference_audio(sequence: Sequence, audio_track_index: int | None = None) -> dict:
    """Refuse, before any audio is extracted or transcribed, what ``extract_mixdown`` would fail
    on or silently get wrong. Returns what will be analyzed.

    Checks: the reference track selection itself; every enabled clip's source file exists and has
    an audio stream. A source frame rate that differs from the sequence is fine: extraction works
    in seconds."""
    track = sequence.reference_track(audio_track_index)
    clips = [clip for clip in track.clips if clip.enabled]
    if not clips:
        raise SequenceRefusal("the reference audio track has no enabled clips")
    for clip in clips:
        if clip.speed != 1.0:
            raise SequenceRefusal(
                f"a clip on A{track.index + 1} plays at {clip.speed * 100:.0f}% speed; the analysis reads its "
                "audio at normal speed, so its cuts would land in the wrong places. Set it to 100% or choose "
                "another Reference Audio track")
    files: list[Path] = []
    for clip in clips:
        if Path(clip.media_path) not in files:
            files.append(Path(clip.media_path))
    for path in files:
        if not path.is_file():
            raise SequenceRefusal(f"source media is missing or offline: {path}")
        if _has_audio_stream(path) is False:
            raise SequenceRefusal(f"source media has no audio stream: {path}")
    return {"track": track.index, "clip_count": len(clips), "files": [str(path) for path in files]}


def load(path: str | Path) -> Sequence:
    """Read a persisted panel JSON snapshot; XML input is retired."""
    path = Path(path)
    if path.suffix.lower() != ".json":
        raise SequenceRefusal("XML Rough Cut is retired. Start a new Rough Cut in the panel or use premiere_rough_cut.")
    return from_panel_json(json.loads(path.read_text(encoding="utf-8-sig")))
