"""Candidate redundancy groups among active build rules: rules that cite the same correction set, and
the registry's own flagged pairs (conflicts.json) that fall inside the build stage. Candidates only;
each group is read by hand in groups.md."""
import json
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[4]
led = json.loads((HERE / "ledger.json").read_text(encoding="utf-8"))
ids = {x["id"] for x in led}

same = {}
for x in led:
    if x["corrections"]:
        same.setdefault(tuple(sorted(x["corrections"])), []).append(x["id"])
print("same correction set:")
for k, v in same.items():
    if len(v) > 1:
        print(" ", v, k)

conf = json.loads((ROOT / "projects/hks/registry/conflicts.json").read_text(encoding="utf-8"))
pairs = [p for p in conf["pairs"] if set(p.get("rules", p.get("ids", []))) <= ids]
print("conflicts.json keys:", list(conf["pairs"][0]) if conf["pairs"] else None)
print(len(pairs), "flagged pairs inside build")
for p in pairs:
    print(" ", p)
