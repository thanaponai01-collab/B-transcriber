"""Render the hks-build skill as variants of proposal.json, from an in-memory copy of the registry
(the registry is not written). Checks that no rule and no correction is lost, then prints sizes.

current: tools/hks_registry_build.render_skill as today
a: absorbed rules superseded by their canonical (canonical takes the union of corrections and a gate)
b: a + every gated rule one line, no do-confirm question (the gate answers it)
c: b + playbook rules in PLAYBOOK.md (no question) + the questions split into pause points
"""
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import hks_registry_build as B  # noqa: E402
from cutdeck.hks_registry import load  # noqa: E402

P = json.loads((HERE / "proposal.json").read_text(encoding="utf-8"))
OUT = HERE / "variants"
OUT.mkdir(exist_ok=True)


def apply_a(reg):
    reg = copy.deepcopy(reg)
    rid = {r["id"]: r for r in reg["rules"]}
    for g in P["groups"]:
        c = rid[g["canonical"]]
        for a in g["absorbs"]:
            r = rid[a]
            assert r["status"] == "active" and r["stage"] == "build", a
            c["corrections"] = sorted(set(c["corrections"]) | set(r["corrections"]))
            c["gate"] = c["gate"] or r["gate"]
            r["status"], r["superseded_by"] = "superseded", c["id"]
    return reg


def build_rules(reg):
    return [r for r in reg["rules"] if r["status"] == "active" and r["stage"] == "build"]


def head(n, extra=""):
    return ["---", "name: hks-build", 'description: "HKS build rules from the rule registry. Load when building an HKS '
            '(โหนกระแส) draft in Premiere from an approved paper edit, before the first cut, and until the cut checks pass."',
            "---", "", B.BANNER, "", "# HKS build: rules and do-confirm", "",
            f"The {n} active `build` rules in [the registry](../../../{B.REGISTRY}/rules/).{extra}", ""]


def render_b(reg, reference=(), pauses=None):
    rules = build_rules(reg)
    gated = [r for r in rules if r["gate"]]
    ref = [r for r in rules if r["id"] in reference]
    rest = [r for r in rules if not r["gate"] and r["id"] not in reference]
    out = head(len(rules), " Gated rules are checked by `hks_gates`; the gate is the answer, so they ask nothing.")
    out += ["## Enforced by a gate", ""] + [f"- **{r['id']}** {r['title'].strip('*. ')} (gate `{r['gate']}`)" for r in gated]
    out += ["", "## Rules", ""] + [B.rule_text(r) for r in rest]
    if ref:
        out += ["", "## Playbook", "", f"{len(ref)} READ-DO recipes for timeline moves (roll, slip, slide, ripple, "
                "the moves not to use) are in [PLAYBOOK.md](PLAYBOOK.md). Open it before a move you have not made today."]
    out += ["", "## Do–confirm", ""]
    if pauses:
        byid = {r["id"]: r for r in rest}
        n = 0
        for p in pauses:
            out += [f"### {p['name']}", ""]
            for i in p["rules"]:
                n += 1
                out.append(f"{n}. **{i}** {byid[i]['confirm']}")
            out.append("")
    else:
        out += ["Each question needs a written answer in the handover, keyed by its rule id.", ""]
        out += [f"{i}. **{r['id']}** {r['confirm']}" for i, r in enumerate([r for r in rest if r["confirm"]], 1)]
    pb = ["# HKS build playbook (READ-DO)", "", B.BANNER, ""] + [B.rule_text(r) for r in ref]
    return "\n".join(out) + "\n", ("\n".join(pb) + "\n") if ref else None


def check(reg0, reg, name, pauses=None, reference=()):
    """Every active build rule of today is active or superseded by an active rule; every correction it
    cites is still cited by an active rule; pause points cover every ungated, non-reference rule once."""
    now = {r["id"]: r for r in reg["rules"]}
    cited = {k for r in now.values() if r["status"] == "active" for k in r["corrections"]}
    for r in build_rules(reg0):
        n = now[r["id"]]
        assert n["status"] == "active" or now[n["superseded_by"]]["status"] == "active", (name, r["id"])
        assert set(r["corrections"]) <= cited, (name, r["id"])
    if pauses:
        listed = [i for p in pauses for i in p["rules"]]
        want = {r["id"] for r in build_rules(reg) if not r["gate"] and r["id"] not in reference}
        assert len(listed) == len(set(listed)) and set(listed) == want, (name, set(listed) ^ want)


reg0 = load(str(ROOT))
files = {"current": (B.render_skill(reg0, "build"), None)}
ra = apply_a(reg0)
check(reg0, ra, "a")
files["a"] = (B.render_skill(ra, "build"), None)
files["b"] = render_b(ra)
check(reg0, ra, "c", P["pause_points"], set(P["reference"]))
files["c"] = render_b(ra, set(P["reference"]), P["pause_points"])

print(f"{'variant':8} {'rules':>5} {'questions':>9} {'chars':>6} {'+playbook':>9}")
for k, (skill, pb) in files.items():
    (OUT / f"build_{k}.md").write_text(skill, encoding="utf-8")
    if pb:
        (OUT / f"PLAYBOOK_{k}.md").write_text(pb, encoding="utf-8")
    q = sum(1 for line in skill.splitlines() if line[:1].isdigit() and ". **" in line)
    n = sum(1 for line in skill.splitlines() if line.startswith("- **"))
    print(f"{k:8} {n:5} {q:9} {len(skill):6} {len(pb) if pb else 0:9}")
# what the handover would require (all stages): do_confirm rules still active
for name, reg in (("current", reg0), ("a", ra)):
    print(name, "handover answers required:", sum(1 for r in reg["rules"] if r["status"] == "active" and r["kind"] == "do_confirm"))
