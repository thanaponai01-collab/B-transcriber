"""What the timeline says, without listening to it again.

A cut timeline is a list of pieces of source files. Each source file is transcribed once
(`transcribe(media_path)`, cached by sha256 in the shared store) and its word timeline is
mapped through the clip list onto the sequence, in exact Premiere ticks. A copy, a re-cut or a
reorder of the same footage needs no new transcription: only this mapping runs again.

Mapping, for a clip at sequence ``start`` playing source ``[in, out)`` at 100% speed:
``sequence_ticks = start + (source_ticks - in)``. A word the clip's In or Out cuts through is
kept with ``clipped`` set, and the edge is reported in ``edges``: that is a cut inside speech.

Pure apart from `source_words` (reads the store) and `build` (the helper entry point).
"""
from __future__ import annotations

import bisect
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from cutdeck.sequence_timing import PPRO_TICKS_PER_SECOND

TICKS_PER_MS = PPRO_TICKS_PER_SECOND // 1000
# A word cut by less than this at a clip edge is timing noise, not a cut through the word.
CLIP_TOLERANCE_MS = 40


@dataclass(frozen=True)
class Clip:
    id: str
    start: int  # sequence ticks
    end: int
    in_: int    # source ticks
    out: int
    media: str


@dataclass(frozen=True)
class SourceWord:
    text: str
    start_ms: int
    end_ms: int
    cue: int  # index of the engine's phrase cue that holds it


@dataclass(frozen=True)
class TimelineWord:
    text: str
    start: int  # sequence ticks
    end: int
    clip: str
    media: str
    src_start_ms: int
    src_end_ms: int
    cue: int
    clipped: str | None  # "head" / "tail" / "both": the clip edge cuts this word


def _ticks(value) -> int:
    return int(value)


def audio_clips(timeline: dict, track: str | None = None) -> tuple[str, list[Clip], list[dict]]:
    """(track id, clips to map, skipped clips with reasons) for one audio track of a
    `read_timeline` result: ``track`` ("A2"), or the first un-muted audio track with clips."""
    tracks = [t for t in timeline.get("tracks", []) if t.get("kind") == "audio"]
    if not tracks:
        raise ValueError("the sequence has no audio tracks")
    if track is not None:
        chosen = next((t for t in tracks if t["id"] == track), None)
        if chosen is None:
            raise ValueError(f"no audio track {track}; the sequence has {', '.join(t['id'] for t in tracks)}")
    else:
        with_clips = [t for t in tracks if t.get("clips")]
        chosen = next((t for t in with_clips if not t.get("muted")), None)
        if chosen is None:
            raise ValueError("no un-muted audio track has clips; pass track, e.g. \"A1\"")
    clips, skipped = [], []
    for c in chosen.get("clips", []):
        reason = None
        if c.get("disabled"):
            reason = "disabled"
        elif not c.get("media"):
            reason = "no media file (nested sequence?)"
        elif c.get("speed", 1) != 1 or c.get("reversed"):
            reason = f"speed {c.get('speed')}{' reversed' if c.get('reversed') else ''}: only 100% forward is mapped"
        if reason:
            skipped.append({"clip": c["id"], "reason": reason})
            continue
        clips.append(Clip(c["id"], _ticks(c["start_ticks"]), _ticks(c["end_ticks"]),
                          _ticks(c["in_ticks"]), _ticks(c["out_ticks"]), c["media"]))
    clips.sort(key=lambda c: c.start)
    return chosen["id"], clips, skipped


def source_word_list(words: Iterable, cues: Iterable) -> list[SourceWord]:
    """Engine words (``.text/.start_ms/.end_ms``) tagged with the phrase cue holding their
    midpoint; with no word timeline, each cue is one word."""
    cues = sorted(cues, key=lambda c: (c["start_ms"], c["end_ms"]))
    starts = [c["start_ms"] for c in cues]
    out = []
    words = list(words)
    if not words:
        return [SourceWord(c["text"], c["start_ms"], c["end_ms"], i) for i, c in enumerate(cues)]
    for w in sorted(words, key=lambda w: (w.start_ms, w.end_ms)):
        mid = (w.start_ms + w.end_ms) / 2
        i = max(bisect.bisect_right(starts, mid) - 1, 0) if cues else 0
        out.append(SourceWord(w.text, w.start_ms, w.end_ms, i))
    return out


def project(clips: list[Clip], words_by_media: dict[str, list[SourceWord]],
            tolerance_ms: int = CLIP_TOLERANCE_MS) -> list[TimelineWord]:
    """Every source word each clip plays, on the sequence, in sequence order."""
    out = []
    starts_by_media = {m: [w.start_ms for w in ws] for m, ws in words_by_media.items()}
    for clip in clips:
        words = words_by_media.get(clip.media) or []
        starts = starts_by_media.get(clip.media) or []
        in_ms, out_ms = clip.in_ / TICKS_PER_MS, clip.out / TICKS_PER_MS
        # Words are sorted by start; one that starts before In can still reach into the clip.
        i = bisect.bisect_left(starts, in_ms - 30000)
        for w in words[i:]:
            if w.start_ms >= out_ms:
                break
            lo, hi = max(w.start_ms * TICKS_PER_MS, clip.in_), min(w.end_ms * TICKS_PER_MS, clip.out)
            # The engine reports some short words with start == end: keep one that falls inside.
            if hi < lo or (hi == lo and (w.end_ms > w.start_ms or not clip.in_ <= lo < clip.out)):
                continue
            head = w.start_ms < in_ms - tolerance_ms
            tail = w.end_ms > out_ms + tolerance_ms
            out.append(TimelineWord(
                w.text, clip.start + lo - clip.in_, clip.start + hi - clip.in_, clip.id,
                clip.media, w.start_ms, w.end_ms, w.cue,
                "both" if head and tail else "head" if head else "tail" if tail else None))
    out.sort(key=lambda w: (w.start, w.end))
    return out


def _thai(ch: str) -> bool:
    return "฀" <= ch <= "๿"


def join_words(texts: Iterable[str]) -> str:
    """Thai joins without spaces; every other join gets one, as the pipeline's script-boundary
    spacing writes cues (transcribe/pipeline/normalize.py)."""
    out = ""
    for t in texts:
        t = t.strip()
        if out and t and not (_thai(out[-1]) and _thai(t[0])):
            out += " "
        out += t
    return out


def seconds(ticks: int) -> float:
    return round(ticks / PPRO_TICKS_PER_SECOND, 3)


def timecode(ticks: int, ticks_per_frame: int) -> str:
    frames = ticks // ticks_per_frame
    fps = round(PPRO_TICKS_PER_SECOND / ticks_per_frame)
    s, f = divmod(frames, fps)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02}:{m:02}:{s:02}:{f:02}"


def lines(words: list[TimelineWord], ticks_per_frame: int) -> list[dict]:
    """The engine's phrase cues as the timeline plays them: consecutive words of one cue in
    one clip. A cue a cut runs through becomes two lines, and a cut-away part is gone."""
    out, group = [], []

    def flush():
        if not group:
            return
        first, last = group[0], group[-1]
        line = {"tc": timecode(first.start, ticks_per_frame), "start_s": seconds(first.start),
                "end_s": seconds(last.end), "start_ticks": str(first.start), "end_ticks": str(last.end),
                "text": join_words(w.text for w in group), "clip": first.clip,
                "src_s": [round(first.src_start_ms / 1000, 3), round(last.src_end_ms / 1000, 3)]}
        cut = [w.text for w in group if w.clipped]
        if cut:
            line["clipped_words"] = cut
        out.append(line)
        group.clear()

    for w in words:
        if group and (w.clip != group[-1].clip or w.cue != group[-1].cue):
            flush()
        group.append(w)
    flush()
    return out


def _nearest_quiet_ms(levels, threshold: float, edge_ms: float, reach_ms: int = 400) -> int | None:
    """Signed offset (ms, negative = earlier in the source) to the nearest quiet 10 ms window."""
    i = int(edge_ms // ENVELOPE_MS)
    for step in range(reach_ms // ENVELOPE_MS + 1):
        for j in (i - step, i + step):
            if 0 <= j < len(levels) and levels[j] < threshold:
                return round((j + 0.5) * ENVELOPE_MS - edge_ms)
    return None


def edges(clips: list[Clip], words_by_media: dict[str, list[SourceWord]], ticks_per_frame: int,
          tolerance_ms: int = CLIP_TOLERANCE_MS, levels_by_media: dict | None = None) -> list[dict]:
    """Every clip In and Out that cuts through a word: where it is on the sequence, the word,
    and how much of it the cut removes. An empty list means every edit sits between words.

    With the source's level envelope, an edge counts only where the audio at the cut (20 ms
    either side) is audible: an engine word often spans a pause, and a cut in that pause cuts
    no sound. Each such edge also gets ``nearest_quiet_ms``, the shift to the nearest quiet spot."""
    out = []
    levels_by_media = levels_by_media or {}
    starts_by_media = {m: [w.start_ms for w in ws] for m, ws in words_by_media.items()}
    for clip in clips:
        words = words_by_media.get(clip.media) or []
        starts = starts_by_media.get(clip.media) or []
        levels = levels_by_media.get(clip.media)
        threshold = noise_floor(levels) + TAIL_DB if levels is not None else None
        for side, edge_ticks, seq_ticks in (("in", clip.in_, clip.start), ("out", clip.out, clip.end)):
            edge_ms = edge_ticks / TICKS_PER_MS
            if levels is not None:
                i = int(edge_ms // ENVELOPE_MS)
                near = levels[max(i - 2, 0):i + 2]
                if not len(near) or float(near.max()) < threshold:
                    continue
            # No engine word is 30 s long; start there instead of at the top of the file.
            for w in words[bisect.bisect_left(starts, edge_ms - 30000):]:
                if w.start_ms > edge_ms:
                    break
                if w.start_ms + tolerance_ms < edge_ms < w.end_ms - tolerance_ms:
                    removed = edge_ms - w.start_ms if side == "in" else w.end_ms - edge_ms
                    edge = {"clip": clip.id, "side": side, "tc": timecode(seq_ticks, ticks_per_frame),
                            "at_s": seconds(seq_ticks), "word": w.text,
                            "word_src_s": [w.start_ms / 1000, w.end_ms / 1000],
                            "edge_src_s": round(edge_ms / 1000, 3), "cut_ms": round(removed)}
                    if levels is not None:
                        edge["nearest_quiet_ms"] = _nearest_quiet_ms(levels, threshold, edge_ms)
                    out.append(edge)
    return out


def _norm(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFC", text).lower()
                   if not ch.isspace() and not unicodedata.category(ch).startswith("P"))


def find(words: list[TimelineWord], query: str, ticks_per_frame: int, limit: int = 20) -> list[dict]:
    """Where a phrase is said on the timeline: the first to last word that spells it, ignoring
    spaces and punctuation. Spans that run across a cut are found too (``clips`` lists them)."""
    needle = _norm(query)
    if not needle:
        raise ValueError("query must have letters")
    text, owner = "", []
    for i, w in enumerate(words):
        piece = _norm(w.text)
        text += piece
        owner += [i] * len(piece)
    found, pos = [], text.find(needle)
    while pos >= 0 and len(found) < limit:
        a, b = words[owner[pos]], words[owner[pos + len(needle) - 1]]
        span = words[owner[pos]:owner[pos + len(needle) - 1] + 1]
        found.append({"tc": timecode(a.start, ticks_per_frame), "start_s": seconds(a.start),
                      "end_s": seconds(b.end), "start_ticks": str(a.start), "end_ticks": str(b.end),
                      "text": join_words(w.text for w in span),
                      "clips": list(dict.fromkeys(w.clip for w in span))})
        pos = text.find(needle, pos + len(needle))
    return found


# ── word times, checked against the audio ───────────────────────────────────
# The engine's Thai word times are loose: a word's span often runs hundreds of ms into the
# pause around it (measured on a rough cut, 2026-11-22: 105 of 238 silence-cut edges fell
# "inside" a word, and in 74 of them the part cut off was below -45 dB). Each word is tightened
# to the audible sound inside it, judged as the Rough Cut's sound guard judges sound.

ENVELOPE_MS = 10
_FLOOR_MIN_DB, _FLOOR_MAX_DB = -65.0, -35.0  # as ingest.sound_runs: digital silence is not the floor
TAIL_DB = 6.0  # a 10 ms window this far above the floor is sound (ingest.sound_runs' tail rule)


def level_db(audio, sample_rate: int):
    """Level of each 10 ms window in dB (float32 array)."""
    import numpy as np
    window = sample_rate * ENVELOPE_MS // 1000
    n = len(audio) // window
    frames = audio[:n * window].reshape(n, window).astype(np.float64)
    return (20.0 * np.log10(np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-9)).astype(np.float32)


def noise_floor(levels) -> float:
    import numpy as np
    return float(np.clip(np.percentile(levels, 5), _FLOOR_MIN_DB, _FLOOR_MAX_DB)) if len(levels) else _FLOOR_MIN_DB


def tighten(words: list[SourceWord], levels, tail_db: float = TAIL_DB) -> list[SourceWord]:
    """Each word's start and end pulled in to the first and last audible 10 ms window inside it.
    Never widens a word; a word with no audible window inside keeps the engine's times."""
    threshold = noise_floor(levels) + tail_db
    out = []
    for w in words:
        i0, i1 = w.start_ms // ENVELOPE_MS, -(-w.end_ms // ENVELOPE_MS)
        loud = [i for i in range(i0, min(i1, len(levels))) if levels[i] >= threshold]
        if w.end_ms <= w.start_ms or not loud:
            out.append(w)
            continue
        out.append(SourceWord(w.text, max(w.start_ms, loud[0] * ENVELOPE_MS),
                              min(w.end_ms, (loud[-1] + 1) * ENVELOPE_MS), w.cue))
    return out


def source_levels(media: str, cache: Path, sample_rate: int = 16000):
    """The 10 ms level envelope of a source file's audio, decoded once (streamed, so a long
    file never sits in memory) and kept as ``cache`` (.npy)."""
    import shutil
    import subprocess

    import numpy as np
    if cache.is_file():
        return np.load(cache)
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH")
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", media, "-vn",
           "-af", "aresample=ochl=mono:rematrix_maxval=1.0", "-ar", str(sample_rate), "-f", "f32le", "pipe:1"]
    window_bytes = sample_rate * ENVELOPE_MS // 1000 * 4
    chunks = []
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {})) as proc:
        while True:
            block = proc.stdout.read(window_bytes * 6000)  # one minute
            if not block:
                break
            usable = len(block) - len(block) % window_bytes
            chunks.append(level_db(np.frombuffer(block[:usable], dtype=np.float32), sample_rate))
    if proc.returncode:
        raise RuntimeError(f"ffmpeg could not decode the audio of {media}")
    levels = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache, levels)
    return levels


# ── sources: the store ───────────────────────────────────────────────────────

def _sha_index_path(db_path: Path) -> Path:
    return db_path.with_name(db_path.name + ".sha256-index.json")


def media_sha256(path: str, db_path: Path) -> str:
    """sha256 of a source file, remembered by (path, size, mtime) so a 7 GB camera file is
    hashed once, not on every timeline read."""
    from transcribe.db import store
    st = os.stat(path)
    key = f"{os.path.abspath(path)}|{st.st_size}|{st.st_mtime_ns}"
    index_path = _sha_index_path(db_path)
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = {}
    if key not in index:
        index[key] = store.sha256_of_file(path)
        tmp = index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(index, indent=0), encoding="utf-8")
        os.replace(tmp, index_path)
    return index[key]


def source_words(media: str, db_path: Path, levels_dir: Path | None = None) -> tuple[int, list[SourceWord], object] | None:
    """(transcript job id, word timeline, level envelope or None) of the newest finished transcript of this file, or
    None when it has never been transcribed. With ``levels_dir``, word times are tightened to
    the audio (`tighten`); the file's level envelope is cached there by sha256."""
    from cutdeck.words import words_for_job
    from transcribe.db import store
    sha = media_sha256(media, db_path)
    conn = store.connect(db_path)
    try:
        job = store.latest_transcript_job(conn, sha)
        if job is None:
            return None
        cues = [{"text": t.text, "start_ms": t.start_ms, "end_ms": t.end_ms}
                for t in store.get_tokens(conn, job.id)]
        words = source_word_list(words_for_job(conn, job.id), cues)
    finally:
        conn.close()
    levels = None
    if levels_dir is not None:
        levels = source_levels(media, levels_dir / f"{sha}.npy")
        words = tighten(words, levels)
    return job.id, words, levels


def build(timeline: dict, *, track: str | None = None, query: str | None = None,
          from_ticks: int | None = None, to_ticks: int | None = None, offset: int = 0,
          limit: int = 200, db_path: Path | None = None, out_dir: Path | None = None,
          tighten_words: bool = True,
          lookup: Callable[[str], tuple | None] | None = None) -> dict:
    """The timeline transcript of one audio track of a `read_timeline` result."""
    if lookup is None:
        import yaml
        from transcribe.db import store
        root = Path(__file__).resolve().parent.parent
        config = yaml.safe_load((root / "transcribe/config.yaml").read_text(encoding="utf-8"))
        db = Path(db_path) if db_path else store.resolve_db_path(config)
        levels_dir = (out_dir / "levels") if out_dir is not None and tighten_words else None
        lookup = lambda media: source_words(media, db, levels_dir)  # noqa: E731
    tpf = int(timeline["ticks_per_frame"])
    track_id, clips, skipped = audio_clips(timeline, track)
    words_by_media, levels_by_media, jobs, missing = {}, {}, {}, []
    for media in dict.fromkeys(c.media for c in clips):
        if not Path(media).is_file():
            missing.append({"media": media, "reason": "file is missing or offline"})
            continue
        found = lookup(media)
        if found is None:
            missing.append({"media": media, "reason": "not transcribed yet: run transcribe(media_path), "
                                                      "then call this again (no re-listening after that)"})
            continue
        jobs[media], words_by_media[media] = found[0], found[1]
        if len(found) > 2 and found[2] is not None:
            levels_by_media[media] = found[2]
    words = project(clips, words_by_media)
    all_lines = lines(words, tpf)
    result = {"sequence": timeline.get("name"), "sequence_id": timeline.get("sequence_id"),
              "track": track_id, "clips": len(clips), "skipped": skipped, "missing": missing,
              "sources": [{"media": m, "transcript_job_id": j} for m, j in jobs.items()],
              "words": len(words), "edges_inside_words": edges(clips, words_by_media, tpf, levels_by_media=levels_by_media)}
    if query:
        result["matches"] = find(words, query, tpf)
    if from_ticks is not None or to_ticks is not None:
        lo = from_ticks if from_ticks is not None else 0
        hi = to_ticks if to_ticks is not None else 1 << 62
        all_lines = [ln for ln in all_lines if int(ln["end_ticks"]) > lo and int(ln["start_ticks"]) < hi]
    result["line_count"] = len(all_lines)
    result["lines"] = all_lines[offset:offset + limit]
    result["next_offset"] = offset + limit if offset + limit < len(all_lines) else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w.-]+", "_", str(timeline.get("name") or "sequence"))[:60]
        path = out_dir / f"{safe}-{track_id}.json"
        path.write_text(json.dumps({**result, "lines": all_lines, "next_offset": None,
                                    "word_list": [w.__dict__ for w in words]}, ensure_ascii=False),
                        encoding="utf-8")
        result["full_path"] = str(path)
    return result
