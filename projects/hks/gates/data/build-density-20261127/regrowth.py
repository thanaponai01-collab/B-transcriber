"""Replay K28-K77 in ledger order: for each rule that cites one of them, would a deterministic check
("this correction repeats K<n>, and active rule X already cites K<n>") have pointed at X instead of a new
rule? Counts rules created per correction and how many of those had such an X of the same stage."""
import json
import glob
from pathlib import Path

R = Path(__file__).parents[4] / "registry"


def load(p):
    return [json.loads(Path(f).read_text(encoding="utf-8")) for f in glob.glob(str(R / p))]


rules = load("rules/*.json")
ks = sorted(load("corrections/*.json"), key=lambda k: (k["date"], k["time"] or "99", int(k["id"][1:].rstrip("abcd"))))
num = lambda k: int(k["id"][1:].rstrip("abcd"))  # noqa: E731
first_cited = {}  # rule id -> first correction id it cites, by ledger order
order = {k["id"]: i for i, k in enumerate(ks)}
for r in rules:
    if r["corrections"]:
        first_cited[r["id"]] = min(r["corrections"], key=lambda c: order.get(c, 1e9))
new_rules, caught = [], []
for k in ks:
    if num(k) < 28:
        continue
    born = [r for r in rules if first_cited.get(r["id"]) == k["id"]]  # rules this correction created
    for r in born:
        new_rules.append(r["id"])
        earlier = [x for x in rules if x["id"] != r["id"] and x["stage"] == r["stage"]
                   and any(c in (k["repeat_of"] or []) for c in x["corrections"])
                   and order.get(first_cited.get(x["id"]), 1e9) < order[k["id"]]]
        if earlier:
            caught.append((k["id"], r["id"], r["stage"], [x["id"] for x in earlier][:6]))
print(len(new_rules), "rules first cite a correction K28-K77;", len(caught), "of them repeat a correction an earlier same-stage rule cites")
for c in caught:
    print(" ", c)
