"""Per HKS episode: corrections, repeats and the repeat-correction rate, from the correction ledger.

    python tools/hks_corrections_report.py

- corrections: every corrections/K<n>.json of that episode (verbal, red marker, diff).
- repeats: corrections whose repeat_of names an earlier correction of the same mistake.
- gate: corrections cited by a rule whose kept gate was added before the correction's day, so a
  gate should have caught it (projects/hks/gates/README.md "The success metric"; baseline 1.7 per episode
  over 1123-1125, counted against today's gates).
"""
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from cutdeck.hks_registry import load_corrections, load_rules  # noqa: E402


def rows(corrections, rules, gates):
    gated = defaultdict(set)  # correction id -> the days its rules' kept gates were added
    for r in rules:
        g = gates.get(r["gate"]) or {}
        if g.get("status") == "kept":
            for k in r["corrections"]:
                gated[k].add(g["added"])
    by_ep = defaultdict(list)
    for c in corrections:
        by_ep[c["episode"]].append(c)
    out = []
    for ep in sorted(by_ep):
        cs = by_ep[ep]
        repeats = [c for c in cs if c["repeat_of"]]
        gate = [c for c in cs if any(d and d < c["date"] for d in gated[c["id"]])]
        out.append({"episode": ep, "corrections": len(cs), "repeats": len(repeats),
                    "repeat_rate": round(len(repeats) / len(cs), 2), "gate_should_have_caught": len(gate)})
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    with open(os.path.join(ROOT, "projects/hks/gates/registry.json"), encoding="utf-8") as f:
        gates = json.load(f)["gates"]
    table = rows(load_corrections(), load_rules(), gates)
    print("| Episode | Corrections | Repeats | Repeat rate | A kept gate should have caught |")
    print("|---|---|---|---|---|")
    for r in table:
        print(f"| {r['episode']} | {r['corrections']} | {r['repeats']} | {r['repeat_rate']:.2f} | "
              f"{r['gate_should_have_caught']} |")
    n = sum(r["corrections"] for r in table)
    if n:
        print(f"\nAll: {n} corrections over {len(table)} episodes, {n / len(table):.1f} per episode; "
              f"{sum(r['repeats'] for r in table)} repeats ({sum(r['repeats'] for r in table) / n:.2f}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
