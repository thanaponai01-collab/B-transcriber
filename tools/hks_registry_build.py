"""Generate the HKS rule pages from projects/hks/registry/, the single source.

Writes projects/hks/before-you-cut.md (the entries that came from that page, in its old order and
wording, plus every active code gate) and one skill per stage, .claude/skills/hks-<stage>/SKILL.md,
with every active entry of that stage. Output depends on the registry alone, so a rerun writes the
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
           "Short on purpose. The full rules are in [rules.md](rules.md). This page exists because on "
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


def render(reg):
    """{repo-relative path: text} for every generated file."""
    files = {PAGE: render_before_you_cut(reg)}
    for stage in reg["stages"]:
        files[f".claude/skills/{skill_name(stage)}/SKILL.md"] = render_skill(reg, stage)
    return files


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
    for rel, text in render(load(args.root)).items():
        path = os.path.join(args.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(f"wrote {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
