"""Build-stage do-confirm replay: current hks-build vs variant c, on the agent's 20261126 YT v1 at its
HANDOVER OK save. The subject does the build do-confirm and lists every break; a blind Sonnet judge
scores which of the 8 known faults (the user's corrections K67-K69 and the draft memo's 'not done'
list) it caught. Raw stdout is saved before parsing; existing runs are skipped; spend is capped.

    python run.py subjects current_1 c_1 ...
    python run.py judge
    python run.py summary
"""
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
VAR = HERE.parent / "variants"
RUNS = HERE / "runs"
JUDGE = HERE / "judge"
CAP = 12.0

CTX = """You are the editing agent for โหนกระแส, a Thai live news-talk show. Today (20261126): accusations about
คุณกัน จอมพลัง's foundation and money, on the day he is questioned at DSI. You built the YouTube long form draft
below in Premiere from the approved paper edit: an After Effects opener (headline cards) on V1, the body pieces
from the broadcast on V2 + A1, covers on V3. The template kit and the user's `Backup` sequence (still listening
shots and B-roll) are in the project. The draft is now saved and you are at the build stage's do-confirm,
before handover."""

TASK = """Task: do the build stage's do-confirm on this draft, exactly as the rule book asks. Answer every
do-confirm question it lists, from the timeline below (say "cannot tell from the timeline" where that is true).
Then list every rule this draft breaks: rule id, where (timeline times), what is wrong, and the fix.

Answer with JSON only, in this shape:
{"answers": {"<rule id>": "<answer>"},
 "breaks": [{"rule": "<rule id>", "where": "<timeline times>", "what": "<what is wrong>", "fix": "<the fix>"}]}"""

FAULTS = {
    "F1": "Covers are not chosen per cut: (nearly) every cut gets the same fixed-length cover (4 s), the same few "
          "shots are reused, and a cover's footage is not what the words at that cut point at.",
    "F2": "No tightening inside the kept passages: body pieces are long (many 20-50 s) with no cuts inside them, "
          "so pauses, restarts, doubled words and fillers are left in.",
    "F3": "No split edits: sound and picture cut on the same frame at the body joins; no J or L cuts (none built "
          "on a copy on an upper track).",
    "F4": "No music bed: no BGM clip under the piece (the audio tracks other than A1 are empty).",
    "F5": "No film damage on the covers / B-roll.",
    "F6": "No blur over the TV clock (no clock-blur adjustment layer anywhere).",
    "F7": "The template finish is missing: no sting / glitch / invert flash / whoosh at the section change from "
          "the opener into the body, and/or no end stack / end card / held face at the end.",
    "F8": "A sliver shot: a 0.04 s clip at about 3:58.68 (a flash / snappy change).",
}


def spent():
    tot = 0.0
    for f in list(RUNS.glob("*.raw.json")) + list(JUDGE.glob("*.raw.json")):
        try:
            tot += json.loads(f.read_text(encoding="utf-8")).get("total_cost_usd", 0.0)
        except Exception:
            pass
    return tot


def claude(prompt, model):
    with tempfile.TemporaryDirectory() as cwd:
        p = subprocess.run(["claude", "-p", "--model", model, "--tools", "", "--strict-mcp-config",
                            "--no-session-persistence", "--output-format", "json",
                            "--setting-sources", "project", "--settings", '{"effortLevel": "medium"}'],
                           input=prompt, capture_output=True, text=True, encoding="utf-8", cwd=cwd, timeout=1800)
    return p.stdout or json.dumps({"error": p.stderr})


def subject_prompt(arm):
    skill = (VAR / f"build_{arm}.md").read_text(encoding="utf-8")
    tl = (HERE / "timeline.md").read_text(encoding="utf-8")
    return (f"{CTX}\n\nThe editor's rule book for this step (the hks-build skill) follows. Follow it.\n\n"
            f"<skill>\n{skill.strip()}\n</skill>\n\n{TASK}\n\n{tl}")


def parse(raw):
    r = json.loads(raw)
    t = r.get("result", "")
    t = t[t.find("{"): t.rfind("}") + 1]
    return r, json.loads(t)


def subjects(jobs):
    RUNS.mkdir(exist_ok=True)
    for job in jobs:
        raw = RUNS / f"{job}.raw.json"
        if raw.exists():
            print(job, "exists"); continue
        if spent() + 1.2 > CAP - 1.5:
            print(job, f"stopped: spent {spent():.2f}"); break
        raw.write_text(claude(subject_prompt(job.split("_")[0]), "opus"), encoding="utf-8")
        r = json.loads(raw.read_text(encoding="utf-8"))
        print(job, "cost", r.get("total_cost_usd"), "err", r.get("is_error"), f"spent {spent():.2f}", flush=True)


def judge():
    JUDGE.mkdir(exist_ok=True)
    key_f = JUDGE / "blind_key.json"
    key = json.loads(key_f.read_text(encoding="utf-8")) if key_f.exists() else {}
    for raw in sorted(RUNS.glob("*.raw.json")):
        job = raw.name[:-9]
        if job in key.values():
            continue
        name = f"r_{random.randrange(16**6):06x}"
        key[name] = job
        _, out = parse(raw.read_text(encoding="utf-8"))
        # the judge sees the subject's own words; rule ids are kept (they can hint the arm; noted in the report)
        prompt = ("You are scoring an editor's self-check of a video draft against a fixed list of faults the draft "
                  "really has. For each fault, say whether the self-check below names it as a problem to fix "
                  "(anywhere: in a break or in an answer). It counts only if the self-check says it is wrong or "
                  "missing; mentioning the topic as fine does not count. Be strict and literal.\n\nFaults:\n"
                  + "\n".join(f"{k}: {v}" for k, v in FAULTS.items())
                  + '\n\nAnswer with JSON only: {"F1": {"caught": true|false, "quote": "<short quote or empty>"}, ...}'
                  + "\n\nSelf-check:\n" + json.dumps(out, ensure_ascii=False, indent=1))
        (JUDGE / f"{name}.raw.json").write_text(claude(prompt, "sonnet"), encoding="utf-8")
        key_f.write_text(json.dumps(key, indent=1), encoding="utf-8")
        print(name, f"spent {spent():.2f}", flush=True)


def summary():
    key = json.loads((JUDGE / "blind_key.json").read_text(encoding="utf-8"))
    rows = {}
    for name, job in sorted(key.items(), key=lambda x: x[1]):
        _, v = parse((JUDGE / f"{name}.raw.json").read_text(encoding="utf-8"))
        r, out = parse((RUNS / f"{job}.raw.json").read_text(encoding="utf-8"))
        hits = sorted(k for k in FAULTS if v.get(k, {}).get("caught"))
        rows[job] = {"caught": len(hits), "hits": hits, "breaks": len(out.get("breaks", [])),
                     "answers": len(out.get("answers", {})), "cost": round(r.get("total_cost_usd", 0), 3),
                     "out_tok": r.get("usage", {}).get("output_tokens")}
        print(job, rows[job])
    for arm in sorted({j.split("_")[0] for j in rows}):
        c = [x["caught"] for j, x in rows.items() if j.startswith(arm + "_")]
        print(f"{arm}: caught {c} mean {sum(c) / len(c):.2f} range {max(c) - min(c)}")
        for k in FAULTS:
            print(f"   {k}: {sum(1 for j, x in rows.items() if j.startswith(arm + '_') and k in x['hits'])}/{len(c)}")
    print(f"spent {spent():.2f}")
    (HERE / "results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    {"subjects": lambda: subjects(sys.argv[2:]), "judge": judge, "summary": summary}[sys.argv[1]]()
