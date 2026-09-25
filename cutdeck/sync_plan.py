"""cutdeck.sync_plan — where every clip of a multi-cam shoot belongs, by audio.

The matching half of native Sync (plan agreed 2026-09-23): the panel sends the clips it read off
the user's flat timeline, this decides each clip's start, the panel places them in Premiere.
Pure — no Premiere, no XML; media is read through an injected `loader` so every shooting
scenario is testable with synthetic audio.

Unlike the retired XML sync (one reference clip; anything not overlapping it failed), clips are placed
through overlaps: the longest clip anchors a session, every clip that matches the session's
audio so far joins it, and the session's audio grows with each one — so a camera that only
overlaps another camera, or a recorder split into several files, still lands. Clips that
connect to nothing start a new session; a "session" of one clip matched nothing and goes to the
back with the others that could not be placed.

Two passes per clip, to keep memory bounded on long shoots: a coarse match at COARSE_RATE
against the whole session, then a fine match at FINE_RATE on a short window against the placed
clip it overlaps most. The coarse match uses COARSE_CHUNK_S pieces of the clip, not all of it:
two recorders' clocks drift apart (50 ppm is 180 ms over an hour), which smears a whole-clip
match into two "equally good" places and rejects it — measured, 2026-09-24. The first piece
that matches places the clip. When the overlap is long, the fine match also runs at its far
end; a different answer there is the drift, reported rather than corrected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

import numpy as np

from cutdeck.sync import correlate_gcc_phat_detail

COARSE_RATE = 2000
FINE_RATE = 16000
MIN_PSR = 10.0
MAX_RUNNER_UP = 0.8  # runner-up peak / best peak above this = two places match: ambiguous
MIN_OVERLAP_S = 2.0
MIN_DURATION_S = 0.5
MIN_RMS = 1e-4
FINE_WINDOW_S = 20.0
FINE_MARGIN_S = 0.1
FINE_TRIES = 6  # fine windows tried across the overlap before a coarse match counts as chance
COARSE_CHUNK_S = 60.0
MAX_DRIFT_PPM = 500.0  # widens the fine search with distance from where the coarse match was made
DRIFT_CHECK_MIN_OVERLAP_S = 60.0
DRIFT_WARN_MS = 20.0
SESSION_GAP_S = 2.0
UNPLACED_GAP_S = 30.0  # between the last synced session and the clips that could not be synced

# loader(path, sample_rate, start_s, duration_s) -> mono float32. start/duration None = whole file.
Loader = Callable[[Path, int, Optional[float], Optional[float]], np.ndarray]
# progress(done, total, stage): "Reading audio" per clip read, then "Matching" per clip tried.
Progress = Callable[[int, int, str], None]


@dataclass(frozen=True)
class ClipInput:
    id: str
    path: Path
    duration_s: float  # length on the timeline; used to lay out clips with no usable audio


@dataclass(frozen=True)
class Placement:
    clip_id: str
    status: str  # anchor | synced | unmatched | no_audio | silent | too_short
    start_s: float  # absolute start in the synced layout; unplaced clips sit at the back
    session: Optional[int] = None
    matched_to: Optional[str] = None
    confidence: Optional[float] = None
    drift_ms: Optional[float] = None
    reason: str = ""


@dataclass
class SyncPlan:
    placements: list[Placement]
    sessions: int
    duration_s: float
    # Length of each readable clip's audio, whole file: what a full-length placement must span.
    media_duration_s: dict[str, float] = field(default_factory=dict)

    @property
    def unplaced(self) -> list[Placement]:
        return [p for p in self.placements if p.status not in ("anchor", "synced")]


@dataclass
class _Clip:
    input: ClipInput
    order: int
    coarse: np.ndarray
    duration_s: float


@dataclass
class _Session:
    starts: dict[str, float] = field(default_factory=dict)  # clip id -> start, session time
    found: dict[str, Placement] = field(default_factory=dict)


def _unit(audio: np.ndarray) -> np.ndarray:
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))) if len(audio) else 0.0
    return (audio / rms).astype(np.float32) if rms > 0 else audio.astype(np.float32)


def _composite(session: _Session, clips: dict[str, _Clip]) -> tuple[np.ndarray, float]:
    """The session's audio so far at COARSE_RATE, and the session time of its first sample.
    Overlapping clips are averaged, not summed: a sum makes stretches that more clips heard
    louder, which breaks the tie between two equally good matches (repeated sound) in favour of
    wherever more cameras happened to be rolling."""
    origin = min(session.starts.values())
    end = max(s + clips[i].duration_s for i, s in session.starts.items())
    out = np.zeros(int(round((end - origin) * COARSE_RATE)) + 1, dtype=np.float32)
    cover = np.zeros(len(out), dtype=np.float32)
    for cid, start in session.starts.items():
        audio = _unit(clips[cid].coarse)
        at = int(round((start - origin) * COARSE_RATE))
        n = min(len(audio), len(out) - at)
        out[at:at + n] += audio[:n]
        cover[at:at + n] += 1.0
    return out / np.maximum(cover, 1.0), origin


def _overlap(a0: float, a1: float, b0: float, b1: float) -> tuple[float, float]:
    return max(a0, b0), min(a1, b1)


def _fine_start(loader: Loader, clip: _Clip, other: _Clip, other_start: float,
                coarse_start: float, at: float, margin: float) -> Optional[float]:
    """Refine `clip`'s start by matching FINE_RATE windows beginning at session time `at`,
    searching `margin` seconds either side of where the coarse start puts it."""
    window = min(FINE_WINDOW_S, clip.duration_s - (at - coarse_start), other.duration_s - (at - other_start))
    if window < MIN_DURATION_S:
        return None
    clip_from = at - coarse_start
    ref_from = max(0.0, at - other_start - margin)
    clip_audio = loader(clip.input.path, FINE_RATE, clip_from, window)
    ref_audio = loader(other.input.path, FINE_RATE, ref_from, window + 2 * margin)
    offset, psr, runner_up = correlate_gcc_phat_detail(ref_audio, clip_audio, FINE_RATE)
    start = other_start + ref_from + offset - clip_from
    if psr < MIN_PSR or runner_up > MAX_RUNNER_UP or abs(start - coarse_start) > margin:
        return None
    return start


def _try_place(clip: _Clip, session: _Session, clips: dict[str, _Clip], loader: Loader) -> Optional[Placement]:
    composite, origin = _composite(session, clips)
    found = None
    chunk_from = 0.0
    while found is None and chunk_from + MIN_OVERLAP_S <= clip.duration_s:
        chunk = clip.coarse[int(chunk_from * COARSE_RATE):int((chunk_from + COARSE_CHUNK_S) * COARSE_RATE)]
        if float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2))) >= MIN_RMS:
            offset, psr, runner_up = correlate_gcc_phat_detail(composite, _unit(chunk), COARSE_RATE)
            if psr >= MIN_PSR and runner_up <= MAX_RUNNER_UP:
                found = (origin + offset - chunk_from, chunk_from, psr)
        chunk_from += COARSE_CHUNK_S
    if found is None:
        return None
    coarse, matched_at, psr = found
    # The placed clip this one overlaps most is the fine reference; too little overlap with
    # everything placed means the peak landed on silence padding, not on shared sound.
    best, best_len = None, 0.0
    for cid, start in session.starts.items():
        o0, o1 = _overlap(coarse, coarse + clip.duration_s, start, start + clips[cid].duration_s)
        if o1 - o0 > best_len:
            best, best_len = cid, o1 - o0
    if best is None or best_len < MIN_OVERLAP_S:
        return None
    other, other_start = clips[best], session.starts[best]
    o0, o1 = _overlap(coarse, coarse + clip.duration_s, other_start, other_start + other.duration_s)
    margin = lambda at: FINE_MARGIN_S + abs(at - (coarse + matched_at)) * MAX_DRIFT_PPM * 1e-6
    # The overlap may open on silence, so step through it until a fine window confirms.
    start, at = None, o0
    for _ in range(FINE_TRIES):
        if at > o1 - MIN_DURATION_S:
            break
        start = _fine_start(loader, clip, other, other_start, coarse, at, margin(at))
        if start is not None:
            break
        at += FINE_WINDOW_S
    if start is None:
        # A coarse peak the fine match cannot confirm is chance. Live 2026-09-23: unrelated audio
        # scored coarse PSR 9-12 against a 37-minute session, one piece passed, and falling back
        # to the coarse start "synced" it on top of the interviews.
        return None
    drift_ms = None
    if o1 - o0 >= DRIFT_CHECK_MIN_OVERLAP_S:
        late_at = o1 - FINE_WINDOW_S
        late = _fine_start(loader, clip, other, other_start, start, late_at, margin(late_at))
        if late is not None:
            drift_ms = (late - start) * 1000.0
    return Placement(clip.input.id, "synced", start, matched_to=best, confidence=psr, drift_ms=drift_ms,
                     reason="" if drift_ms is None or abs(drift_ms) < DRIFT_WARN_MS
                     else f"drifts {drift_ms:+.0f} ms across the overlap — check the end")


def plan_sync(clips: Sequence[ClipInput], loader: Loader, progress: Optional[Progress] = None) -> SyncPlan:
    """Place every clip. Input order is the user's timeline order and orders the sessions."""
    report = progress or (lambda done, total, stage: None)
    rejected: dict[str, Placement] = {}
    usable: dict[str, _Clip] = {}
    media: dict[str, float] = {}

    for order, c in enumerate(clips):
        report(order, len(clips), "Reading audio")
        try:
            coarse = np.asarray(loader(c.path, COARSE_RATE, None, None), dtype=np.float32)
        except Exception as exc:  # no audio stream, offline, unreadable: this clip only
            rejected[c.id] = Placement(c.id, "no_audio", 0.0, reason=f"no usable audio ({exc})")
            continue
        duration = len(coarse) / COARSE_RATE
        media[c.id] = duration
        if duration < MIN_DURATION_S:
            rejected[c.id] = Placement(c.id, "too_short", 0.0, reason="too short to match")
        elif float(np.sqrt(np.mean(coarse.astype(np.float64) ** 2))) < MIN_RMS:
            rejected[c.id] = Placement(c.id, "silent", 0.0, reason="audio is silent")
        else:
            usable[c.id] = _Clip(c, order, coarse, duration)

    pending = sorted(usable.values(), key=lambda c: (-c.duration_s, c.order))
    sessions: list[_Session] = []
    while pending:
        report(len(usable) - len(pending), len(usable), "Matching")
        anchor = pending.pop(0)
        session = _Session({anchor.input.id: 0.0}, {anchor.input.id: Placement(anchor.input.id, "anchor", 0.0)})
        grew = True
        while grew:  # a clip that fails now may match once the session has grown
            grew = False
            for clip in list(pending):
                placed = _try_place(clip, session, usable, loader)
                if placed is not None:
                    session.starts[clip.input.id] = placed.start_s
                    session.found[clip.input.id] = placed
                    pending.remove(clip)
                    grew = True
                    report(len(usable) - len(pending), len(usable), "Matching")
        if len(session.starts) == 1:
            rejected[anchor.input.id] = Placement(anchor.input.id, "unmatched", 0.0,
                                                  reason="its audio matched no other clip")
        else:
            sessions.append(session)

    # Layout: sessions in timeline order, one after another; everything unplaced at the back.
    sessions.sort(key=lambda s: min(usable[i].order for i in s.starts))
    result: dict[str, Placement] = {}
    cursor = 0.0
    for n, session in enumerate(sessions):
        origin = min(session.starts.values())
        end = cursor
        for cid, p in session.found.items():
            start = cursor + session.starts[cid] - origin
            result[cid] = Placement(cid, p.status, start, n, p.matched_to, p.confidence, p.drift_ms, p.reason)
            end = max(end, start + usable[cid].duration_s)
        cursor = end + SESSION_GAP_S
    # Unplaced clips sit in a row on shared tracks, after a gap wide enough to see. The panel places
    # whole files, so each is spaced by the longer of its timeline length and its file's.
    length = lambda c: max(c.duration_s, media.get(c.id, 0.0))
    if sessions:
        cursor += UNPLACED_GAP_S - SESSION_GAP_S
    for c in clips:
        if c.id in rejected:
            p = rejected[c.id]
            result[c.id] = Placement(c.id, p.status, cursor, reason=p.reason)
            cursor += length(c) + SESSION_GAP_S
    duration = max((p.start_s + length(next(c for c in clips if c.id == p.clip_id)) for p in result.values()),
                   default=0.0)
    plan = SyncPlan([result[c.id] for c in clips], len(sessions), duration, media)
    usable.clear()
    return plan
