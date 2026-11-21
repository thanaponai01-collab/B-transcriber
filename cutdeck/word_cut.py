"""Cut by words: remove phrases from a timeline, each cut placed in the pauses around it.

The timeline transcript (`cutdeck.timeline_transcript`) gives every word's place on the
sequence, with times tightened to the audio. To remove a run of words, the cut starts in the
pause before its first word and ends in the pause after its last word, leaving a natural pause
(``keep_ms``, at most what was there) split across the join. Cuts are whole sequence frames,
as `cut_copy` takes them.
"""
from __future__ import annotations

from cutdeck.timeline_transcript import TimelineWord, _norm, find, join_words

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
              (w.start == w.end and lo <= w.start <= hi)]
    if not inside:
        raise ValueError("no word lies inside that span")
    return inside[0], inside[-1]


def _quiet_frame(frame: int, lo: int, hi: int, tpf: int, level_at) -> tuple[int, float | None]:
    """The frame boundary in ``[lo, hi]`` (ticks: the pause) nearest ``frame`` whose audio is
    quiet (``level_at`` below 0): ``(frame, None)``. When the pause has none (words touching),
    ``frame`` stays, the word boundary, with its dB over the sound threshold. (Moving to a
    the quietest frame nearby (a dip) was tried live, 2026-11-22: it left part of a removed filler
    behind and never removed a cut in sound.)"""
    first, last = -(-lo // tpf), hi // tpf
    for step in range(max(last - first, 0) + 1):
        for f in (frame - step, frame + step):
            if first <= f <= last:
                level = level_at(f * tpf)
                if level is not None and level < 0:
                    return f, None
    level = level_at(frame * tpf)
    if level is None:  # no levels for this source: nothing is known, nothing is claimed
        return frame, None
    return frame, round(level, 1)


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
        # Whole frames, rounded inward into the pause. A pause shorter than a frame holds no
        # boundary: take the one that intrudes least (into the kept word, or a sliver of the
        # removed one).
        fa, fb = -(-a // tpf), b // tpf
        if fa * tpf > first:
            lower = first // tpf
            fa = lower if before - lower * tpf < fa * tpf - first else fa
        if fb * tpf < last:
            upper = -(-last // tpf)
            fb = upper if upper * tpf - after < last - fb * tpf else fb
        no_quiet = {}
        if level_at is not None:
            # The quiet frame in the pause nearest the target; the engine's word edges can be
            # off, the audio is not. No quiet frame: the word boundary, with its level over threshold.
            fa, loud_a = _quiet_frame(fa, before, first, tpf, level_at)
            fb, loud_b = _quiet_frame(fb, last, after, tpf, level_at)
            no_quiet = {side: db for side, db in (("start", loud_a), ("end", loud_b)) if db is not None}
        spans.append((fa, fb))
        details.append({"text": "".join(w.text for w in words[i:j + 1]) if not remove.get("text") else remove["text"],
                        "removed_s": [round(fa * tpf / 254016000000, 3), round(fb * tpf / 254016000000, 3)],
                        "pause_before_ms": round(gap_before / TICKS_PER_MS),
                        "pause_after_ms": round(gap_after / TICKS_PER_MS),
                        "tight": gap_before < 2 * tpf or gap_after < 2 * tpf,
                        # side -> dB over the sound threshold at the word boundary it was cut on
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


WORDLESS_GAP_MS, WORDLESS_REACH_MS = 100, 600  # best fit to the owner's 34 edges (2026-11-22)


def _wordless_reach(media: str, edge: int, bound: int, step: int, source_level) -> int:
    """Move a phrase edge (ticks) out over sound no word covers that touches it: at most
    ``WORDLESS_GAP_MS`` of quiet between, ``WORDLESS_REACH_MS`` in all, never past ``bound`` (the
    neighbouring word). ``step`` -1 walks back from a start, +1 forward from an end."""
    unit = 10 * TICKS_PER_MS
    t, quiet, reached = edge, 0, edge
    while abs(t - edge) < WORDLESS_REACH_MS * TICKS_PER_MS:
        t += step * unit
        if (step < 0 and t <= bound) or (step > 0 and t >= bound):
            break
        level = source_level(media, t)
        if level is None:
            break
        if level >= 0:
            reached, quiet = t, 0
        else:
            quiet += 10
            if quiet > WORDLESS_GAP_MS:
                break
    return reached


PAD_MS = 60  # pause kept before and after a piece: the owner's own edges sit here (21 of 25 within a frame, 2026-11-22)


def plan_pieces(words: list[TimelineWord], keeps: list[dict], tpf: int,
                source_words: dict, source_level=None, pad_ms: int = PAD_MS) -> list[dict]:
    """The pieces of source media that play each kept phrase, in the order given.

    The phrase is found on this timeline (a rough cut, a copy), but its edges are placed in the
    SOURCE file: in the pauses around its words there (``pad_ms`` of pause, then the nearest
    quiet frame; with no pause, the word boundary). A rough cut has already removed most pauses; the source still has them, so the
    piece starts and ends cleanly even where the rough cut's words touch, and never carries a
    sliver of a neighbouring clip.

    ``source_words``: {media: [SourceWord]} sorted by start; ``source_level(media, ticks)``: dB
    over the sound threshold at a source position (negative = quiet). Source In/Out are whole
    frames of ``tpf``. Returns ``[{text, media, in_ticks, out_ticks, src_s, no_quiet?}]``."""
    pad = pad_ms * TICKS_PER_MS
    out = []
    for keep in keeps:
        i, j = _resolve(words, keep, tpf)
        kept = words[i:j + 1]
        media = kept[0].media
        if any(w.media != media for w in kept):
            raise ValueError(f"{keep.get('text', 'that span')!r} runs across two source files; keep each part")
        # The words must run on in the source: a phrase that crosses a cut or a reorder here
        # would come back as one piece holding what the cut removed, or Out before In.
        for a, b in zip(kept, kept[1:]):
            if b.src_start_ms < a.src_start_ms or b.src_start_ms - a.src_end_ms > 1000:
                raise ValueError(f"{keep.get('text', 'that span')!r} is not one stretch of its source (it crosses a "
                                 f"cut at {a.text}|{b.text}); keep each part as its own phrase")
        first, last = kept[0].src_start_ms * TICKS_PER_MS, kept[-1].src_end_ms * TICKS_PER_MS
        src = source_words.get(media) or []
        before = max((w.end_ms * TICKS_PER_MS for w in src if w.end_ms * TICKS_PER_MS <= first), default=0)
        after = min((w.start_ms * TICKS_PER_MS for w in src if w.start_ms * TICKS_PER_MS >= last), default=last + pad)
        if source_level is not None:
            # Wordless sound touching the phrase (a breath, a laugh, a word the engine missed)
            # goes with it: the owner kept it on 4 of 17 hand-cut pieces (2026-11-22).
            first = _wordless_reach(media, first, before, -1, source_level)
            last = _wordless_reach(media, last, after, 1, source_level)
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
        if source_level is not None:
            level = lambda t: source_level(media, t)  # noqa: E731
            fa, loud_a = _quiet_frame(fa, before, first, tpf, level)
            fb, loud_b = _quiet_frame(fb, last, after, tpf, level)
            no_quiet = {side: db for side, db in (("start", loud_a), ("end", loud_b)) if db is not None}
        piece = {"text": keep.get("text") or "".join(w.text for w in kept), "media": media,
                 "in_ticks": str(fa * tpf), "out_ticks": str(fb * tpf),
                 "src_s": [round(fa * tpf / 254016000000, 3), round(fb * tpf / 254016000000, 3)]}
        if no_quiet:
            piece["no_quiet"] = no_quiet
        out.append(piece)
    return out


def keep_ranges(words: list[TimelineWord], keeps: list[dict], tpf: int, clips: list,
                source_words: dict, source_level=None, pad_ms: int = PAD_MS,
                end_ticks: int | None = None) -> dict:
    """Keep only these phrases on this timeline, in its own order: their spans in sequence
    frames, and the frame cuts (everything else) for `cut_copy`, which keeps every track and
    layer. Each span's edges are placed as `plan_pieces` places them, in the source file's
    pauses, then mapped back onto the timeline, never past the clip that holds the edge word
    (beyond it the timeline plays other source)."""
    spans, details = [], []
    for keep in keeps:
        i, j = _resolve(words, keep, tpf)
        # Only the outer edges are placed: a span on a rough cut crosses its joins, which stay
        # where they are. Each edge is a one-word plan in that word's own source.
        head = plan_pieces(words, [{"from_ticks": words[i].start, "to_ticks": words[i].end or words[i].start + 1}],
                           tpf, source_words, source_level, pad_ms)[0]
        tail = plan_pieces(words, [{"from_ticks": words[j].start, "to_ticks": words[j].end or words[j].start + 1}],
                           tpf, source_words, source_level, pad_ms)[0]
        piece = {"text": keep.get("text") or join_words(w.text for w in words[i:j + 1]),
                 "no_quiet": {**({"start": head["no_quiet"]["start"]} if "start" in head.get("no_quiet", {}) else {}),
                              **({"end": tail["no_quiet"]["end"]} if "end" in tail.get("no_quiet", {}) else {})}}
        first_clip = next(c for c in clips if c.id == words[i].clip)
        last_clip = next(c for c in clips if c.id == words[j].clip)
        to_seq = lambda clip, src: clip.start + round((src - clip.in_) / clip.speed)  # noqa: E731
        a = max(to_seq(first_clip, int(head["in_ticks"])), first_clip.start)
        b = min(to_seq(last_clip, int(tail["out_ticks"])), last_clip.end)
        fa, fb = -(-a // tpf), b // tpf  # inward: a clamped edge is a clip edge, already on a frame
        if fb <= fa:
            raise ValueError(f"{piece['text']!r} is shorter than a frame on this timeline")
        spans.append([fa, fb])
        details.append({"text": piece["text"], "timeline_s": [round(fa * tpf / 254016000000, 3),
                                                              round(fb * tpf / 254016000000, 3)],
                        **({"no_quiet": piece["no_quiet"]} if piece.get("no_quiet") else {})})
    order = sorted(range(len(spans)), key=lambda k: spans[k][0])
    merged: list[list[int]] = []
    for k in order:
        a, b = spans[k]
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    # The whole sequence, every track: not just where this audio track's clips end.
    end_frame = -(-(end_ticks if end_ticks is not None else max(c.end for c in clips)) // tpf)
    cuts, cursor = [], 0
    for a, b in merged:
        if a > cursor:
            cuts.append([cursor, a])
        cursor = max(cursor, b)
    if cursor < end_frame:
        cuts.append([cursor, end_frame])
    return {"keep_frames": merged, "cuts_frames": cuts, "kept": details}
