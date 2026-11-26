"""Failure ledger for active build rules: corrections cited, repeats of those corrections after the
rule was added, gate, confirmed, kind. Reads the registry only. Writes ledger.json next to this file."""
import collections
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
R = ROOT / "projects/hks/registry"


def load(pat):
    return [json.loads(Path(f).read_text(encoding="utf-8")) for f in glob.glob(str(R / pat))]


rules = {r["id"]: r for r in load("rules/*.json")}
ks = {k["id"]: k for k in load("corrections/*.json")}
# a correction that repeats K means K's lesson was missed again
repeats_of = collections.defaultdict(list)
for k in ks.values():
    for p in k.get("repeat_of") or []:
        repeats_of[p].append(k)

rows = []
for r in rules.values():
    if r["status"] != "active" or r["stage"] != "build":
        continue
    cited = r.get("corrections") or []
    later = sorted({k["id"] for c in cited for k in repeats_of.get(c, []) if k["date"] >= r["added"]})
    rows.append({"id": r["id"], "title": r["title"], "kind": r["kind"], "gate": r["gate"],
                 "confirmed": r["confirmed"], "added": r["added"], "corrections": cited,
                 "repeats_after_added": later, "source": r["source"]["file"], "aliases": r["aliases"],
                 "chars": len(r["text"]) + len(r.get("confirm") or "")})
rows.sort(key=lambda x: (-len(x["repeats_after_added"]), -len(x["corrections"])))
(Path(__file__).parent / "ledger.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

print(len(rows), "build rules;", sum(1 for x in rows if not x["corrections"]), "cite no correction;",
      sum(1 for x in rows if x["repeats_after_added"]), "repeated after added;",
      sum(1 for x in rows if x["gate"]), "gated;", sum(1 for x in rows if x["confirmed"]), "confirmed")
print("sources", dict(collections.Counter(x["source"] for x in rows)))
for x in rows:
    print(f'{x["id"]:9} g={str(x["gate"])[:22]:22} c={int(x["confirmed"])} '
          f'K={",".join(x["corrections"])[:28]:28} rep={",".join(x["repeats_after_added"])[:24]:24} {x["title"][:48]}')
