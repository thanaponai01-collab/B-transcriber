"""Clean speech: find fillers, repeated words and restarts on a timeline transcript.

Works on the timeline transcript's lines (`timeline_transcript.lines`: one engine cue as the timeline
plays it). A cue ends where the speaker paused, so a whole cue can be cut in its pauses. Each
finding is either cut or marked for the editor. Nothing is ever rewritten: a cut only removes words
that were said (the reconciler's select-only rule).

Kinds:
  * ``filler``: a whole line of hesitation sound (เอ่อ, อืม, อ่า, ฮึ...), or one at the start of a line.
  * ``repeat``: the same line said twice in a row. A short single word said twice is marked, not cut
    (เพิ่บ เพิ่บ, ย่ำแย่ ย่ำแย่ can be on purpose). Three times or more is emphasis and left alone.
  * ``restart``: a short line, then a line that starts with the same words and carries on
    ("จังหวะ / จังหวะพิษ"). The first one is marked, or cut with ``cut_restarts``. Doubling (สีไฟ / สีไฟสีไฟ, ช้า / ช้าช้า) is Thai
    reduplication, not a restart, and is left alone.
  * ``near_restart``: the next line starts almost the same way but not exactly. Marked: which take
    makes the whole sentence is a judgment call for the editor (or the agent, from the context).
  * ``retake``: a retake phrase from ``cut.retake_markers`` (เดี๋ยวเอาใหม่...). Marked.

`plan` then checks every cut against the audio (`word_cut.plan`): a cut that has no quiet frame to
land on becomes a marker (repeats, restarts) or is skipped (fillers), so no cut lands in sound.
"""
from __future__ import annotations

import os
import re

from cutdeck import word_cut
from cutdeck.timeline_transcript import TimelineWord, _norm, join_words, seconds

FILLER = re.compile(r"^(?:เอ่อ|เอิ่ม|อ่า+|อืม+|ฮึ+|หืม|ฮึ่ม|ฮึบ|อ้า+|um+|uh+)+$")
LAUGH = re.compile(r"^(?:ฮ่า|ๆ|5)+$")
MAX_GAP_S = 1.5        # lines further apart than this are not one restart
RESTART_MAX_S = 2.5    # a restart's first take is short (takes.py false_start_max_ms)
SHORT_REPEAT = 8       # a one-word repeated line shorter than this (letters) may be on purpose: mark it
NEAR_SHARE = 0.6       # a near restart shares at least this much of the first line's start
KINDS = ("filler", "repeat", "restart", "near_restart", "retake")


def segments(words: list[TimelineWord]) -> list[tuple[int, int]]:
    """(first, last) word index of each line, grouped as `timeline_transcript.lines` groups them."""
    out: list[list[int]] = []
    for i, w in enumerate(words):
        if out and words[out[-1][1]].clip == w.clip and words[out[-1][1]].cue == w.cue:
            out[-1][1] = i
        else:
            out.append([i, i])
    return [(a, b) for a, b in out]


def _text(words, a, b) -> str:
    return _norm("".join(w.text for w in words[a:b + 1]))


def _one_letter_run(t: str) -> bool:
    return len(set(t)) == 1


def _starts_with_words(words, seg, t: str) -> bool:
    """The line ``seg`` starts with ``t`` and ``t`` ends on one of its word boundaries (มา is not the
    start of มาก)."""
    a, b = seg
    said = ""
    for k in range(a, b):  # never the whole line: something must follow
        said += _norm(words[k].text)
        if said == t:
            return True
        if len(said) >= len(t):
            return False
    return False


def find(words: list[TimelineWord], retake_markers: tuple[str, ...] = (), kinds=KINDS,
         cut_restarts: bool = False) -> list[dict]:
    """Every finding, in timeline order: ``{kind, action ("cut"|"mark"), word_range, text, why}``.
    Restarts are marked unless ``cut_restarts``: on the owner's own finished edit (LV GP 2026, yt)
    they kept 11 of 13 of them, so cutting them is not yet the safe default."""
    segs = segments(words)
    texts = [_text(words, a, b) for a, b in segs]
    markers = [m for m in (_norm(x) for x in retake_markers) if m]
    found: list[dict] = []

    def add(kind, action, a, b, why):
        if kind in kinds:
            found.append({"kind": kind, "action": action, "word_range": [a, b],
                          "text": join_words(w.text for w in words[a:b + 1]), "why": why})

    k = 0
    while k < len(segs):
        (a, b), t = segs[k], texts[k]
        if not t:
            k += 1
            continue
        if FILLER.match(t):
            add("filler", "cut", a, b, "hesitation sound")
            k += 1
            continue
        for j in range(a, b):  # a filler at the start of the line, its own word(s)
            if FILLER.match(_text(words, a, j)) and not FILLER.match(_text(words, j + 1, b)):
                add("filler", "cut", a, j, "hesitation sound at the start of a line")
                break
        if any(m in t for m in markers):
            add("retake", "mark", a, b, "retake phrase: the take before it may need to go")
        # Runs of the same line: twice is a stutter, three or more is emphasis.
        run = k
        while run + 1 < len(segs) and texts[run + 1] == t and _gap(words, segs[run], segs[run + 1]) < MAX_GAP_S:
            run += 1
        if run > k:
            if run - k == 1 and not _one_letter_run(t) and not LAUGH.match(t):
                if b > a or len(t) >= SHORT_REPEAT:  # two words or more, or one long word
                    add("repeat", "cut", a, b, "said twice in a row")
                else:
                    add("repeat", "mark", a, b, "short word said twice: stutter or on purpose?")
            k = run + 1
            continue
        if k + 1 < len(segs) and _gap(words, segs[k], segs[k + 1]) < MAX_GAP_S \
                and not _one_letter_run(t) and not LAUGH.match(t):
            nxt = texts[k + 1]
            short = seconds(words[b].end - words[a].start) <= RESTART_MAX_S
            if nxt.startswith(t + t):
                pass  # doubling (สีไฟ / สีไฟสีไฟ): Thai reduplication, said on purpose
            elif short and _starts_with_words(words, segs[k + 1], t):
                add("restart", "cut" if cut_restarts else "mark", a, b, "started, then said again in full")
            else:
                shared = len(os.path.commonprefix([t, nxt]))
                if shared >= 3 and shared >= NEAR_SHARE * len(t) and nxt != t:
                    add("near_restart", "mark", a, b,
                        "the next line starts almost the same: which take makes the whole sentence?")
        k += 1
    return found


def _gap(words, s1, s2) -> float:
    return seconds(words[s2[0]].start - words[s1[1]].end)


def plan(words: list[TimelineWord], findings: list[dict], tpf: int, end_ticks: int,
         keep_ms: int = word_cut.KEEP_MS, level_at=None) -> dict:
    """Frame cuts for `cut_copy` from the findings to cut, each checked on its own first: one with
    no quiet frame at an edge is marked instead (or, a filler, skipped). Returns ``cuts_frames``,
    ``cut`` / ``marked`` / ``skipped`` (findings, each with ``removed_s`` or ``at_s``)."""
    cut, marked, skipped = [], [], []
    for f in findings:
        i, j = f["word_range"]
        if f["action"] != "cut":
            marked.append({**f, "at_s": [seconds(words[i].start), seconds(words[j].end)]})
            continue
        one = word_cut.plan(words, [{"word_range": [i, j], "text": f["text"]}], tpf, end_ticks, keep_ms, level_at)
        removal = one["removals"][0]
        if removal.get("no_quiet"):
            entry = {**f, "at_s": [seconds(words[i].start), seconds(words[j].end)],
                     "no_quiet": removal["no_quiet"]}
            if f["kind"] == "filler":
                skipped.append(entry)
            else:
                marked.append({**entry, "action": "mark", "why": f["why"] + " (no pause to cut in)"})
            continue
        cut.append({**f, "removed_s": removal["removed_s"]})
    # Findings with no word between them are one removal: planned apart, each would keep part of the
    # pause it shares with the other, leaving a frame or two of nothing between two cuts.
    ranges: list[list[int]] = []
    for i, j in sorted(f["word_range"] for f in cut):
        if ranges and i <= ranges[-1][1] + 1:
            ranges[-1][1] = max(ranges[-1][1], j)
        else:
            ranges.append([i, j])
    together = word_cut.plan(words, [{"word_range": r, "text": "-"} for r in ranges],
                             tpf, end_ticks, keep_ms, level_at) if cut else {"cuts_frames": []}
    return {"cuts_frames": together["cuts_frames"], "cut": cut, "marked": marked, "skipped": skipped}


def after_cuts(at_s: float, cuts_frames: list[list[int]], tpf: int) -> float:
    """Where a time on the source sequence lands on the cut copy (a time inside a cut: the join)."""
    frame, removed = at_s * 254016000000 / tpf, 0
    for a, b in cuts_frames:
        if b <= frame:
            removed += b - a
        elif a <= frame:
            return round((a - removed) * tpf / 254016000000, 3)
    return round((frame - removed) * tpf / 254016000000, 3)


def markers(marked: list[dict], cuts_frames: list[list[int]], tpf: int) -> list[dict]:
    """`add_markers` entries for the marked findings, placed on the cut copy."""
    out = []
    for f in marked:
        a, b = (after_cuts(s, cuts_frames, tpf) for s in f["at_s"])
        out.append({"start_s": a, "duration_s": max(round(b - a, 3), 0), "name": f"CHECK {f['kind']}: {f['text']}"[:200],
                    "comment": f["why"]})
    return out
