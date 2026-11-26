"""Measure 'one HKS skill vs one per stage' and replay the 20261125 session (2ce93c3f).

Prints markdown tables used by skills_prototype.md. Run from the worktree root:
    python <this file> <worktree root>
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

import tiktoken

ROOT = sys.argv[1]
sys.path.insert(0, os.path.join(ROOT, "tools"))
import hks_registry_build as b  # noqa: E402

SESSION = os.path.expanduser("~/.claude/projects/E--Me-5-Claude-Transcriber-v2/"
                             "2ce93c3f-9549-40a3-a8f9-ae2e9b93f444.jsonl")
ENC = tiktoken.get_encoding("cl100k_base")
RULE = re.compile(r"(rules\.md|principles\.md|PRINCIPLES\.md|before-you-cut\.md|hks/README\.md|build-plan\.md)")
# Stage boundaries, local time, inferred from the agent's own messages (see skills_prototype.md).
STAGES = [("17:14:40", "day_setup"), ("18:50:30", "paper_edit"), ("19:16:53", "build"),
          ("19:26:18", "handover"), ("19:29:14", "after handover (user edits, retro)")]


def tok(s):
    return len(ENC.encode(s))


def local(ts):
    return (datetime.fromisoformat(ts.replace("Z", "+00:00")) + timedelta(hours=7)).strftime("%H:%M:%S")


def stage_at(t):
    return [s for start, s in STAGES if start <= t][-1] if t >= STAGES[0][0] else "before"


def git_show(rel):
    return subprocess.run(["git", "-C", ROOT, "show", f"HEAD:{rel}"], capture_output=True,
                          encoding="utf-8").stdout


def body(skill):
    return skill.split("---\n", 2)[2]


# ---- sizes -------------------------------------------------------------------------------
reg = b.load(ROOT)
files = b.render(reg)
skills = {p.split("/")[2]: t for p, t in files.items() if p.endswith("SKILL.md")}
combined = next(iter(skills.values())).split("---\n", 2)[1] + "".join(body(t) for t in skills.values())
today = {rel: git_show(rel) for rel in ("projects/hks/rules.md", "projects/hks/principles.md",
                                        "projects/hks/before-you-cut.md")}

# ---- session -----------------------------------------------------------------------------
rows = [json.loads(line) for line in open(SESSION, encoding="utf-8") if line.strip()]
usage = []  # (local time, context tokens at that request), Claude's own count
calls = {}  # tool_use id -> (local time, context, description)
results = {}  # tool_use id -> result text
compact = None
for o in rows:
    if o.get("type") == "system" and o.get("subtype") == "compact_boundary":
        compact = local(o["timestamp"])
    m = o.get("message") if isinstance(o.get("message"), dict) else {}
    c = m.get("content")
    if o.get("type") == "assistant" and "timestamp" in o:
        u = m.get("usage") or {}
        ctx = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        usage.append((local(o["timestamp"]), ctx))
        for x in c or []:
            if x.get("type") != "tool_use":
                continue
            inp = x.get("input", {})
            target = inp.get("file_path") or inp.get("command") or ""
            if RULE.search(target) or "tool-results" in target:
                calls[x["id"]] = (local(o["timestamp"]), ctx, x["name"], target[:150])
    if o.get("type") == "user" and isinstance(c, list):
        for x in c:
            if x.get("type") == "tool_result" and x.get("tool_use_id") in calls:
                cc = x["content"]
                results[x["tool_use_id"]] = cc if isinstance(cc, str) else "".join(
                    y.get("text", "") for y in cc if isinstance(y, dict))


def ctx_at(t):
    """Context size of the first request at or after local time t."""
    return next(c for tt, c in usage if tt >= t)


def ctx_before(t):
    return [c for tt, c in usage if tt < t][-1]


# Calibration: the 17:14:50 Read of the persisted cat output (principles + rules + memory files).
cal_id = next(i for i, (t, _, name, tgt) in calls.items() if name == "Read" and "tool-results" in tgt)
cal_text = results[cal_id]
cal_t = calls[cal_id][0]
cal_claude = ctx_at("17:14:52") - calls[cal_id][1]
ratio = cal_claude / tok(cal_text)

# Split the Read result (cat -n format) into the files it holds.
plain = "\n".join(re.sub(r"^\s*\d+\t", "", ln) for ln in cal_text.splitlines())
parts = re.split(r"\n====+\n", plain)
read_1125 = {"principles.md (as read)": parts[0], "rules.md (as read)": parts[1]}

print(f"calibration: cl100k {tok(cal_text)} vs Claude usage delta {cal_claude} -> ratio {ratio:.3f}\n")


def size_row(name, text, label):
    return f"| {name} | {len(text):,} | {tok(text):,} | {round(tok(text) * ratio):,} | {label} |"


print("| Loaded | chars | cl100k (measured) | Claude est. (cl100k x ratio, inferred) | note |")
print("|---|---:|---:|---:|---|")
print(size_row("(a) one combined skill, all 4 stages", combined, "four bodies + one frontmatter"))
for name, t in skills.items():
    print(size_row(f"(b) {name}", t, "generated"))
print(size_row("generated before-you-cut.md", files["projects/hks/before-you-cut.md"], "generated"))
print(size_row("(c) today: rules.md + principles.md + before-you-cut.md (HEAD)", "".join(today.values()), "git HEAD"))
for rel, t in today.items():
    print(size_row(f"    {rel} (HEAD)", t, ""))
print(size_row("(c) as read at 1125 17:14:50: principles.md + rules.md", "".join(read_1125.values()),
               "exact text from the transcript"))
print(size_row("    whole 17:14:50 Read result (incl. memory files, line numbers)", cal_text, "calibration input"))
print()

print("| local time | stage (inferred) | tool | what | context before (Claude, measured) | result cl100k |")
print("|---|---|---|---|---:|---:|")
for i, (t, ctx, name, tgt) in sorted(calls.items(), key=lambda kv: kv[1][0]):
    res = results.get(i, "")
    shown = "persisted: preview only" if res.startswith("<persisted-output>") else ""
    tgt = tgt.replace("|", "/").replace("\n", " ")[:110]
    print(f"| {t} | {stage_at(t)} | {name} | `{tgt}` {shown} | {ctx:,} | {tok(res):,} |")
print()

points = {"build start (19:16:53 'Build it')": ctx_at("19:16:53"),
          "build end (19:26:13)": ctx_at("19:26:13"),
          "handover message (19:27:06)": ctx_at("19:27:06"),
          "last request before compaction": ctx_before(compact) if compact else None,
          "first request after compaction": ctx_at(compact) if compact else None}
print(f"compaction (compact_boundary): {compact}")
print(f"rules entered context at request sizes {calls[cal_id][1]:,} .. {ctx_at('17:14:52'):,}")
for k, v in points.items():
    print(f"{k}: {v:,}")
for stage, start in (("paper_edit", "18:50:30"), ("build", "19:16:53"), ("handover", "19:26:18")):
    print(f"per-stage skill for {stage} would load at {start}, context {ctx_at(start):,}")
