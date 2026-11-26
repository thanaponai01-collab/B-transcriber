"""hks_piece_ends.py: every body piece end of a saved HKS sequence, for a do-confirm answer check.

A piece end is the A1 source point where the sound jumps away (through-edits merged, as
``hks_cut_check.sound_cuts`` does). Each end carries its last words and two flags from the
helper's own measures:

- ``in_speech``: the source is not quiet at the end and the end is not in a word gap
  (``hks_cut_check.quiet_near`` / ``in_word_gap``), whatever the picture shows.
- ``continuation``: the last word is a hanging connective (the retired endings reviewer's list).

``check_answers`` is the answer check: every listed end needs a verdict, and a ``finished``
verdict on a flagged end needs a reason. Experiment: output/hks_rules/do_confirm/.
"""
from __future__ import annotations

from cutdeck.hks_cut_check import in_word_gap, quiet_near, sound_cuts
from transcribe.audio import levels as lv

CONTINUATION = {"คือ", "ก็", "ว่า", "แต่", "แล้ว", "แล้วก็", "ก็คือ"}
LAST_WORDS = 6


def piece_ends(a1_clips: list[dict], sources: dict, body_from: float = 0.0) -> list[dict]:
    """``sources`` maps a media path to (words, levels or None), as ``hks_gates.load_sources``."""
    overs = {m: lv.over(levels, lv.QUIET) for m, (_, levels) in sources.items() if levels is not None}
    ends = []
    for t, out_clip, _ in sound_cuts(a1_clips):
        if out_clip is None or out_clip["start"] < body_from:
            continue  # a hook piece's end is not a body end
        media, src = out_clip.get("media_path"), out_clip["source_out"]
        words, _ = sources.get(media, ([], None))
        said = [w.text for w in words if w.end_ms <= src * 1000 + 40 and w.end_ms > (src - 8) * 1000]
        over = overs.get(media)
        quiet = over is not None and quiet_near(over, src)
        ends.append({"at_s": round(t, 2), "media_path": media, "src_s": round(src, 2),
                     "last_words": " ".join(said[-LAST_WORDS:]),
                     "in_speech": bool(words) and not quiet and not in_word_gap(words, src),
                     "continuation": said[-1] if said and said[-1].strip() in CONTINUATION else None})
    return ends


def check_answers(ends: list[dict], answers: dict) -> list[str]:
    """Problems with a do-confirm answer. ``answers`` maps ``src_s`` (as listed) to
    {"verdict": "finished" | "unfinished", "reason": str}. Empty list: the answer passes."""
    problems = []
    for e in ends:
        a = answers.get(e["src_s"])
        if not a or a.get("verdict") not in ("finished", "unfinished"):
            problems.append(f"{e['at_s']} (src {e['src_s']}): no verdict")
        elif a["verdict"] == "finished" and (e["in_speech"] or e["continuation"]) and not (a.get("reason") or "").strip():
            flag = "in running speech" if e["in_speech"] else f"ends on {e['continuation']!r}"
            problems.append(f"{e['at_s']} (src {e['src_s']}): called finished, {flag}, no reason")
    return problems
