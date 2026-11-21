"""What the timeline says, without listening to it again.

A cut timeline is a list of pieces of source files. Each source file is transcribed once
(`transcribe(media_path)`, cached by sha256 in the shared store) and its word timeline is
mapped through the clip list onto the sequence, in exact Premiere ticks. A copy, a re-cut or a
reorder of the same footage needs no new transcription: only this mapping runs again.

Mapping, for a clip at sequence ``start`` playing source ``[in, out)`` at ``speed``:
``sequence_ticks = start + (source_ticks - in) / speed``. A word the clip's In or Out cuts through is
kept with ``clipped`` set, and the edge is reported in ``edges``: that is a cut inside speech.

Pure apart from `source_words` (reads the store) and `build` (the helper entry point).
"""
from __future__ import annotations

import bisect
import json
import os
import re
import unicodedata
from dataclasses import dataclass, replace
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
    speed: float = 1.0  # forward playback rate; the clip plays (out - in) / speed of sequence time


@dataclass(frozen=True)
class SourceWord:
    text: str
    start_ms: int
    end_ms: int
    cue: int  # index of the engine's phrase cue that holds it
    corrected: bool = False  # text from a person's correction of the cue, not the engine


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
    corrected: bool = False


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
        elif c.get("reversed") or not c.get("speed", 1) > 0:
            reason = f"reversed or speed {c.get('speed')}: only forward playback is mapped"
        if reason:
            skipped.append({"clip": c["id"], "reason": reason})
            continue
        # Premiere reports a speed-changed clip's In/Out divided by its speed (live 2026-11-22:
        # 200% over source 112-122 s reads in 56 s, out 61 s), so the source span is In/Out x speed.
        speed = float(c.get("speed", 1))
        clips.append(Clip(c["id"], _ticks(c["start_ticks"]), _ticks(c["end_ticks"]),
                          round(_ticks(c["in_ticks"]) * speed), round(_ticks(c["out_ticks"]) * speed),
                          c["media"], speed))
    clips.sort(key=lambda c: c.start)
    return chosen["id"], clips, skipped


def source_word_list(words: Iterable, cues: Iterable) -> list[SourceWord]:
    """Engine words (``.text/.start_ms/.end_ms``) tagged with the phrase cue holding their
    midpoint; with no word timeline, each cue is one word."""
    cues = sorted(cues, key=lambda c: (c["start_ms"], c["end_ms"]))
    starts = [c["start_ms"] for c in cues]
    ids = [c.get("idx", i) for i, c in enumerate(cues)]  # the store's token idx when given
    out = []
    words = list(words)
    if not words:
        return [SourceWord(c["text"], c["start_ms"], c["end_ms"], ids[i]) for i, c in enumerate(cues)]
    for w in sorted(words, key=lambda w: (w.start_ms, w.end_ms)):
        mid = (w.start_ms + w.end_ms) / 2
        i = max(bisect.bisect_right(starts, mid) - 1, 0) if cues else 0
        out.append(SourceWord(w.text, w.start_ms, w.end_ms, ids[i] if cues else 0))
    return out


def apply_corrections(words: list[SourceWord], corrected: dict[int, str]) -> list[SourceWord]:
    """A person's corrected text for a cue (``{cue idx: text}``, SubtitleDesk / web editor)
    replaces the engine's words of that cue. The corrected text is split into words
    (pythainlp); with as many words as the engine had, each keeps its engine times, else they
    share the cue's span by character count. A cue the engine gave no words is left alone."""
    if not corrected:
        return words
    from pythainlp.tokenize import word_tokenize
    out, k = [], 0
    while k < len(words):
        w = words[k]
        if w.cue not in corrected:
            out.append(w)
            k += 1
            continue
        group = [w]
        while k + len(group) < len(words) and words[k + len(group)].cue == w.cue:
            group.append(words[k + len(group)])
        k += len(group)
        tokens = [t for t in word_tokenize(corrected[w.cue], keep_whitespace=False) if t.strip()]
        if not tokens:
            continue  # corrected to nothing: the cue was a hallucination
        if len(tokens) == len(group):
            out += [replace(g, text=t, corrected=True) for g, t in zip(group, tokens)]
            continue
        lo, hi = group[0].start_ms, max(g.end_ms for g in group)
        total, pos = sum(len(t) for t in tokens), 0
        for t in tokens:
            a = lo + (hi - lo) * pos // total
            pos += len(t)
            out.append(SourceWord(t, a, lo + (hi - lo) * pos // total, w.cue, True))
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
                w.text, clip.start + round((lo - clip.in_) / clip.speed),
                clip.start + round((hi - clip.in_) / clip.speed), clip.id,
                clip.media, w.start_ms, w.end_ms, w.cue,
                "both" if head and tail else "head" if head else "tail" if tail else None, w.corrected))
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
        if any(w.corrected for w in group):
            line["corrected"] = True
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


def _audible_at(levels, threshold: float, at_ms: float) -> bool:
    """Is any 10 ms window within 20 ms of ``at_ms`` sound?"""
    i = int(at_ms // ENVELOPE_MS)
    near = levels[max(i - 2, 0):i + 2]
    return bool(len(near)) and float(near.max()) >= threshold


def edges(clips: list[Clip], words_by_media: dict[str, list[SourceWord]], ticks_per_frame: int,
          tolerance_ms: int = CLIP_TOLERANCE_MS, levels_by_media: dict | None = None) -> list[dict]:
    """Clip Ins and Outs that cut into sound: where each is on the sequence, the word it cuts
    (None: sound no word covers, e.g. an onset the engine timed late, a laugh, music), how much
    of the word is lost, and ``nearest_quiet_ms``, the shift to the nearest quiet spot.

    With the source's level envelope the audio decides: every edge with sound within 20 ms of
    the cut is listed, whether or not an engine word covers it (an engine word often spans a
    pause, and a word the engine starts late leaves its onset uncovered). Without one, an edge
    is listed when it falls more than ``tolerance_ms`` inside an engine word."""
    out = []
    levels_by_media = levels_by_media or {}
    starts_by_media = {m: [w.start_ms for w in ws] for m, ws in words_by_media.items()}
    thresholds = {m: noise_floor(lv) + TAIL_DB for m, lv in levels_by_media.items()}
    for clip in clips:
        words = words_by_media.get(clip.media) or []
        starts = starts_by_media.get(clip.media) or []
        levels = levels_by_media.get(clip.media)
        threshold = thresholds.get(clip.media)
        for side, edge_ticks, seq_ticks in (("in", clip.in_, clip.start), ("out", clip.out, clip.end)):
            edge_ms = edge_ticks / TICKS_PER_MS
            if levels is not None and not _audible_at(levels, threshold, edge_ms):
                continue
            word = None
            # No engine word is 30 s long; start there instead of at the top of the file.
            for w in words[bisect.bisect_left(starts, edge_ms - 30000):]:
                if w.start_ms > edge_ms:
                    break
                if w.start_ms + tolerance_ms < edge_ms < w.end_ms - tolerance_ms:
                    word = w
            if word is None and levels is None:
                continue
            edge = {"clip": clip.id, "side": side, "tc": timecode(seq_ticks, ticks_per_frame),
                    "at_s": seconds(seq_ticks), "edge_src_s": round(edge_ms / 1000, 3),
                    "word": word.text if word else None}
            if word:
                edge["word_src_s"] = [word.start_ms / 1000, word.end_ms / 1000]
                edge["cut_ms"] = round(edge_ms - word.start_ms if side == "in" else word.end_ms - edge_ms)
            if levels is not None:
                quiet = _nearest_quiet_ms(levels, threshold, edge_ms)
                edge["nearest_quiet_ms"] = quiet
                # "tail": quiet within one 10 ms window, the faint end of a fade; "sound": the cut
                # is in it. Both are listed; only "sound" is clearly audible as a clip.
                edge["severity"] = "tail" if quiet is not None and abs(quiet) <= TAIL_MS else "sound"
            out.append(edge)
    return out


def level_at(clips: list[Clip], levels_by_media: dict, ticks: int,
             thresholds: dict | None = None) -> float | None:
    """The loudest 10 ms source level within 20 ms of a sequence position, and how far above
    the source's floor it is, as dB over threshold (negative = quiet). None: no levels there;
    a position no clip covers plays nothing, so it is quiet (-inf)."""
    for clip in clips:
        if clip.start <= ticks < clip.end:
            levels = levels_by_media.get(clip.media)
            if levels is None:
                return None
            src_ms = (clip.in_ + (ticks - clip.start) * clip.speed) / TICKS_PER_MS
            i = int(src_ms // ENVELOPE_MS)
            near = levels[max(i - 2, 0):i + 2]
            if not len(near):
                return float("-inf")
            threshold = (thresholds or {}).get(clip.media)
            return float(near.max()) - (threshold if threshold is not None else noise_floor(levels) + TAIL_DB)
    return float("-inf")


def later_stream_clips(timeline: dict, track_id: str) -> list[str]:
    """Clips on ``track_id`` that look like a later audio stream of their file: a lower audio
    track plays the same file over the same source span at the same place. Premiere lays each
    stream of a multi-stream file on its own track (live 2026-11-22: a 4-stream OBS file landed on
    A1-A4), while the transcript and levels are of the file's first stream."""
    tracks = [t for t in timeline.get("tracks", []) if t.get("kind") == "audio"]
    ids = [t["id"] for t in tracks]
    if track_id not in ids:
        return []
    lower = {(c.get("media"), c["start_ticks"], c["in_ticks"], c["out_ticks"])
             for t in tracks[:ids.index(track_id)] for c in t.get("clips", [])}
    return [c["id"] for c in tracks[ids.index(track_id)].get("clips", [])
            if (c.get("media"), c["start_ticks"], c["in_ticks"], c["out_ticks"]) in lower]


def spans_on_timeline(clips: list[Clip], spans_by_media: dict[str, list[tuple[int, int]]],
                      ticks_per_frame: int) -> list[dict]:
    """Source spans (ms) where each clip plays them, cut to the clip, in sequence order."""
    out = []
    for clip in clips:
        for a, b in spans_by_media.get(clip.media) or []:
            lo, hi = max(a * TICKS_PER_MS, clip.in_), min(b * TICKS_PER_MS, clip.out)
            if hi <= lo:
                continue
            start = clip.start + round((lo - clip.in_) / clip.speed)
            end = clip.start + round((hi - clip.in_) / clip.speed)
            out.append({"tc": timecode(start, ticks_per_frame), "start_s": seconds(start), "end_s": seconds(end),
                        "start_ticks": str(start), "end_ticks": str(end), "clip": clip.id,
                        "src_s": [a / 1000, b / 1000]})
    out.sort(key=lambda x: int(x["start_ticks"]))
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
    text, owner, starts, ends = "", [], set(), set()
    for i, w in enumerate(words):
        piece = _norm(w.text)
        starts.add(len(text))
        text += piece
        ends.add(len(text))
        owner += [i] * len(piece)
    found, pos = [], text.find(needle)
    while pos >= 0 and len(found) < limit:
        a, b = words[owner[pos]], words[owner[pos + len(needle) - 1]]
        span = words[owner[pos]:owner[pos + len(needle) - 1] + 1]
        found.append({"tc": timecode(a.start, ticks_per_frame), "start_s": seconds(a.start),
                      "end_s": seconds(b.end), "start_ticks": str(a.start), "end_ticks": str(b.end),
                      "text": join_words(w.text for w in span),
                      "clips": list(dict.fromkeys(w.clip for w in span)),
                      # False: the phrase starts or ends inside a longer word
                      "whole_words": pos in starts and pos + len(needle) in ends})
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
TAIL_MS = 10   # a cut this close to quiet sits on the faint end of a fade


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


REACH_MS = 400  # how far a word edge may grow into a pause to meet sound the engine left out


def tighten(words: list[SourceWord], levels, tail_db: float = TAIL_DB) -> list[SourceWord]:
    """Fit each word's edges to the sound. First pulled in to the first and last audible 10 ms
    window inside the engine's span; then an edge that borders a pause is grown out through
    continuous sound (at most ``REACH_MS``, never into a neighbouring word): on a 96-min
    source, a quarter of words after a pause started 100+ ms after their sound began, and as
    many ended early (2026-11-22). A word with no audible window keeps the engine's times."""
    threshold = noise_floor(levels) + tail_db
    n = len(levels)
    audible = lambda i: 0 <= i < n and levels[i] >= threshold  # noqa: E731
    inner = []
    for w in words:
        i0, i1 = w.start_ms // ENVELOPE_MS, -(-w.end_ms // ENVELOPE_MS)
        loud = [i for i in range(i0, min(i1, n)) if levels[i] >= threshold]
        if w.end_ms <= w.start_ms or not loud:
            inner.append((w, False))
            continue
        inner.append((replace(w, start_ms=max(w.start_ms, loud[0] * ENVELOPE_MS),
                              end_ms=min(w.end_ms, (loud[-1] + 1) * ENVELOPE_MS)), True))
    out = []
    reach = REACH_MS // ENVELOPE_MS
    for k, (w, fitted) in enumerate(inner):
        if not fitted:
            out.append(w)
            continue
        floor_ms = out[-1].end_ms if out else 0
        ceil_ms = inner[k + 1][0].start_ms if k + 1 < len(inner) else n * ENVELOPE_MS
        i = w.start_ms // ENVELOPE_MS
        steps = 0
        while steps < reach and audible(i - 1) and (i - 1) * ENVELOPE_MS >= floor_ms:
            i -= 1
            steps += 1
        j = w.end_ms // ENVELOPE_MS  # first window after the word
        steps = 0
        while steps < reach and audible(j) and (j + 1) * ENVELOPE_MS <= ceil_ms:
            j += 1
            steps += 1
        out.append(replace(w, start_ms=i * ENVELOPE_MS, end_ms=j * ENVELOPE_MS))
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


def audio_stream_count(media: str) -> int | None:
    """How many audio streams the file has (ffprobe), or None when ffprobe can't say. The
    transcript and levels read the first one, as the Rough Cut does; UXP does not say which
    stream a Premiere clip plays."""
    import shutil
    import subprocess
    if shutil.which("ffprobe") is None:
        return None
    result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                             "stream=index", "-of", "csv=p=0", media], capture_output=True, text=True,
                            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    return len(result.stdout.split()) if result.returncode == 0 else None


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


def source_words(media: str, db_path: Path, levels_dir: Path | None = None) -> tuple[int, list[SourceWord], object, list] | None:
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
        cues = [{"idx": t.idx, "text": t.text, "start_ms": t.start_ms, "end_ms": t.end_ms}
                for t in store.get_tokens(conn, job.id)]
        words = source_word_list(words_for_job(conn, job.id), cues)
        words = apply_corrections(words, {c.token_idx: c.corrected_text
                                          for c in store.get_corrections(conn, job.id)})
        # Speech the VAD heard that no cue covers: the engine dropped it (transcribe.service's
        # coverage_gaps). On the timeline an agent would otherwise read it as a pause.
        from transcribe.pipeline import coverage
        speech = [(sp.start_ms, sp.end_ms) for sp in store.get_speech_spans(conn, job.id) if sp.kind == "speech"]
        gaps = [(g.start_ms, g.end_ms) for g in coverage.find_gaps(speech, cues)]
    finally:
        conn.close()
    levels = None
    if levels_dir is not None:
        levels = source_levels(media, levels_dir / f"{sha}.npy")
        words = tighten(words, levels)
    return job.id, words, levels, gaps


def _source_entry(media: str, job_id: int, probe_streams: bool) -> dict:
    entry = {"media": media, "transcript_job_id": job_id}
    streams = audio_stream_count(media) if probe_streams else None
    if streams and streams > 1:
        entry["audio_streams"] = streams
        entry["note"] = ("several audio streams: the transcript is of the first; if this track "
                         "plays another stream, its words may not be what is heard")
    return entry


def build(timeline: dict, *, track: str | None = None, query: str | None = None,
          from_ticks: int | None = None, to_ticks: int | None = None, offset: int = 0,
          limit: int = 200, db_path: Path | None = None, out_dir: Path | None = None,
          tighten_words: bool = True, keep_words: bool = False,
          lookup: Callable[[str], tuple | None] | None = None) -> dict:
    """The timeline transcript of one audio track of a `read_timeline` result."""
    probe_streams = lookup is None
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
    words_by_media, levels_by_media, gaps_by_media, jobs, missing = {}, {}, {}, {}, []
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
        if len(found) > 3:
            gaps_by_media[media] = found[3]
    words = project(clips, words_by_media)
    all_lines = lines(words, tpf)
    result = {"sequence": timeline.get("name"), "sequence_id": timeline.get("sequence_id"),
              "track": track_id, "clips": len(clips), "skipped": skipped, "missing": missing,
              "sources": [_source_entry(m, j, probe_streams) for m, j in jobs.items()],
              "words": len(words), "cuts_in_sound": edges(clips, words_by_media, tpf, levels_by_media=levels_by_media)}
    if query:
        result["matches"] = find(words, query, tpf)
    result["untranscribed"] = spans_on_timeline(clips, gaps_by_media, tpf)
    later = later_stream_clips(timeline, track_id)
    if later:
        result["warnings"] = [f"{len(later)} clip(s) on {track_id} look like a later audio stream of their file "
                              f"(a lower track plays the same file at the same place, e.g. {later[0]}); the "
                              "transcript is of the first stream, so if the streams differ these words are not "
                              "what this track plays"]
    if from_ticks is not None or to_ticks is not None:
        lo = from_ticks if from_ticks is not None else 0
        hi = to_ticks if to_ticks is not None else 1 << 62
        inside = lambda a, b: b > lo and a < hi  # noqa: E731
        all_lines = [ln for ln in all_lines if inside(int(ln["start_ticks"]), int(ln["end_ticks"]))]
        result["untranscribed"] = [u for u in result["untranscribed"]
                                   if inside(int(u["start_ticks"]), int(u["end_ticks"]))]
        result["cuts_in_sound"] = [e for e in result["cuts_in_sound"]
                                   if lo <= round(e["at_s"] * PPRO_TICKS_PER_SECOND) < hi]
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
    if keep_words:  # for in-process callers (word_cut); not JSON
        result["word_objects"] = words
        thresholds = {m: noise_floor(lv) + TAIL_DB for m, lv in levels_by_media.items()}
        result["level_at"] = lambda ticks: level_at(clips, levels_by_media, ticks, thresholds)
        result["source_words"] = words_by_media

        def source_level(media, ticks):
            levels = levels_by_media.get(media)
            if levels is None:
                return None
            i = int(ticks / TICKS_PER_MS // ENVELOPE_MS)
            near = levels[max(i - 2, 0):i + 2]
            return float(near.max()) - thresholds[media] if len(near) else float("-inf")
        result["source_level"] = source_level
    return result
