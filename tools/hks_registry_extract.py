"""Find the commit that introduced each HKS registry entry, and validate the registry.

projects/hks/registry/rules/<id>.json is hand-curated. Each entry carries `probe`: one or more
phrases copied from its source file (each on one physical line). For every probe this runs
`git log --follow -S <probe> -- <source file>` and takes the oldest hit; the oldest hit over
all probes is the entry's `commit`, its date is `added`.

    python tools/hks_registry_extract.py           # fill commit/added where null, validate, summarise
    python tools/hks_registry_extract.py --check   # recompute every commit, report drift, write nothing

A rerun never overwrites a field that is already set (merge by id): fix a wrong commit by hand
and it stays. Exit 1 on any validation error.
"""
import argparse
import collections
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from cutdeck.hks_registry import load, write_rule  # noqa: E402

GATES = "projects/hks/gates/registry.json"
FAILURES = "projects/hks/gates/failure-table.md"
# Files whose ids the registry must keep (ids cited anywhere in them).
ID_SOURCES = ["projects/hks/rules.md", "projects/hks/principles.md",
              "projects/hks/before-you-cut.md", "projects/PRINCIPLES.md"]
ID_RE = re.compile(r"\b(HKS-[CR]?\d+|M-\d+)\b")


def git(*args):
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True)
    return out.stdout.decode("utf-8")


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def first_commit(probe, path):
    """Oldest commit (sha, date) whose diff of `path` changed the count of `probe`."""
    log = git("log", "--follow", "--format=%h %ad", "--date=short", "-S", probe, "--", path)
    lines = log.strip().splitlines()
    return tuple(lines[-1].split()) if lines else None


def bad_probes(rule):
    """Probes that don't name exactly one place in today's source file. A superseded or
    retired entry may probe wording that has since been removed (git still finds it)."""
    text = read(rule["source"]["file"])
    return [(p, text.count(p)) for p in rule["probe"]
            if text.count(p) > 1 or (text.count(p) == 0 and rule["status"] == "active")]


def find(rule):
    path = rule["source"]["file"]
    skip = {p for p, _ in bad_probes(rule)}
    hits = []
    for probe in rule["probe"]:
        if probe in skip:
            continue
        hit = first_commit(probe, path)
        if hit:
            hits.append(hit)
    # Oldest in the file's own history order (dates tie within a day).
    order = history(path)
    return max(hits, key=lambda h: order.index(h[0])) if hits else None


_history = {}


def history(path):
    if path not in _history:
        _history[path] = git("log", "--follow", "--format=%h", "--", path).split()
    return _history[path]


def validate(reg, gates, kcodes, problems):
    ids = [r["id"] for r in reg["rules"]]
    for i, n in collections.Counter(ids).items():
        if n > 1:
            problems.append(f"duplicate id {i}")
    known = set(ids)
    aliases = collections.Counter(a for r in reg["rules"] for a in r["aliases"])
    for a, n in aliases.items():
        if n > 1 or a in known:
            problems.append(f"alias {a!r} is not unique")
    for r in reg["rules"]:
        rid = r["id"]
        if not r["probe"]:
            problems.append(f"{rid}: no probe")
        for p, n in bad_probes(r):
            problems.append(f"{rid}: probe occurs {n} times in {r['source']['file']}: {p!r}")
        if r["status"] not in ("active", "superseded", "retired"):
            problems.append(f"{rid}: bad status {r['status']}")
        if (r["status"] == "superseded") != bool(r["superseded_by"]):
            problems.append(f"{rid}: superseded_by must be set exactly when superseded")
        if r["superseded_by"] and r["superseded_by"] not in known:
            problems.append(f"{rid}: superseded_by {r['superseded_by']} is not an id")
        if r["stage"] not in reg["stages"]:
            problems.append(f"{rid}: bad stage {r['stage']}")
        if r["gate"] is not None and r["gate"] not in gates:
            problems.append(f"{rid}: gate {r['gate']} not in {GATES}")
        if r["kind"] == "code_gate" and (r["gate"] is None or gates[r["gate"]]["status"] != "kept"):
            problems.append(f"{rid}: code_gate needs a kept gate, has {r['gate']}")
        if r["kind"] not in ("code_gate", "do_confirm", "human_only"):
            problems.append(f"{rid}: bad kind {r['kind']}")
        live_dc = r["kind"] == "do_confirm" and r["status"] == "active"
        if live_dc != bool(r["confirm"]):
            problems.append(f"{rid}: confirm must be set exactly for an active do_confirm")
        for k in r["corrections"]:
            if k not in kcodes:
                problems.append(f"{rid}: correction {k} not in {FAILURES}")
    cited = set()
    for path in ID_SOURCES:
        cited |= set(ID_RE.findall(read(path)))
    missing = sorted(cited - known)
    return missing


def summary(reg):
    rules = reg["rules"]
    for field in ("status", "kind", "stage"):
        c = collections.Counter(r[field] for r in rules)
        print(f"{field}: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
    print(f"confirmed: {sum(r['confirmed'] for r in rules)} of {len(rules)}")
    print(f"total: {len(rules)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="recompute every commit; write nothing")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    reg = load()
    gates = json.loads(read(GATES))["gates"]
    kcodes = set(re.findall(r"^\| (K\d+[a-d]?) \|", read(FAILURES), re.M))
    problems = []

    changed = []
    for r in reg["rules"]:
        if not args.check and r["commit"]:
            continue
        hit = find(r)
        if hit is None:
            print(f"no commit found: {r['id']}")
            continue
        if args.check:
            if r["commit"] != hit[0]:
                print(f"drift: {r['id']} stored {r['commit']} found {hit[0]} {hit[1]}")
        else:
            r["commit"], r["added"] = hit
            changed.append(r)

    missing = validate(reg, gates, kcodes, problems)
    if missing:
        print("ids cited in the sources but not in the registry: " + ", ".join(missing))
    for p in problems:
        print("ERROR " + p)

    for r in changed:
        write_rule(r)
    if changed:
        print(f"filled commit for {len(changed)} entries")
    summary(reg)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
