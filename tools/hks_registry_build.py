"""Generate the HKS rule pages from projects/hks/registry/, the single source.

Writes projects/hks/before-you-cut.md (the entries that came from that page, in its old order and
wording, plus every active code gate), one skill per stage, .claude/skills/hks-<stage>/SKILL.md,
with every active entry of that stage, and the entry skill .claude/skills/hks/SKILL.md that routes
to them. Output depends on the registry alone, so a rerun writes the
same bytes.

    python tools/hks_registry_build.py           # write every generated file
    python tools/hks_registry_build.py --check   # exit 1 if any generated file differs (hand edit or stale)
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from cutdeck.hks_registry import REGISTRY, load  # noqa: E402

PAGE = "projects/hks/before-you-cut.md"
PAGE_TITLE = "Before you cut (read this every time, before any HKS draft)"
WHY = "memory/why-rules-broke-20261125.md"
BANNER = f"GENERATED from {REGISTRY} by tools/hks_registry_build.py; do not edit."
HANDOVER_TOOL = "premiere_hks_handover"
GATES_CLI = "python -m cutdeck.hks_gates --prproj <saved .prproj> --sequence"
# Stage -> what proves it done, for the entry skill.
DONE = {
    "day_setup": f"`{GATES_CLI} Editing` prints `PASS day_setup`",
    "paper_edit": "the user approves the paper edit in their own words (no code gate measures a story)",
    "build": f"`{GATES_CLI} \"<draft>\" --from <body start s>` exits 0: no control fails",
    "handover": f"`{HANDOVER_TOOL}` returns HANDOVER OK (it saves, runs every gate and stores the signed "
                "record the panel shows)",
}

# Stage -> (heading, when an agent loads its skill). Skill names allow only a-z, 0-9 and hyphens.
STAGES = {
    "day_setup": ("Day setup", "when starting an HKS (โหนกระแส) editing day: before the transcript, the "
                  "markers, the colours on `Editing` and the `Backup` sequence are set up, and before "
                  "the paper edit"),
    "paper_edit": ("Paper edit", "when writing or revising an HKS (โหนกระแส) paper edit (which spans "
                   "stay, their order, the hook), before the user approves it and before any build"),
    "build": ("Build", "when building an HKS (โหนกระแส) draft in Premiere from an approved paper edit, "
              "before the first cut, and until the cut checks pass"),
    "handover": ("Handover", "when an HKS (โหนกระแส) draft is built and checked, before telling the user "
                 "it is ready: it lists the handover's own rules and how every do-confirm answer is "
                 f"sent to `{HANDOVER_TOOL}`"),
}


def skill_name(stage):
    return "hks-" + stage.replace("_", "-")


def by_stage(reg):
    active = [r for r in reg["rules"] if r["status"] == "active"]
    return {s: [r for r in active if r["stage"] == s] for s in reg["stages"]}


def page_item(r):
    """The old page's markup: alias "before-you-cut N" is item N with its title in bold; the rest are bullets."""
    n = next((a.split()[-1] for a in r["aliases"] if a.startswith("before-you-cut ")), None)
    if n is None:
        return "- " + r["text"]
    bold = re.match(re.escape(r["title"]) + r"[.:]?", r["text"]).group()
    return f"{n}. **{bold}**{r['text'][len(bold):]}"


def render_before_you_cut(reg):
    active = [r for r in reg["rules"] if r["status"] == "active"]
    sections = {}
    for r in active:
        if r["source"]["file"] == PAGE:
            sections.setdefault(r["source"]["heading"], []).append(r)
    intro = " ".join(r["text"] for r in sections.pop(PAGE_TITLE))
    skills = ", ".join(f"`{skill_name(s)}`" for s in reg["stages"])
    out = [BANNER, "", f"# {PAGE_TITLE}", "",
           "Short on purpose. Every rule is in [the registry](registry/README.md). This page exists because on "
           f"20261125 I had those rules and broke them anyway (the reasons are at the end). {intro}", "",
           f"Every active rule of a stage, with its do-confirm question, is in that stage's skill ({skills}, "
           "under `.claude/skills/`).", "",
           "## Code gates (the handover runs these)"]
    out += [f"- **{r['id']}** {r['title'].rstrip('.')} (`{r['gate']}`)" for r in active if r["kind"] == "code_gate"]
    for heading, rules in sections.items():
        out += ["", f"## {heading}"] + [page_item(r) for r in rules]
    out += ["", f"The whole note: [{WHY}]({WHY})."]
    return "\n".join(out) + "\n"


def rule_text(r):
    head = r["text"] if r["text"].startswith(r["title"]) else f"**{r['title'].rstrip('.')}.** {r['text']}"
    tags = [f"gate `{r['gate']}`" if r["gate"] else "", "human only" if r["kind"] == "human_only" else ""]
    tags = ", ".join(t for t in tags if t)
    return f"- **{r['id']}** {head}" + (f" ({tags})" if tags else "")


def render_skill(reg, stage):
    stages = by_stage(reg)
    rules = stages[stage]
    heading, when = STAGES[stage]
    description = f"HKS {heading.lower()} rules from the rule registry. Load {when}."
    out = ["---", f"name: {skill_name(stage)}",
           f"description: {json.dumps(description, ensure_ascii=False)}",  # a JSON string is valid YAML
           "---", "", BANNER, "",
           f"# HKS {heading.lower()}: rules and do-confirm", "",
           f"The {len(rules)} active `{stage}` rules in [the registry](../../../{REGISTRY}/rules/). A gate id "
           "names the `hks_gates` check that measures the rule.", ""]
    out += [rule_text(r) for r in rules]
    confirms = [r for r in rules if r["confirm"]]
    out += ["", "## Do–confirm", "",
            "Each question needs a written answer in the handover, keyed by its rule id.", ""]
    out += [f"{i}. **{r['id']}** {r['confirm']}" for i, r in enumerate(confirms, 1)]
    if stage == "handover":
        out += ["", "## Sending the answers", "",
                f"Send every answer to the helper's `{HANDOVER_TOOL}` tool as `{{rule_id: answer}}`, one "
                "written answer per active do-confirm rule. That is the list above plus the lists in the "
                "other stage skills:", ""]
        for other, rs in stages.items():
            if other != stage:
                ids = ", ".join(r["id"] for r in rs if r["confirm"])
                out.append(f"- `{skill_name(other)}`: {ids}")
    return "\n".join(out) + "\n"


def render_entry(reg):
    stages = by_stage(reg)
    description = ("HKS (โหนกระแส) entry point. Load first for any HKS editing work: it names the stage "
                   "skill to load, says no stage is done until its gate passes, and takes every user "
                   "correction through tools/hks_correct.py.")
    out = ["---", "name: hks", f"description: {json.dumps(description, ensure_ascii=False)}", "---", "",
           BANNER, "", "# HKS: start here", "",
           "The stages run in this order. Load a stage's skill before you start the stage. **A stage is "
           "not done until its gate passes.** Until then don't call it done, ready or finished, and don't "
           "start the next stage.", "",
           "| Stage | Load | Done when | Gates its rules name |", "|---|---|---|---|"]
    for stage, rules in stages.items():
        gates = sorted({r["gate"] for r in rules if r["gate"]})
        out.append(f"| {STAGES[stage][0]} | `{skill_name(stage)}` ({len(rules)} rules) | {DONE[stage]} | "
                   + (", ".join(f"`{g}`" for g in gates) or "none") + " |")
    out += ["", "## When the user corrects you", "",
            "1. Before anything else, run `python tools/hks_correct.py \"<the user's exact words>\" "
            "--episode <YYYYMMDD> ...` (its `--help` lists the rest). It is the only way a correction "
            "becomes a rule. Never write a rule by hand into rules.md, principles.md, a skill or a memory "
            "file.",
            "2. It exits 2 with questions (which rule wins a conflict; gate or note?). Ask the user each "
            "one, then rerun with the answers.",
            "3. Write the K id it prints next to the correction where memory tells the story. A test "
            "fails on a correction quoted in memory with no K id, and on a K id no rule cites."]
    return "\n".join(out) + "\n"


def render(reg):
    """{repo-relative path: text} for every generated file."""
    files = {PAGE: render_before_you_cut(reg), ".claude/skills/hks/SKILL.md": render_entry(reg)}
    for stage in reg["stages"]:
        files[f".claude/skills/{skill_name(stage)}/SKILL.md"] = render_skill(reg, stage)
    return files


def write_all(root):
    """Write every generated file under ``root``; returns their repo-relative paths."""
    out = []
    for rel, text in render(load(root)).items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        out.append(rel)
    return out


def stale(root):
    """Generated paths whose file under `root` is missing or differs from what render() writes."""
    out = []
    for rel, text in render(load(root)).items():
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            out.append(rel)
            continue
        with open(path, encoding="utf-8") as f:  # universal newlines: a CRLF checkout still matches
            if f.read() != text:
                out.append(rel)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="report differing files, write nothing")
    ap.add_argument("--root", default=ROOT, help="repo root (default: this checkout)")
    args = ap.parse_args()
    if args.check:
        bad = stale(args.root)
        for rel in bad:
            print(f"differs from {REGISTRY}: {rel} (run python tools/hks_registry_build.py)")
        return 1 if bad else 0
    for rel in write_all(args.root):
        print(f"wrote {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
