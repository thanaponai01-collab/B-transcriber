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
from transcribe.audio import levels as lv

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
    start_by: str | None = None  # how the edge was placed (EDGE_HOW); None: not known
    end_by: str | None = None
    start_err_ms: int | None = None  # the edge's error bar (edge_bar); None: not known
    end_err_ms: int | None = None


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
    start_err_ms: int | None = None  # source error bar over the clip's speed: sequence ms
    end_err_ms: int | None = None
    start_by: str | None = None
    end_by: str | None = None


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
            bar = lambda ms: None if ms is None else round(ms / clip.speed)  # noqa: E731
            out.append(TimelineWord(
                w.text, clip.start + round((lo - clip.in_) / clip.speed),
                clip.start + round((hi - clip.in_) / clip.speed), clip.id,
                clip.media, w.start_ms, w.end_ms, w.cue,
                "both" if head and tail else "head" if head else "tail" if tail else None, w.corrected,
                bar(w.start_err_ms), bar(w.end_err_ms), w.start_by, w.end_by))
    out.sort(key=lambda w: (w.start, w.end))
    return out


def _thai(ch: str) -> bool:
    return "฀" <= ch <= "๿"


_CLITICS = {"'s", "'ve", "'re", "'ll", "'d", "'m", "'t", "n't", "’s", "’ve", "’re", "’ll", "’d", "’m", "n’t"}


def join_words(texts: Iterable[str]) -> str:
    """Thai joins without spaces; every other join gets one, as the pipeline's script-boundary
    spacing writes cues (transcribe/pipeline/normalize.py)."""
    out = ""
    for t in texts:
        t = t.strip()
        # No space between two Thai runs, before punctuation or a clitic ("'ve", "n't"), or after
        # an opening bracket.
        if out and t and not (_thai(out[-1]) and _thai(t[0])) and t[0] not in ".,!?;:%)]}"                 and t.lower() not in _CLITICS and out[-1] not in "([{":
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
        if first.start_err_ms is not None:
            line["start_err_ms"] = first.start_err_ms
        if last.end_err_ms is not None:
            line["end_err_ms"] = last.end_err_ms
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


def _nearest_quiet_ms(over, edge_ms: float, reach_ms: int = 400) -> int | None:
    """Signed offset (ms, negative = earlier in the source) to the nearest quiet 10 ms window
    (``over``: dB over the sound line, ``levels.over``)."""
    i = int(edge_ms // ENVELOPE_MS)
    for step in range(reach_ms // ENVELOPE_MS + 1):
        for j in (i - step, i + step):
            if 0 <= j < len(over) and over[j] < 0:
                return round((j + 0.5) * ENVELOPE_MS - edge_ms)
    return None


def _audible_at(over, at_ms: float) -> bool:
    """Is any 10 ms window within 20 ms of ``at_ms`` sound?"""
    i = int(at_ms // ENVELOPE_MS)
    near = over[max(i - 2, 0):i + 2]
    return bool(len(near)) and float(near.max()) >= 0


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
    overs = {m: lv.over(levels, lv.QUIET) for m, levels in levels_by_media.items()}
    # A through-edit (the next clip goes on playing the same source from where this one stops)
    # cuts nothing: neither side of it is an edge.
    through = set()
    for a, b in zip(clips, clips[1:]):
        if a.end == b.start and a.media == b.media and a.out == b.in_ and a.speed == b.speed:
            through |= {(a.id, "out"), (b.id, "in")}
    for clip in clips:
        words = words_by_media.get(clip.media) or []
        starts = starts_by_media.get(clip.media) or []
        over = overs.get(clip.media)
        for side, edge_ticks, seq_ticks in (("in", clip.in_, clip.start), ("out", clip.out, clip.end)):
            if (clip.id, side) in through:
                continue
            edge_ms = edge_ticks / TICKS_PER_MS
            if over is not None and not _audible_at(over, edge_ms):
                continue
            word = None
            # No engine word is 30 s long; start there instead of at the top of the file.
            for w in words[bisect.bisect_left(starts, edge_ms - 30000):]:
                if w.start_ms > edge_ms:
                    break
                if w.start_ms + tolerance_ms < edge_ms < w.end_ms - tolerance_ms:
                    word = w
            if word is None and over is None:
                continue
            edge = {"clip": clip.id, "side": side, "tc": timecode(seq_ticks, ticks_per_frame),
                    "at_s": seconds(seq_ticks), "at_ticks": str(seq_ticks), "edge_src_s": round(edge_ms / 1000, 3),
                    "word": word.text if word else None}
            if word:
                edge["word_src_s"] = [word.start_ms / 1000, word.end_ms / 1000]
                edge["cut_ms"] = round(edge_ms - word.start_ms if side == "in" else word.end_ms - edge_ms)
                err = word.start_err_ms if side == "in" else word.end_err_ms
                if err is not None:
                    edge["cut_err_ms"] = err
            if over is not None:
                quiet = _nearest_quiet_ms(over, edge_ms)
                edge["nearest_quiet_ms"] = quiet
                # "tail": quiet within one 10 ms window, the faint end of a fade; "sound": the cut
                # is in it. Both are listed; only "sound" is clearly audible as a clip.
                edge["severity"] = "tail" if quiet is not None and abs(quiet) <= TAIL_MS else "sound"
            out.append(edge)
    return out


def level_at(clips: list[Clip], levels_by_media: dict, ticks: int,
             overs: dict | None = None) -> float | None:
    """The loudest 10 ms source level within 20 ms of a sequence position, as dB over the
    quiet rule's sound line (negative = quiet; ``overs`` caches ``levels.over`` per media).
    None: no levels there; a position no clip covers plays nothing, so it is quiet (-inf)."""
    for clip in clips:
        if clip.start <= ticks < clip.end:
            levels = levels_by_media.get(clip.media)
            if levels is None:
                return None
            over = (overs or {}).get(clip.media)
            if over is None:
                over = lv.over(levels, lv.QUIET)
            src_ms = (clip.in_ + (ticks - clip.start) * clip.speed) / TICKS_PER_MS
            i = int(src_ms // ENVELOPE_MS)
            near = over[max(i - 2, 0):i + 2]
            return float(near.max()) if len(near) else float("-inf")
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
                      "whole_words": pos in starts and pos + len(needle) in ends,
                      "word_range": [owner[pos], owner[pos + len(needle) - 1]]})
        pos = text.find(needle, pos + len(needle))
    return found


# ── word times, checked against the audio ───────────────────────────────────
# The engine's Thai word times are loose: a word's span often runs hundreds of ms into the
# pause around it (measured on a rough cut, 2026-11-22: 105 of 238 silence-cut edges fell
# "inside" a word, and in 74 of them the part cut off was below -45 dB). Each word is tightened
# to the audible sound inside it, judged as the Rough Cut's sound guard judges sound.

ENVELOPE_MS = lv.ENVELOPE_MS
TAIL_MS = 10   # a cut this close to quiet sits on the faint end of a fade


def level_db(audio, sample_rate: int):
    """Level of each 10 ms window in dB (float32 array)."""
    import numpy as np
    window = sample_rate * ENVELOPE_MS // 1000
    n = len(audio) // window
    frames = audio[:n * window].reshape(n, window).astype(np.float64)
    return (20.0 * np.log10(np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-9)).astype(np.float32)


REACH_MS = 400  # how far a word edge may grow into a pause to meet sound the engine left out


def tighten(words: list[SourceWord], levels, rule: lv.Rule = lv.QUIET) -> list[SourceWord]:
    """Fit each word's edges to the sound. First pulled in to the first and last audible 10 ms
    window inside the engine's span; then an edge that borders a pause is grown out through
    continuous sound (at most ``REACH_MS``, never into a neighbouring word): on a 96-min
    source, a quarter of words after a pause started 100+ ms after their sound began, and as
    many ended early (2026-11-22). A word with no audible window keeps the engine's times."""
    sound = lv.sound(levels, rule)
    n = len(levels)
    audible = lambda i: 0 <= i < n and sound[i]  # noqa: E731
    inner = []
    for w in words:
        i0, i1 = w.start_ms // ENVELOPE_MS, -(-w.end_ms // ENVELOPE_MS)
        loud = [i for i in range(i0, min(i1, n)) if sound[i]]
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
        grew_start = 0
        while grew_start < reach and audible(i - 1) and (i - 1) * ENVELOPE_MS >= floor_ms:
            i -= 1
            grew_start += 1
        j = w.end_ms // ENVELOPE_MS  # the window holding the end
        grew_end = 0
        while grew_end < reach and audible(j) and (j + 1) * ENVELOPE_MS <= ceil_ms:
            j += 1
            grew_end += 1
        # An edge that did not grow keeps its exact time (no rounding to the 10 ms grid).
        out.append(replace(w, start_ms=i * ENVELOPE_MS if grew_start else w.start_ms,
                           end_ms=max(j * ENVELOPE_MS, w.end_ms) if grew_end else w.end_ms))
    return out


# ── how sure each word edge is ──────────────────────────────────────────────
# A word edge's error bar is the 90th percentile of |edge - marked sound edge| for edges placed
# the same way, fitted on the timing judge's tune split (`python tools/timing_options.py
# fit` writes EDGE_BARS; heldout checks the coverage). Placement ("how"): word_align's
# ``start_by``/``end_by`` (snap, ctc, engine), "tightened" (no word_align: engine times through
# `tighten`), "collapsed" (squeezed to under COLLAPSED_MS: its time is not known), "interpolated"
# (a correction's words shared out by character count: never measured, no bar).

EDGE_BARS = Path(__file__).with_name("edge_bars.json")
COLLAPSED_MS = 5
_bars: dict | None = None


def edge_step_db(levels, t_ms: float, kind: str) -> float | None:
    """How sharply the sound changes across an edge: mean level of the 30 ms after it minus the
    30 ms before (a start), or before minus after (an end), in dB on the 10 ms envelope."""
    import numpy as np
    g = int(t_ms // ENVELOPE_MS)
    a, b = levels[max(0, g - 3):max(0, g)], levels[max(0, g):g + 3]
    if not len(a) or not len(b):
        return None
    step = float(np.mean(b) - np.mean(a))
    return step if kind == "start" else -step


def edge_bar(kind: str, how: str | None, step: float | None) -> int | None:
    """The error bar (ms) of an edge placed by ``how`` with energy step ``step`` (EDGE_BARS)."""
    global _bars
    if how is None or how == "interpolated":
        return None
    if _bars is None:
        _bars = json.loads(EDGE_BARS.read_text(encoding="utf-8"))
    groups = _bars["bars"]
    if step is not None:
        band = sum(step > c for c in _bars["step_cuts"])
        if f"{kind}|{how}|{band}" in groups:
            return groups[f"{kind}|{how}|{band}"]
    return groups.get(f"{kind}|{how}", _bars["fallback"])


def placed_words(words: list[SourceWord], raw: list[dict]) -> list[SourceWord]:
    """Each word's ``start_by``/``end_by`` from the stored word_align pieces whose edge it
    shares (a merged Thai word starts on its first piece and ends on its last)."""
    starts = {int(w["start_ms"]): w.get("start_by") for w in raw}
    ends = {int(w["end_ms"]): w.get("end_by") for w in raw}
    return [replace(w, start_by=starts.get(w.start_ms), end_by=ends.get(w.end_ms)) for w in words]


def with_bars(words: list[SourceWord], levels) -> list[SourceWord]:
    out = []
    for w in words:
        collapsed = w.end_ms - w.start_ms < COLLAPSED_MS
        sb = "interpolated" if w.corrected and w.start_by is None else "collapsed" if collapsed else w.start_by
        eb = "interpolated" if w.corrected and w.end_by is None else "collapsed" if collapsed else w.end_by
        step = (lambda t, k: edge_step_db(levels, t, k)) if levels is not None else (lambda t, k: None)  # noqa: E731
        out.append(replace(w, start_by=sb, end_by=eb, start_err_ms=edge_bar("start", sb, step(w.start_ms, "start")),
                           end_err_ms=edge_bar("end", eb, step(w.end_ms, "end"))))
    return out


HOLE_MS = 100  # PAUSE-rule sound with no word for this long is a hole (judge: tune precision 0.87)


def word_holes(words: list[SourceWord], levels, min_ms: int = HOLE_MS) -> list[tuple[int, int]]:
    """Source spans (ms) of sound (levels.PAUSE rule, which skips breaths and room tone) at
    least ``min_ms`` long that no word covers: speech the transcript has no word for. A
    collapsed word covers nothing. On the judge's marked speech: heldout 14 of 14 reported holes
    were speech and 4 of 5 wordless speech runs were found; tune 26 of 30 and 7 of 10."""
    import numpy as np
    sound = lv.sound(levels, lv.PAUSE)
    covered = np.zeros(len(sound), dtype=bool)
    for w in words:
        if w.end_ms - w.start_ms >= COLLAPSED_MS:
            covered[w.start_ms // ENVELOPE_MS:-(-w.end_ms // ENVELOPE_MS)] = True
    hole = np.concatenate(([0], (sound & ~covered).astype(np.int8), [0]))
    edges_ = np.flatnonzero(np.diff(hole))
    return [(int(a) * ENVELOPE_MS, int(b) * ENVELOPE_MS) for a, b in zip(edges_[::2], edges_[1::2])
            if (b - a) * ENVELOPE_MS >= min_ms]


def source_levels(media: str, cache: Path, sample_rate: int = 16000):
    """The 10 ms level envelope of a source file's audio, decoded once (streamed, so a long
    file never sits in memory) and kept as ``cache`` (.npy)."""
    import shutil
    import subprocess

    import numpy as np
    if cache.is_file():
        try:
            return np.load(cache)
        except (OSError, ValueError):
            pass  # a half-written cache: decode again
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
    tmp = cache.with_name(f"{cache.stem}.{os.getpid()}.{id(levels)}.tmp.npy")
    np.save(tmp, levels)
    os.replace(tmp, cache)
    return levels


_stream_counts: dict[str, int] = {}


def audio_stream_count(media: str) -> int | None:
    """How many audio streams the file has (ffprobe), or None when ffprobe can't say. The
    transcript and levels read the first one, as the Rough Cut does; UXP does not say which
    stream a Premiere clip plays. Remembered for the process by (path, size, mtime), as
    `media_sha256` is, so a timeline read does not spawn ffprobe per source per call."""
    import shutil
    import subprocess
    st = os.stat(media)
    key = f"{os.path.abspath(media)}|{st.st_size}|{st.st_mtime_ns}"
    if key in _stream_counts:
        return _stream_counts[key]
    if shutil.which("ffprobe") is None:
        return None
    result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                             "stream=index", "-of", "csv=p=0", media], capture_output=True, text=True,
                            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    if result.returncode != 0:
        return None
    _stream_counts[key] = len(result.stdout.split())
    return _stream_counts[key]


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
        tmp = index_path.with_name(f"{index_path.name}.{os.getpid()}.{id(index)}.tmp")
        tmp.write_text(json.dumps(index, indent=0), encoding="utf-8")
        try:
            os.replace(tmp, index_path)
        except OSError:  # another writer won the race; this entry is re-hashed next time
            tmp.unlink(missing_ok=True)
    return index[key]


def source_words(media: str, db_path: Path, levels_dir: Path | None = None,
                 bars: bool = False) -> tuple[int, list[SourceWord], object, list, str | None] | None:
    """(transcript job id, word timeline, level envelope or None, untranscribed speech gaps, other-language note or
    None) of the file's finished transcript that transcribe() last returned (`store.latest_transcript_job`), or
    None when it has never been transcribed. With ``levels_dir``, word times are tightened to
    the audio (`tighten`); the file's level envelope is cached there by sha256.

    With ``bars``, words word_align placed keep its times (`tighten` over them loses 6 heldout
    points within a frame, all on ends) and every word gets its placement and error bars."""
    import json as _json
    from transcribe.words import words_for_job
    from transcribe.db import store
    from transcribe.retime import aligned
    sha = media_sha256(media, db_path)
    store.init_db(db_path)  # a store made before job.chosen_at gets the column (idempotent)
    conn = store.connect(db_path)
    try:
        job = store.latest_transcript_job(conn, sha)
        if job is None:
            return None
        cues = [{"idx": t.idx, "text": t.text, "start_ms": t.start_ms, "end_ms": t.end_ms}
                for t in store.get_tokens(conn, job.id)]
        words = source_word_list(words_for_job(conn, job.id), cues)
        result = store.get_engine_result(conn, job.id, "a")
        raw = _json.loads(result.raw_words_json) if result and result.raw_words_json else []
        ctc = bars and aligned(raw)
        if ctc:
            words = placed_words(words, raw)
        words = apply_corrections(words, {c.token_idx: c.corrected_text
                                          for c in store.get_corrections(conn, job.id)})
        # Speech the VAD heard that no cue covers: the engine dropped it (transcribe.service's
        # coverage_gaps). On the timeline an agent would otherwise read it as a pause.
        from transcribe.pipeline import coverage
        speech = [(sp.start_ms, sp.end_ms) for sp in store.get_speech_spans(conn, job.id) if sp.kind == "speech"]
        gaps = [(g.start_ms, g.end_ms) for g in coverage.find_gaps(speech, cues)]
        note = _other_language_note(store.transcript_scripts(conn, sha), job.id)
    finally:
        conn.close()
    levels = None
    if levels_dir is not None:
        try:
            levels = source_levels(media, levels_dir / f"{sha}.npy")
        except (RuntimeError, OSError):
            levels = None  # undecodable audio: engine times, and no sound checks, for this file
        if levels is not None and not ctc:
            words = tighten(words, levels)
            if bars:
                words = [replace(w, start_by="tightened", end_by="tightened") for w in words]
    if bars:
        words = with_bars(words, levels)
    return job.id, words, levels, gaps, note


_LANGUAGES = {"thai": ("Thai", "th"), "latin": ("English", "en")}


def _other_language_note(scripts: dict[int, str], used: int) -> str | None:
    """Says so when the file also has a transcript in the other script: the one used is the
    last one asked for, which may be the wrong language for this audio."""
    others = [j for j, s in scripts.items() if s != scripts.get(used)]
    if used not in scripts or not others:
        return None
    (used_name, _), (other_name, other_code) = _LANGUAGES[scripts[used]], _LANGUAGES[scripts[others[-1]]]
    return (f"these words are the {used_name} transcript (job {used}), the last one asked for; the file also "
            f"has {'an' if other_name == 'English' else 'a'} {other_name} one (job {others[-1]}). If the audio is {other_name}, run "
            f'transcribe(media_path, language="{other_code}") and read again')


def _source_entry(media: str, job_id: int, probe_streams: bool, note: str | None = None,
                  timing: str | None = None) -> dict:
    entry = {"media": media, "transcript_job_id": job_id, **({"note": note} if note else {})}
    if timing:
        entry["timing"] = timing
    if timing == "tightened":
        entry["note"] = "; ".join(filter(None, [entry.get("note"), (
            "word times are the engine's, fitted to the sound (wide error bars): "
            f'run python -m transcribe.retime "{media}" once (CTC only, no new ASR, keeps text and corrections)')]))
    streams = audio_stream_count(media) if probe_streams else None
    if streams and streams > 1:
        entry["audio_streams"] = streams
        entry["note"] = "; ".join(filter(None, [entry.get("note"), (
            "several audio streams: the transcript is of the first; if this track "
            "plays another stream, its words may not be what is heard")]))
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
        lookup = lambda media: source_words(media, db, levels_dir, bars=True)  # noqa: E731
    tpf = int(timeline["ticks_per_frame"])
    track_id, clips, skipped = audio_clips(timeline, track)
    words_by_media, levels_by_media, gaps_by_media, jobs, missing, notes = {}, {}, {}, {}, [], {}
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
        if len(found) > 4 and found[4]:
            notes[media] = found[4]
    timing = {m: ("ctc" if any(w.start_by in ("snap", "ctc") for w in ws) else
                  "tightened" if any(w.start_by == "tightened" for w in ws) else None)
              for m, ws in words_by_media.items()}
    holes_by_media = {m: word_holes(words_by_media[m], lv_) for m, lv_ in levels_by_media.items()}
    words = project(clips, words_by_media)
    cuts = edges(clips, words_by_media, tpf, levels_by_media=levels_by_media)
    if levels_by_media:
        # A word "clipped" by an edge that is quiet in the audio spans a pause; only an edge with
        # sound at it really cuts the word (on a real Short, 27 flags vs 4 cuts in sound).
        loud = {(e["clip"], e["side"]) for e in cuts}
        side = {"head": ("in",), "tail": ("out",), "both": ("in", "out")}
        words = [w if not w.clipped or w.media not in levels_by_media
                 or any((w.clip, sd) in loud for sd in side[w.clipped]) else replace(w, clipped=None)
                 for w in words]
    all_lines = lines(words, tpf)
    result = {"sequence": timeline.get("name"), "sequence_id": timeline.get("sequence_id"),
              "track": track_id, "clips": len(clips), "skipped": skipped, "missing": missing,
              "sources": [_source_entry(m, j, probe_streams, notes.get(m), timing.get(m)) for m, j in jobs.items()],
              "words": len(words), "cuts_in_sound": cuts}
    if query:
        result["matches"] = find(words, query, tpf)
    result["untranscribed"] = spans_on_timeline(clips, gaps_by_media, tpf)
    # Sound no word covers, on the timeline (skipped clips are holes too: see "skipped").
    result["holes"] = spans_on_timeline(clips, holes_by_media, tpf)
    later = later_stream_clips(timeline, track_id)
    warnings = list(notes.values())
    if later:
        warnings.append(f"{len(later)} clip(s) on {track_id} look like a later audio stream of their file "
                        f"(a lower track plays the same file at the same place, e.g. {later[0]}); the "
                        "transcript is of the first stream, so if the streams differ these words are not "
                        "what this track plays")
    if warnings:
        result["warnings"] = warnings
    if from_ticks is not None or to_ticks is not None:
        lo = from_ticks if from_ticks is not None else 0
        hi = to_ticks if to_ticks is not None else 1 << 62
        inside = lambda a, b: b > lo and a < hi  # noqa: E731
        all_lines = [ln for ln in all_lines if inside(int(ln["start_ticks"]), int(ln["end_ticks"]))]
        result["untranscribed"] = [u for u in result["untranscribed"]
                                   if inside(int(u["start_ticks"]), int(u["end_ticks"]))]
        result["holes"] = [h for h in result["holes"] if inside(int(h["start_ticks"]), int(h["end_ticks"]))]
        result["cuts_in_sound"] = [e for e in result["cuts_in_sound"]
                                   if lo <= int(e["at_ticks"]) < hi]
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
        overs = {m: lv.over(levels, lv.QUIET) for m, levels in levels_by_media.items()}
        result["level_at"] = lambda ticks: level_at(clips, levels_by_media, ticks, overs)
        result["source_words"] = words_by_media
        result["clip_objects"] = clips

        def source_level(media, ticks):
            over = overs.get(media)
            if over is None:
                return None
            i = int(ticks / TICKS_PER_MS // ENVELOPE_MS)
            near = over[max(i - 2, 0):i + 2]
            return float(near.max()) if len(near) else float("-inf")
        result["source_level"] = source_level
    return result


# ── a saved project, offline ────────────────────────────────────────────────

def timeline_from_prproj(sequence: dict, fps: float = 30.0) -> dict:
    """A `read_timeline`-shaped dict from one sequence of `cutdeck.prproj_reader`'s summary, so a
    saved project can be heard without Premiere. The reader gives seconds and no speed: speed
    is the clip's source length over its timeline length (Premiere's In/Out are then reported
    divided by it, as `read_timeline` does)."""
    from fractions import Fraction
    nominal = round(fps)
    # 29.97, 23.976, 59.94: the NTSC rates are nominal x 1000/1001 exactly, as Premiere counts them.
    rate = (Fraction(nominal * 1000, 1001) if abs(fps - nominal * 1000 / 1001) < 0.005 and fps != nominal
            else Fraction(fps).limit_denominator(1001))
    tpf = PPRO_TICKS_PER_SECOND * rate.denominator // rate.numerator
    ticks = lambda s: round(s * PPRO_TICKS_PER_SECOND)  # noqa: E731
    tracks, end = [], 0
    for t in sequence.get("audio_tracks", []):
        clips = []
        for c in t.get("clips", []):
            length, source = c["end"] - c["start"], c["source_out"] - c["source_in"]
            speed = round(source / length, 4) if length > 0 and source > 0 else 1.0
            speed = speed or 1.0  # a ratio that rounds to 0 is not a speed Premiere plays
            start = ticks(c["start"])
            clips.append({"id": f"A{t['index'] + 1}@{start}", "start_ticks": str(start), "end_ticks": str(ticks(c["end"])),
                          "in_ticks": str(ticks(c["source_in"] / speed)), "out_ticks": str(ticks(c["source_out"] / speed)),
                          "media": c.get("media_path"), "disabled": bool(c.get("disabled")), "speed": speed,
                          "reversed": False})
            end = max(end, ticks(c["end"]))
        tracks.append({"id": f"A{t['index'] + 1}", "kind": "audio", "muted": bool(t.get("muted")), "clips": clips})
    return {"name": sequence.get("name"), "sequence_id": None, "ticks_per_frame": str(tpf),
            "end_ticks": str(end), "tracks": tracks}


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="What a saved Premiere sequence says and where, from its sources' "
                                             "stored transcripts (no Premiere, no new listening).")
    ap.add_argument("--prproj", required=True, help="the saved .prproj")
    ap.add_argument("--sequence", required=True, help="the sequence's name")
    ap.add_argument("--track", help='audio track, e.g. "A1" (default: first un-muted with clips)')
    ap.add_argument("--fps", type=float, default=30.0, help="the sequence's frame rate (the reader does not give it)")
    ap.add_argument("--query", help="find a phrase")
    ap.add_argument("--json", action="store_true", help="print the whole result as JSON")
    args = ap.parse_args(argv)
    from cutdeck.prproj_reader import read_project
    summary = read_project(args.prproj)
    found = [s for s in summary["sequences"] if s["name"] == args.sequence]
    if not found:
        ap.error(f"no sequence named {args.sequence!r}")
    out_dir = Path(__file__).resolve().parent.parent / "output" / "timeline_transcripts"
    result = build(timeline_from_prproj(found[0], args.fps), track=args.track, query=args.query,
                   limit=100000, out_dir=out_dir)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0
    print(f"{result['sequence']} {result['track']}: {result['clips']} clips, {result['line_count']} lines; "
          f"missing {[m['media'] for m in result['missing']]}; cuts in sound {len(result['cuts_in_sound'])} "
          f"({sum(e.get('severity') != 'tail' for e in result['cuts_in_sound'])} in sound); full: {result.get('full_path')}")
    for warning in result.get("warnings", []):
        print("warning:", warning)
    for ln in result["lines"]:
        print(f"{ln['tc']}  {ln['clip']:<22} {ln['text']}" + ("  [clipped: " + ", ".join(ln["clipped_words"]) + "]" if ln.get("clipped_words") else ""))
    for m in result.get("matches", []):
        print("match", m["tc"], m["text"])
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
