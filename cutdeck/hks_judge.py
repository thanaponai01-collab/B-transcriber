"""HKS judgment by meaning, done by the agent in a Claude Code session (the user's route, 2026-11-23).

The steps that need meaning (2.7 sponsors, 2.9 topics and stories, 4.2/4.4/4.5 the story cut,
5.4 hook bites) go through one select-only loop:

1. ``prompt`` turns a footage file's word transcript into numbered lines (``L0001``) and writes
   ``<out>/<day>/<task>.prompt.md``: the task in the user's own rules, the answer format, and the
   lines. Nothing else: no gold, no plan, no audit numbers. Lines inside a 2.2 drop are left out.
2. A **fresh** agent, given only that file, writes ``<task>.answer.json``. It picks line ids and
   never writes times or text of its own.
3. ``apply`` validates the answer (every id must be a shown line, ``from`` not after ``to``;
   anything else raises ``JudgeAnswerError``), turns ids into source seconds and writes the
   episode section. The prompt and the answer stay on disk as the artifact.

    python -m cutdeck.hks_judge prompt "G:\\Me\\Works\\20261120 - โหนกระแส" --task sponsors
    python -m cutdeck.hks_judge apply  "G:\\Me\\Works\\20261120 - โหนกระแส" --task sponsors
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from cutdeck import hks_episode
from cutdeck.hks_tighten import silences

OUT = Path("test_projects/hks_judge")
WORDS = Path("test_projects/hks_words")
MAX_GAP = 0.3    # s of silence that ends a line (Whisper word times touch: 90 % of gaps are under 0.1 s)
BREAK_SLACK = 0.1  # s: a break this far past the next word's start still ends the line before it
MAX_LINE = 8.0   # s: a line never runs longer (20261120: 822 lines, 4.8 s on average)


class JudgeAnswerError(ValueError):
    """The answer names a line that was not shown, or a span that runs backwards."""


@dataclass(frozen=True)
class Line:
    id: str
    start: float
    end: float
    text: str


def lines(words: list[list], drops: list[tuple[float, float]] = (), breaks: list[float] = ()) -> list[Line]:
    """Word pieces ``[[start, end, text], ...]`` -> lines broken at pauses and at MAX_LINE.
    Words inside a drop are left out, and a drop always ends a line. A time in ``breaks`` (a
    silence in the audio, a change of speaker) ends the line before the first word starting
    after it: Whisper stretches words over pauses, so the word gaps alone miss most of them."""
    def dropped(t: float) -> bool:
        return any(a <= t < b for a, b in drops)

    marks = sorted(breaks)
    def broken(prev: list, w: list) -> bool:
        i = bisect_right(marks, prev[0])
        return i < len(marks) and marks[i] <= w[0] + BREAK_SLACK

    out, cur = [], []
    for w in words:
        if dropped((w[0] + w[1]) / 2):
            if cur:
                out.append(cur)
                cur = []
            continue
        if cur and (w[0] - cur[-1][1] > MAX_GAP or w[1] - cur[0][0] > MAX_LINE or broken(cur[-1], w)):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return [Line(f"L{i + 1:04d}", ws[0][0], ws[-1][1], "".join(w[2] for w in ws).strip())
            for i, ws in enumerate(out)]


def _clock(t: float) -> str:
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{int(t % 60):02d}"


SHOW = """You are helping edit a Thai live news-talk show. One host interviews guests about a news
incident (often a crime, a dispute or a scam); the live broadcast runs about two hours, first as
the TV part, then a social-media-only part. The words below are an automatic transcript (it has
errors), one numbered line per stretch of speech, with its position in the broadcast."""

SPAN_FORMAT = """Answer with JSON only, in a file, in this shape:
{"spans": [{"from": "L0123", "to": "L0130", "why": "<a few words, Thai or English>"}]}
Use only line ids shown below. "from" and "to" may be the same line. Do not write times."""

TASKS = {
    "sponsors": {
        "section": "sponsors",
        "hide": (),  # a sponsor read can sit inside a clock-off drop: show everything
        "rules": """Task: mark every stretch where the show promotes a sponsor: a product, brand, shop,
app, service or event is advertised or thanked as a sponsor, read by the host or played as an ad.
Mark the whole promotion, from its first line to its last. Do not mark news content that only
mentions a company. If there is no sponsor, answer {"spans": []}.""",
        "format": SPAN_FORMAT,
    },
    "topics": {
        "section": "topics",
        "hide": ("drops",),
        "rules": """Task: mark where each new topic starts. A topic starts where the host opens a new
subject: a question that moves the talk to a new incident, a new guest, a new part of the story
(what happened, the other side, the police, the money, what happens next). Pick the first line of
the opening question or introduction. Then group consecutive topics that are about the same
incident into one story: story numbers start at 1 and only go up.""",
        "format": """Answer with JSON only, in a file, in this shape:
{"topics": [{"start": "L0042", "story": 1, "title": "<a few words>"}]}
Topics in broadcast order. Use only line ids shown below. Do not write times.""",
    },
    "questions": {  # the editor's question list (hks_day): topics grouped into story parts, named
        "section": "questions",
        "hide": ("drops",),
        "rules": """Task: list the host's questions for the editor's question list. A question starts where
the host opens a new subject: a question that moves the talk to a new incident, a new guest, a new
part of the story (what happened, the other side, the police, the money, what happens next). Pick
the first line of the opening question or introduction, and give each a short Thai title.
Then group consecutive questions into parts, numbered from 1 and only going up, each with a short
Thai name. When the show covers several incidents, one part per incident. When it is about one
incident, split it into its 3 to 6 phases (for example: what happened, the demand, the climax,
the police and the law, what happens next).""",
        "format": """Answer with JSON only, in a file, in this shape:
{"parts": [{"part": 1, "name": "<a few Thai words>"}],
 "topics": [{"start": "L0042", "story": 1, "title": "<a few Thai words>"}]}
"story" is the part number. Topics in broadcast order. Use only line ids shown below. Do not write times.""",
    },
    "cut": {
        "section": "keeps",
        "hide": ("drops", "sponsors"),
        "rules": """Task: cut the YouTube long form. Choose the lines to KEEP; everything else is cut.
The editor's rules:
1. Get into each story fast: open on the guest's first sentence of the story, or on the host's
   summary if the guest is slow to start.
2. Each point is told once. Cut retellings, off-topic asides, backstory, legal analysis, and
   feelings that do not move the events forward. Shorten as much as possible.
3. Cut the host's prompts, clarifications and opinions. Keep a host line only where two guest
   pieces would not join without it. A short host reaction may stay for drama.
4. Viewer comments read on air: always cut. Sponsor reads: always cut.
5. The kept lines must total 15 to 20 minutes. Line lengths are shown in brackets after the time.
Lines marked H are the host's voice, G someone else's (automatic, can be wrong). Topic headers
were added by an earlier pass to help you find your way; they are not lines.""",
        "format": SPAN_FORMAT.replace('"why": "<a few words, Thai or English>"', '"why": "<what this keep is>"'),
    },
    "hook": {
        "section": "hook_bites",
        "hide": ("drops", "sponsors"),
        "rules": """Task: find soundbites for the cold-open hook, the ~20 s before the show's title that makes a
viewer stay. The editor's rule: short, punchy first-person lines from the climax of the main
incident: the most violent or emotional moment if there is one ("I almost died", the moment of
the attack), otherwise a line that makes the viewer say "what!?". Give 8 candidates, best
first. Each candidate is 1 to 3 consecutive lines; the editor will trim inside it.""",
        "format": SPAN_FORMAT + " List the 8 candidates best first.",
    },
    "fb": {
        "section": "fb_pieces",
        "hide": ("drops", "sponsors"),
        "inside": "long_form",
        "rules": """Task: cut the Facebook version from the finished YouTube long form shown below (only its kept
lines are shown). It plays after the same cold-open hook. The editor's rules: the climax of the
main incident, one side's account of it, and an aggressive or striking last line. Keep the
pieces in broadcast order; jump freely, a cover will hide each cut.
The kept lines must total {lo:.0f} to {hi:.0f} seconds. Line lengths are shown in brackets after the time.""",
        "format": SPAN_FORMAT,
    },
    "minute": {
        "section": "minute_pieces",
        "hide": ("drops", "sponsors"),
        "inside": "long_form",
        "rules": """Task: cut the 1-minute square version from the finished YouTube long form shown below (only its
kept lines are shown). It plays after the same cold-open hook. The editor's rules: the single
strongest moment of the main incident, told in a few pieces, ending on a line that lands. Keep the
pieces in broadcast order.
The kept lines must total {lo:.0f} to {hi:.0f} seconds. Line lengths are shown in brackets after the time.""",
        "format": SPAN_FORMAT,
    },
}
SIZED = ("cut", "fb", "minute")


def words_of(day: str, media: str, words_dir: Path = WORDS) -> list[list]:
    return json.loads((words_dir / day / f"{Path(media).stem}.words.json").read_text(encoding="utf-8"))


def hidden(ep: dict, media: str, sections=("drops",)) -> list[tuple[float, float]]:
    """Spans of the given episode sections (each a list of {start, end}) for one file."""
    f = ep["files"].get(media, {})
    return [(d["start"], d["end"]) for name in sections for d in f.get(name, [])]


def episode_lines(folder: Path, words_dir: Path = WORDS, ep_dir: Path = hks_episode.OUT,
                  hide=("drops",), inside: str | None = None) -> dict[str, list[Line]]:
    """Lines per footage file, the spans of the ``hide`` sections left out and, with ``inside``,
    only the lines whose middle lies in that section's ``[[a, b], ...]`` spans. Line ids run on
    across files (one id space a day)."""
    day = folder.name[:8]
    ep = hks_episode.load(day, ep_dir)
    out, n = {}, 0
    for media in hks_episode.broadcast_order(p.name for p in (folder / "1. FOOTAGE").glob("*.mp4")):
        f = ep["files"].get(media, {})
        breaks = [(a + b) / 2 for a, b in silences(str(folder / "1. FOOTAGE" / media))]
        breaks += [t[0] for t in f.get("turns", [])]
        ls = lines(words_of(day, media, words_dir), hidden(ep, media, hide), breaks)
        if inside is not None:
            spans = f.get(inside, [])
            ls = [l for l in ls if any(a <= (l.start + l.end) / 2 < b for a, b in spans)]
        out[media] = [Line(f"L{n + i + 1:04d}", l.start, l.end, l.text) for i, l in enumerate(ls)]
        n += len(ls)
    return out


def _speaker(turns: list, line: Line) -> str:
    """H or G by the larger overlap with 2.6's turns; empty when there are no turns."""
    if not turns:
        return ""
    host = sum(max(0.0, min(line.end, b) - max(line.start, a)) for a, b, who in turns if who == "host")
    other = sum(max(0.0, min(line.end, b) - max(line.start, a)) for a, b, who in turns if who != "host")
    return "H " if host > other else "G "


def prompt_text(task: str, per_file: dict[str, list[Line]], ep: dict | None = None, fill: dict | None = None) -> str:
    """The prompt. The cutting tasks (SIZED) get topic headers, line lengths and host marks from
    ``ep``. A topic header goes before the first shown line at or after the topic's start: line ids
    differ between tasks that hide different sections."""
    t = TASKS[task]
    body = []
    for media, ls in per_file.items():
        if len(per_file) > 1:
            body.append(f"\n## File: {media}\n")
        f = (ep or {}).get("files", {}).get(media, {}) if task in SIZED else {}
        heads = sorted(f.get("topics", []), key=lambda tp: tp["start"])
        for l in ls:
            tp = None
            while heads and heads[0]["start"] <= l.start + 0.05:
                tp = heads.pop(0)  # topics wholly hidden before this line: only the latest shows
            if tp:
                body.append(f"=== topic (story {tp['story']}): {tp['title']} ===")
            size = f" ({l.end - l.start:.1f}s)" if task in SIZED else ""
            body.append(f"{l.id} [{_clock(l.start)}]{size} {_speaker(f.get('turns', []), l)}{l.text}")
    rules = t["rules"].format(**fill) if fill else t["rules"]
    return "\n\n".join([SHOW, rules, t["format"], "## Transcript\n" + "\n".join(body)]) + "\n"


def _index(per_file: dict[str, list[Line]]) -> dict[str, tuple[str, int, Line]]:
    return {l.id: (media, i, l) for media, ls in per_file.items() for i, l in enumerate(ls)}


def parse(task: str, answer: dict, per_file: dict[str, list[Line]]) -> dict[str, list]:
    """Validated answer -> episode section value per footage file (source seconds)."""
    idx = _index(per_file)

    def get(i) -> tuple[str, int, Line]:
        if i not in idx:
            raise JudgeAnswerError(f"line {i!r} was not shown")
        return idx[i]

    out: dict[str, list] = {m: [] for m in per_file}
    if task in ("topics", "questions"):
        last = 0
        for t in answer.get("topics", []):
            media, _, line = get(t["start"])
            story = int(t["story"])
            if story < last or story < 1:
                raise JudgeAnswerError(f"story numbers must start at 1 and only go up ({t})")
            last = story
            out[media].append({"start": line.start, "line": line.id, "story": story, "title": str(t.get("title", ""))})
        return out
    for s in answer.get("spans", []):
        (ma, ia, a), (mb, ib, b) = get(s["from"]), get(s["to"])
        if ma != mb or ib < ia:
            raise JudgeAnswerError(f"span {s['from']}..{s['to']} runs backwards or across files")
        out[ma].append({"start": a.start, "end": b.end, "from": a.id, "to": b.id, "why": str(s.get("why", ""))})
    return out


def paths(folder: Path, task: str, out: Path = OUT) -> tuple[Path, Path]:
    d = out / folder.name[:8]
    return d / f"{task}.prompt.md", d / f"{task}.answer.json"


def lines_path(folder: Path, task: str, out: Path = OUT) -> Path:
    return out / folder.name[:8] / f"{task}.lines.json"


def write_prompt(folder: Path, task: str, out: Path = OUT, ep_dir: Path = hks_episode.OUT,
                 fill: dict | None = None) -> Path:
    """The prompt, plus the line table it shows: an answer's ids mean these lines, whatever the
    episode's sections become later. The table also keeps, per file, the hidden spans and the
    allowed (``inside``) spans, so a kept run never reaches over content the judge did not see."""
    p, _ = paths(folder, task, out)
    p.parent.mkdir(parents=True, exist_ok=True)
    t = TASKS[task]
    ep = hks_episode.load(folder.name[:8], ep_dir)
    per_file = episode_lines(folder, ep_dir=ep_dir, hide=t["hide"], inside=t.get("inside"))
    p.write_text(prompt_text(task, per_file, ep, fill), encoding="utf-8")
    lines_path(folder, task, out).write_text(json.dumps({m: {
        "lines": [[l.id, l.start, l.end, l.text] for l in ls],
        "hidden": hidden(ep, m, t["hide"]),
        "inside": ep["files"].get(m, {}).get(t["inside"], []) if t.get("inside") else None,
    } for m, ls in per_file.items()}, ensure_ascii=False), encoding="utf-8")
    return p


def shown_table(folder: Path, task: str, out: Path = OUT) -> dict[str, dict]:
    return json.loads(lines_path(folder, task, out).read_text(encoding="utf-8"))


def answer(folder: Path, task: str, out: Path = OUT) -> dict[str, list]:
    """The parsed answer, read against the lines its prompt showed."""
    per_file = {m: [Line(*l) for l in v["lines"]] for m, v in shown_table(folder, task, out).items()}
    return parse(task, json.loads(paths(folder, task, out)[1].read_text(encoding="utf-8")), per_file)


def kept_runs(folder: Path, task: str, out: Path = OUT) -> dict[str, list[tuple[float, float]]]:
    """For a span task: per file, the runs of consecutive picked lines as source ranges. A run
    breaks between two shown lines when hidden content, or time outside the allowed spans, lies
    between them: the judge never saw it, so it is never kept."""
    picked = answer(folder, task, out)
    runs_of = {}
    for media, v in shown_table(folder, task, out).items():
        ls, hide, inside = v["lines"], v["hidden"], v["inside"]
        ids = {l[0]: i for i, l in enumerate(ls)}
        kept = set()
        for s in picked.get(media, []):
            kept.update(range(ids[s["from"]], ids[s["to"]] + 1))

        def joined(e: float, s: float) -> bool:
            if any(a < s and b > e for a, b in hide):
                return False
            return inside is None or any(a <= e and s <= b for a, b in inside)

        runs: list[tuple[float, float]] = []
        for i in sorted(kept):
            if runs and i - 1 in kept and joined(ls[i - 1][2], ls[i][1]):
                runs[-1] = (runs[-1][0], ls[i][2])
            else:
                runs.append((ls[i][1], ls[i][2]))
        if inside is not None:  # a shown line's edge may stick out past an allowed span
            runs = [(max(a, c), min(b, d)) for a, b in runs for c, d in inside if a < d and c < b]
        runs_of[media] = runs
    return runs_of


def apply(folder: Path, task: str, out: Path = OUT, ep_dir: Path = hks_episode.OUT) -> dict[str, list]:
    value = answer(folder, task, out)
    for media, v in value.items():
        hks_episode.update(folder.name[:8], media, TASKS[task]["section"], v, ep_dir)
    return value


def measured(folder: Path, task: str, out: Path = OUT) -> tuple[float, float]:
    """(seconds of the picked lines, seconds of the kept runs): the judge's own measure, and what
    the draft really keeps (the pauses between lines included)."""
    picked = answer(folder, task, out)
    lines_s = 0.0
    for media, v in shown_table(folder, task, out).items():
        ids = {l[0]: i for i, l in enumerate(v["lines"])}
        kept = set()
        for sp in picked.get(media, []):
            kept.update(range(ids[sp["from"]], ids[sp["to"]] + 1))
        lines_s += sum(v["lines"][i][2] - v["lines"][i][1] for i in kept)
    return lines_s, sum(b - a for r in kept_runs(folder, task, out).values() for a, b in r)


def write_revision(folder: Path, task: str, max_run_s: float, out: Path = OUT) -> Path | None:
    """When the kept runs exceed ``max_run_s``, keep the answer as ``<task>.answer.v<n>.json`` and
    write ``<task>.revise.md``: the judge's spans with their measured lengths and a cap in its own
    measure (line seconds), scaled by this answer's runs-to-lines ratio. None when it fits."""
    lines_s, run_s = measured(folder, task, out)
    if run_s <= max_run_s:
        return None
    cap = int(max_run_s * lines_s / run_s) - 10
    prompt, ans = paths(folder, task, out)
    n = len(list(ans.parent.glob(f"{task}.answer.v*.json"))) + 1
    data = json.loads(ans.read_text(encoding="utf-8"))
    ans.with_name(f"{task}.answer.v{n}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    per = {m: [Line(*l) for l in v["lines"]] for m, v in shown_table(folder, task, out).items()}
    idx = _index(per)
    order = [l.id for ls in per.values() for l in ls]
    pos = {x: i for i, x in enumerate(order)}
    rows = []
    for sp in data["spans"]:
        ids = order[pos[sp["from"]]:pos[sp["to"]] + 1]
        rows.append(f"{sp['from']}..{sp['to']}  {sum(idx[i][2].end - idx[i][2].start for i in ids):.1f}s  {sp.get('why', '')}")
    note = (f"# Revise your answer\n\nYour answer below was measured with code: its kept lines total {lines_s:.0f} s. "
            f"That is too long. Pauses between kept lines add more on top, so the kept lines must total at most "
            f"{cap} s.\n\nRemove whole spans, or shorten spans by moving \"from\" or \"to\" inward, until the total "
            f"is at most {cap} s. Follow the same rules as the prompt ({prompt.resolve()}): cut what matters "
            f"least first. Do not add new spans. Measure the total with the line lengths in the prompt before "
            f"you write.\n\nWrite the revised answer, same JSON shape, to {ans.resolve()}.\n\n"
            "## Your current spans (from..to, measured length, your reason)\n" + "\n".join(rows) + "\n")
    r = ans.with_name(f"{task}.revise.md")
    r.write_text(note, encoding="utf-8")
    return r


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("action", choices=("prompt", "apply", "revise"))
    p.add_argument("folder")
    p.add_argument("--task", required=True, choices=sorted(TASKS))
    p.add_argument("--max-run-s", type=float, default=1200.0, help="revise: the longest the kept runs may total")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    folder = Path(args.folder)
    if args.action == "prompt":
        print(write_prompt(folder, args.task))
    elif args.action == "revise":
        print(write_revision(folder, args.task, args.max_run_s) or "fits: no revision needed")
    else:
        value = apply(folder, args.task)
        print(json.dumps({m: len(v) for m, v in value.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()


# --- scoring (gold is read here only, never put in a prompt) -----------------------------------

SPONSORS_20261120 = ((824.56, 860.0), (3947.00, 4407.48))  # build plan 2.7: the two known sponsors
MIN_SPONSOR_HIT = 0.5  # share of a known sponsor's seconds the flagged spans must cover; set before the first run


def _overlap(spans, a: float, b: float) -> float:
    return sum(max(0.0, min(b, e) - max(a, s)) for s, e in spans)


def score_sponsors(folder: Path, out: Path = OUT) -> dict:
    """Plan 2.7. 20261120: both known sponsors flagged. Every day: flagged seconds the user kept in
    the YT cut (false positives: the user always cuts sponsors)."""
    from cutdeck.hks_gold import read_day
    value = answer(folder, "sponsors", out)
    gold = read_day(folder)
    kept = 0.0
    for media, spans in value.items():
        flagged = [(s["start"], s["end"]) for s in spans]
        kept += sum(_overlap(flagged, k.source_in, k.source_out) for k in gold.yt.keeps if k.media.lower() == media.lower())
    r = {"day": folder.name[:8], "spans": sum(len(v) for v in value.values()),
         "flagged_s": round(sum(s["end"] - s["start"] for v in value.values() for s in v), 1),
         "kept_in_yt_s": round(kept, 1)}
    if folder.name.startswith("20261120"):
        (spans,) = value.values()
        flagged = [(s["start"], s["end"]) for s in spans]
        r["known_hit"] = [round(_overlap(flagged, a, b) / (b - a), 2) for a, b in SPONSORS_20261120]
        r["pass"] = all(h >= MIN_SPONSOR_HIT for h in r["known_hit"])
    return r


# Topic starts the user marked (source seconds). 20261120: the clip label-colour boundaries of the
# day project, unlabelled (Brown) runs left out (workflow log, Step 2). 290969: the user's reviewed
# markers (tests/data/topic_cut_starts_hks290969.json).
TOPICS_20261120 = (266.0, 936.0, 1715.0, 1925.0, 2096.0, 2469.0, 2820.0, 2988.0, 3727.0, 3889.0)
TOPIC_TOL = 1.5     # s, build plan 2.9
MIN_TOPIC_HIT = 0.75  # share of the user's starts hit: the 24 of 32 the first hand picks reached on 290969


def score_topics(folder: Path, gold_starts, out: Path = OUT) -> dict:
    """Plan 2.9: the share of the user's topic starts with a picked start within TOPIC_TOL, and the
    share of picked starts near one of the user's (a picker that marks every line must not pass)."""
    value = answer(folder, "topics", out)
    picked = sorted(t["start"] for v in value.values() for t in v)
    hit = [g for g in gold_starts if any(abs(p - g) <= TOPIC_TOL for p in picked)]
    near = [p for p in picked if any(abs(p - g) <= TOPIC_TOL for g in gold_starts)]
    stories = len({t["story"] for v in value.values() for t in v})
    return {"day": folder.name[:8], "picked": len(picked), "stories": stories, "gold": len(gold_starts),
            "hit": len(hit), "recall": round(len(hit) / len(gold_starts), 3),
            "precision": round(len(near) / len(picked), 3) if picked else 0.0,
            "missed": [g for g in gold_starts if g not in hit],
            "pass": len(hit) / len(gold_starts) >= MIN_TOPIC_HIT}


HOOK_TOP = 8
HOOK_GROUP = 15.0  # s: hook pieces this close in source are one moment
HOOK_TOL = 2.0     # s: a candidate within this of a moment's pieces finds it
MIN_HOOK_RECALL = 0.5  # share of the user's hook moments among the top 8; set before the first run


def score_hook(folder: Path, out: Path = OUT) -> dict:
    """Plan 5.4: the user's hook moments (body-gold pieces before the hook end, grouped) found by
    the top HOOK_TOP candidates."""
    from cutdeck.hks_gold import read_day
    value = answer(folder, "hook", out)
    cands = [(m, s["start"], s["end"]) for m, v in value.items() for s in v][:HOOK_TOP]
    gold = read_day(folder)
    pieces = sorted((k.media.lower(), k.source_in, k.source_out) for k in gold.yt.keeps
                    if gold.yt.hook_end is not None and k.tl_start < gold.yt.hook_end)
    moments: list[list] = []
    for m, a, b in pieces:
        if moments and moments[-1][0] == m and a - moments[-1][2] <= HOOK_GROUP:
            moments[-1][2] = max(moments[-1][2], b)
        else:
            moments.append([m, a, b])
    found = [mo for mo in moments if any(c[0].lower() == mo[0] and c[1] - HOOK_TOL <= mo[2] and mo[1] <= c[2] + HOOK_TOL
                                         for c in cands)]
    return {"day": folder.name[:8], "candidates": len(cands), "moments": len(moments), "found": len(found),
            "recall": round(len(found) / len(moments), 2) if moments else None,
            "pass": bool(moments) and len(found) / len(moments) >= MIN_HOOK_RECALL}
