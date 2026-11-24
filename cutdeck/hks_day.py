"""HKS: one command for a new day's footage. The editor's question list, breaks and sponsors.

    python -m cutdeck.hks_day "G:\\Me\\Works\\20261123 - โหนกระแส"
    python -m cutdeck.hks_day "<day folder>" --no-markers      # files only, Premiere untouched

Steps (each is cached, so a re-run only redoes what is missing):

1. Word transcript of every footage file (``hks_words``, Engine A).
2. Drops: opening, bumpers and ad breaks, credits (``hks_breaks``), and where the social part
   starts (the TV clock goes away).
3. Two judges by meaning (``hks_judge``, the user's route of 2026-11-23): ``questions`` (the host's
   questions grouped into story parts) and ``sponsors``. Each runs as a fresh headless
   ``claude -p`` in an empty folder with no tools: it sees only its prompt, never the gold.
4. Files next to the Premiere project, not in the repo:
   ``<day>\\4. PROJECTS\\1. PREMIERE PRO\\CutDeck\\Questions\\<day> questions.md`` and
   ``CutDeck\\Transcript\\<day> transcript.txt``.
5. Ranged markers on the ``Editing`` sequence (one undo step), replacing the draft markers of an
   earlier run. Only when the CutDeck panel is connected, ``Editing`` is the active sequence and
   its length equals the footage's (so timeline time is footage time; one footage file only).
   The marker kinds are in ``projects/hks/memory/marker-draft.md``.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from cutdeck import hks_episode, hks_judge
from transcribe.timebase import Timebase, ms_to_frame, probe

SEQUENCE = "Editing"
JUDGE_MODEL = "opus"
JUDGE_TIMEOUT_S = 1200
DRAFT_NAME = re.compile(r"^(S\d+\.\d+ |\[(OPENING|BREAK|BREAK 3|CREDITS|SPONSOR\?)\])")  # names this command writes
PRINT_NOTE = "\n\nDo not write a file: print the JSON answer as your whole reply, nothing else.\n"


def clock(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t // 60 % 60:02d}:{t % 60:02d}"


def answer_json(text: str) -> dict:
    """The JSON object in a judge's reply (it may wrap it in a code fence)."""
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b < a:
        raise hks_judge.JudgeAnswerError("no JSON object in the reply")
    return json.loads(text[a:b + 1])


def run_judge(prompt: Path, model: str = JUDGE_MODEL) -> dict:
    """A fresh headless Claude Code with no tools, in an empty folder (no repo context)."""
    with tempfile.TemporaryDirectory() as cwd:
        r = subprocess.run(["claude", "-p", "--no-session-persistence", "--tools", "", "--model", model],
                           input=prompt.read_text(encoding="utf-8") + PRINT_NOTE, capture_output=True,
                           text=True, encoding="utf-8", cwd=cwd, timeout=JUDGE_TIMEOUT_S)
    if r.returncode:
        raise RuntimeError(f"claude -p failed: {r.stderr.strip()[:500]}")
    return answer_json(r.stdout)


def judge(folder: Path, task: str, model: str = JUDGE_MODEL) -> dict:
    """Prompt, answer (kept when it already exists), validate, write the episode section. One retry
    when the reply is not a valid answer."""
    prompt, ans = hks_judge.paths(folder, task)
    if not ans.exists():
        hks_judge.write_prompt(folder, task)
        for attempt in (1, 2):
            try:
                data = run_judge(prompt, model)
                per = {m: [hks_judge.Line(*l) for l in v["lines"]]
                       for m, v in hks_judge.shown_table(folder, task).items()}
                hks_judge.parse(task, data, per)
                break
            except (hks_judge.JudgeAnswerError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                if attempt == 2:
                    raise
        ans.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    hks_judge.apply(folder, task)
    return json.loads(ans.read_text(encoding="utf-8"))


def break_blocks(drops: list[dict]) -> list[tuple[float, float, str, str]]:
    """Drops that touch (under 1 s apart) as one block: (start, end, label, kinds)."""
    blocks: list[list] = []
    for d in sorted(drops, key=lambda x: x["start"]):
        if blocks and d["start"] - blocks[-1][1] < 1.0:
            blocks[-1][1] = max(blocks[-1][1], d["end"])
            blocks[-1][2].add(d["kind"])
        else:
            blocks.append([d["start"], d["end"], {d["kind"]}])
    return [(a, b, "OPENING" if "opening" in k else "CREDITS" if "credits" in k else "BREAK", ", ".join(sorted(k)))
            for a, b, k in blocks]


def draft(questions: list[dict], parts: dict[int, str], lines: list[list], drops: list[dict],
          sponsors: list[dict], social_s: float | None, end_s: float) -> tuple[list[dict], str]:
    """(markers, question list markdown) for one footage file. ``questions``: the episode section
    (start, line, story, title); ``lines``: the questions prompt's shown lines [id, start, end, text]."""
    order = [l[0] for l in lines]
    text = {l[0]: l[3] for l in lines}
    rows, markers = [], []
    for i, q in enumerate(questions):
        nxt = questions[i + 1]["start"] if i + 1 < len(questions) else end_s
        k = order.index(q["line"])
        opening = " ".join(text[x] for x in order[k:k + 3])
        n = sum(1 for p in questions[:i + 1] if p["story"] == q["story"])
        rows.append((q["story"], n, q["start"], nxt, q["title"], opening))
        markers.append({"start_s": round(q["start"], 3), "duration_s": round(nxt - q["start"], 3),
                        "name": f"S{q['story']}.{n} {q['title']}"[:200], "comment": opening[:2000]})
    blocks = break_blocks(drops)
    extra = [(a, b, f"[{label}] cut", f"auto: {kinds}") for a, b, label, kinds in blocks]
    if social_s is not None:
        extra.append((social_s, social_s, "[BREAK 3] social part starts", "TV clock gone from here"))
    for s in sponsors:
        if not any(a <= s["start"] and s["end"] <= b for a, b, _, _ in blocks):  # ads inside a break: the break says it
            extra.append((s["start"], s["end"], "[SPONSOR?] check", s.get("why", "")))
    markers += [{"start_s": round(a, 3), "duration_s": round(b - a, 3), "name": name, "comment": why}
                for a, b, name, why in extra]
    markers.sort(key=lambda m: m["start_s"])
    md, story = [], None
    for s, n, a, b, title, opening in rows:
        if s != story:
            md += ["", f"## S{s} {parts.get(s, '')}".rstrip(), ""]
            story = s
        md.append(f"- **{s}.{n}** `{clock(a)}`–`{clock(b)}` ({(b - a) / 60:.1f} min) **{title}**  \n  {opening}")
    md += ["", "## Breaks and sponsors", ""]
    md += [f"- `{clock(a)}`–`{clock(b)}` **{name}** {why}" for a, b, name, why in sorted(extra)]
    return markers, "\n".join(md)


def timecode(t: float, tb: Timebase) -> str:
    """Premiere's HH:MM:SS:FF for ``t`` seconds of footage: the nearest frame, counted at the
    whole-number rate (non-drop-frame)."""
    s, f = divmod(ms_to_frame(t * 1000, tb), round(tb.fps_num / tb.fps_den))
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{f:02d}"


def transcript(lines: list[list], tb: Timebase) -> str:
    """One line per cue: its start and end as Premiere timecode, then the text."""
    return "\n".join(f"[{timecode(l[1], tb)} - {timecode(l[2], tb)}] {l[3]}" for l in lines) + "\n"


async def place_markers(markers: list[dict], footage_s: float, sequence: str = SEQUENCE) -> str:
    """Replace this command's earlier markers on ``sequence`` with ``markers``; refuse unless it is
    the active sequence and as long as the footage."""
    from cutdeck.ai_backend import Backend
    b = Backend()
    if not (await b.premiere_status()).get("connected"):
        return "markers skipped: the CutDeck panel is not connected (open it, run again)"
    seq = await b.premiere("read_sequence", {})
    if seq["name"] != sequence:
        return f"markers skipped: the active sequence is {seq['name']!r}; click the {sequence!r} timeline, run again"
    if abs(seq["end_seconds"] - footage_s) > 0.1:
        return f"markers skipped: {sequence!r} is {seq['end_seconds']:.2f} s, the footage {footage_s:.2f} s (already cut?)"
    tl = await b.premiere("read_timeline", {"sequence": sequence, "tracks": ["V1"], "from_ticks": "0",
                                            "to_ticks": seq["ticks_per_frame"]})
    old = [m["start_ticks"] for m in tl.get("markers", []) if DRAFT_NAME.match(m["name"])]
    if old:
        await b.premiere("remove_markers", {"sequence": sequence, "starts_ticks": old})
    r = await b.premiere("add_markers", {"markers": markers})
    return f"markers: {r['added']} on {sequence!r} ({len(old)} earlier draft markers replaced)"


def run(folder: Path, markers: bool = True, model: str = JUDGE_MODEL) -> list[str]:
    from cutdeck import hks_breaks, hks_words
    from cutdeck.hks_audit import clock_track, tv_part
    from cutdeck.hks_gold import _duration
    day = folder.name[:8]
    log = []
    files = hks_words.footage(folder)
    if not files:
        raise SystemExit(f"no .mp4 in {folder / '1. FOOTAGE'}")
    hks_words.main([str(folder)])
    hks_breaks.day_drops(folder, hks_breaks.load_refs())
    q_answer = judge(folder, "questions", model)
    judge(folder, "sponsors", model)
    parts = {int(p["part"]): str(p.get("name", "")) for p in q_answer.get("parts", [])}
    ep = hks_episode.load(day)
    shown = hks_judge.shown_table(folder, "questions")
    full = hks_judge.shown_table(folder, "sponsors")  # hides nothing: the whole transcript
    out = folder / "4. PROJECTS" / "1. PREMIERE PRO" / "CutDeck" / "Questions"
    out.mkdir(parents=True, exist_ok=True)
    md_all, all_markers, durations = [f"# HKS {day}: questions by story part", "",
                                      "Footage (source) time. Picked automatically from the transcript: check, move markers as needed."], [], []
    for media in hks_episode.broadcast_order(p.name for p in files):
        f = ep["files"].get(media, {})
        path = str(folder / "1. FOOTAGE" / media)
        tv = tv_part(clock_track(path, hks_episode.CACHE))
        dur = _duration(Path(path))
        durations.append(dur)
        mk, md = draft(f.get("questions", []), parts, shown[media]["lines"], f.get("drops", []),
                       f.get("sponsors", []), tv[1] if tv else None, dur)
        all_markers += mk
        md_all += ([f"", f"# {media}"] if len(files) > 1 else []) + [md]
    (out / f"{day} questions.md").write_text("\n".join(md_all) + "\n", encoding="utf-8")
    tx = out.parent / "Transcript"
    tx.mkdir(exist_ok=True)
    (tx / f"{day} transcript.txt").write_text(
        "".join((f"# {m}\n" if len(full) > 1 else "")
                + transcript(v["lines"], probe(str(folder / "1. FOOTAGE" / m))) for m, v in full.items()),
        encoding="utf-8")
    log.append(f"wrote {out / f'{day} questions.md'} and {tx / f'{day} transcript.txt'}")
    if not markers:
        log.append("markers skipped (--no-markers)")
    elif len(files) > 1:
        log.append(f"markers skipped: {len(files)} footage files; markers need one file at timeline 0")
    else:
        log.append(asyncio.run(place_markers(all_markers, durations[0])))
    return log


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("folder", help="the day folder, e.g. G:\\Me\\Works\\20261123 - โหนกระแส")
    p.add_argument("--no-markers", action="store_true", help="write the files only; leave Premiere alone")
    p.add_argument("--model", default=JUDGE_MODEL, help="the judges' Claude model")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    for line in run(Path(args.folder), not args.no_markers, args.model):
        print(line, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
