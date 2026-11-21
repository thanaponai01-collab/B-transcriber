"""Cut by words: remove phrases from a timeline, each cut placed in the pauses around it.

The timeline transcript (`cutdeck.timeline_transcript`) gives every word's place on the
sequence, with times tightened to the audio. To remove a run of words, the cut starts in the
pause before its first word and ends in the pause after its last word, leaving a natural pause
(``keep_ms``, at most what was there) split across the join. Cuts are whole sequence frames,
as `cut_copy` takes them.
"""
from __future__ import annotations

from cutdeck.timeline_transcript import TimelineWord, _norm, find

KEEP_MS = 250  # pause left at a join, when the original pauses were at least this long
TICKS_PER_MS = 254016000


def _resolve(words: list[TimelineWord], remove: dict, tpf: int) -> tuple[int, int]:
    """(first, last) word index of one removal: ``{"text", "occurrence"}`` or
    ``{"from_ticks", "to_ticks"}`` (the words lying mostly inside that span)."""
    if "text" in remove:
        found = find(words, remove["text"], tpf, limit=200)
        matches = [m for m in found if m["whole_words"]]
        if not matches:
            if found:
                raise ValueError(f"{remove['text']!r} is only said inside longer words ({found[0]['text']!r} "
                                 f"at {found[0]['tc']}); give the whole words or a tick span")
            raise ValueError(f"not said on this timeline: {remove['text']!r}")
        n = remove.get("occurrence")
        if n is None and len(matches) > 1:
            where = ", ".join(m["tc"] for m in matches[:10])
            raise ValueError(f"{remove['text']!r} is said {len(matches)} times ({where}); pass occurrence (1-based)")
        m = matches[(n or 1) - 1] if 1 <= (n or 1) <= len(matches) else None
        if m is None:
            raise ValueError(f"{remove['text']!r} has only {len(matches)} occurrence(s)")
        lo, hi = int(m["start_ticks"]), int(m["end_ticks"])
    else:
        lo, hi = int(remove["from_ticks"]), int(remove["to_ticks"])
    inside = [i for i, w in enumerate(words) if (min(w.end, hi) - max(w.start, lo)) * 2 > (w.end - w.start) or
              (w.start == w.end and lo <= w.start < hi)]
    if not inside:
        raise ValueError("no word lies inside that span")
    return inside[0], inside[-1]


DIP_FRAMES = 2  # with no quiet frame, how far either side of the target to look for the quietest


def _quiet_frame(frame: int, lo: int, hi: int, tpf: int, level_at, dip: str) -> tuple[int, float | None]:
    """The frame boundary in ``[lo, hi]`` (ticks: the pause) nearest ``frame`` whose audio is
    quiet (``level_at`` below 0): ``(frame, None)``. When the pause has none (words touching),
    the quietest boundary up to ``DIP_FRAMES`` toward the words being dropped (``dip`` "later" or
    "earlier"), never into the kept ones: ``(frame, its dB over the sound threshold)``."""
    first, last = -(-lo // tpf), hi // tpf
    for step in range(max(last - first, 0) + 1):
        for f in (frame - step, frame + step):
            if first <= f <= last:
                level = level_at(f * tpf)
                if level is not None and level < 0:
                    return f, None
    if dip == "later":
        candidates = range(max(frame, first), frame + DIP_FRAMES + 1)
    else:
        candidates = range(frame - DIP_FRAMES, min(frame, last) + 1)
    best, best_level = frame, None
    for f in candidates:
        level = level_at(f * tpf) if f >= 0 else None
        if level is not None and (best_level is None or level < best_level):
            best, best_level = f, level
    return best, (round(best_level, 1) if best_level is not None else float("inf"))


def plan(words: list[TimelineWord], removes: list[dict], tpf: int, end_ticks: int,
         keep_ms: int = KEEP_MS, level_at=None) -> dict:
    """Frame cuts for `cut_copy`, plus what each removal takes out and how tight its joins are.
    ``level_at(ticks)``: dB over the sound threshold at a sequence position (negative = quiet);
    with it each cut moves to the nearest quiet frame in its pause."""
    keep = keep_ms * TICKS_PER_MS
    spans, details = [], []
    for remove in removes:
        i, j = _resolve(words, remove, tpf)
        before = words[i - 1].end if i > 0 else 0
        after = words[j + 1].start if j + 1 < len(words) else end_ticks
        first, last = words[i].start, words[j].end
        gap_before, gap_after = max(first - before, 0), max(after - last, 0)
        # Leave `keep` of pause (never more than was there), half on each side of the join.
        left = min(gap_before, keep // 2 + max(keep // 2 - gap_after, 0))
        right = min(gap_after, keep - left)
        a, b = before + left, after - right
        # Whole frames, rounded inward into the pause: never into the kept words.
        fa, fb = -(-a // tpf), b // tpf
        if fa * tpf > first:
            fa = first // tpf
        if fb * tpf < last:
            fb = -(-last // tpf)
        no_quiet = {}
        if level_at is not None:
            # The quiet frame in the pause nearest the target; the engine's word edges can be
            # off, the audio is not. No quiet frame: the dip, with its level over threshold.
            fa, loud_a = _quiet_frame(fa, before, first, tpf, level_at, "later")
            fb, loud_b = _quiet_frame(fb, last, after, tpf, level_at, "earlier")
            no_quiet = {side: db for side, db in (("start", loud_a), ("end", loud_b)) if db is not None}
        spans.append((fa, fb))
        details.append({"text": "".join(w.text for w in words[i:j + 1]) if not remove.get("text") else remove["text"],
                        "removed_s": [round(fa * tpf / 254016000000, 3), round(fb * tpf / 254016000000, 3)],
                        "pause_before_ms": round(gap_before / TICKS_PER_MS),
                        "pause_after_ms": round(gap_after / TICKS_PER_MS),
                        "tight": gap_before < 2 * tpf or gap_after < 2 * tpf,
                        # side -> dB over the sound threshold at the dip it was cut on
                        **({"no_quiet": no_quiet} if no_quiet else {})})
    spans.sort()
    merged: list[list[int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        elif b > a:
            merged.append([a, b])
    return {"cuts_frames": merged, "removals": details}


def count(words: list[TimelineWord], text: str) -> int:
    """How many times the phrase is said as whole words."""
    return sum(1 for m in find(words, text, 1, limit=10000) if m["whole_words"]) if _norm(text) else 0


PAD_MS = 120  # pause kept before and after a piece, when there is that much


def plan_pieces(words: list[TimelineWord], keeps: list[dict], clips: list, tpf: int, end_ticks: int,
                level_at=None, pad_ms: int = PAD_MS) -> list[dict]:
    """The pieces of source media that play each kept phrase, in the order given: each piece
    starts in the pause before its first word and ends in the pause after its last (``pad_ms``
    of it, then the nearest quiet frame; with no pause, the dip toward the dropped neighbour,
    never into the kept words). A phrase that runs across a cut on this timeline gives one piece
    per clip. Returns ``[{text, media, in_ticks, out_ticks, timeline_s, no_quiet?}]`` with
    source In/Out in ticks, frame-aligned on this timeline."""
    pad = pad_ms * TICKS_PER_MS
    out = []
    for keep in keeps:
        i, j = _resolve(words, keep, tpf)
        before = words[i - 1].end if i > 0 else 0
        after = words[j + 1].start if j + 1 < len(words) else end_ticks
        first, last = words[i].start, words[j].end
        fa = max(first - pad, before) // tpf
        if fa * tpf < before:
            fa += 1
        if fa * tpf > first:
            fa = first // tpf
        fb = -(-min(last + pad, after) // tpf)
        if fb * tpf > after:
            fb -= 1
        if fb * tpf < last:
            fb = -(-last // tpf)
        no_quiet = {}
        if level_at is not None:
            fa, loud_a = _quiet_frame(fa, before, first, tpf, level_at, "earlier")
            fb, loud_b = _quiet_frame(fb, last, after, tpf, level_at, "later")
            no_quiet = {side: db for side, db in (("start", loud_a), ("end", loud_b)) if db is not None}
        text = keep.get("text") or "".join(w.text for w in words[i:j + 1])
        lo, hi = fa * tpf, fb * tpf
        for clip in clips:  # one piece per clip the span runs through
            a, b = max(lo, clip.start), min(hi, clip.end)
            if b <= a:
                continue
            piece = {"text": text, "media": clip.media,
                     "in_ticks": str(clip.in_ + round((a - clip.start) * clip.speed)),
                     "out_ticks": str(clip.in_ + round((b - clip.start) * clip.speed)),
                     "timeline_s": [round(a / 254016000000, 3), round(b / 254016000000, 3)]}
            if no_quiet:
                piece["no_quiet"] = no_quiet
            out.append(piece)
    return out
