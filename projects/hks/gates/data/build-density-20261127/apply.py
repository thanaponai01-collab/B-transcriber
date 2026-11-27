"""Write the 14 merges of proposal.json into the registry (user, 2026-11-27: "apply all 14 merges, carry
C3's question into X10"). Same rule as variants.apply_a: the canonical takes the union of corrections and,
if it has none, the absorbed rule's gate; the absorbed rule is superseded with confirm cleared, as
tools/hks_correct.py --supersedes does. Kinds are not changed (the handover contract is a separate decision)."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[4]))
from cutdeck import hks_registry  # noqa: E402

P = json.loads((HERE / "proposal.json").read_text(encoding="utf-8"))
rid = {r["id"]: r for r in hks_registry.load_rules()}
for g in P["groups"]:
    c = rid[g["canonical"]]
    assert c["status"] == "active", c["id"]
    for a in g["absorbs"]:
        r = rid[a]
        assert r["status"] == "active" and r["stage"] == "build", a
        c["corrections"] = sorted(set(c["corrections"]) | set(r["corrections"]))
        c["gate"] = c["gate"] or r["gate"]
        r.update(status="superseded", superseded_by=c["id"], confirm=None)
        hks_registry.write_rule(r)
    hks_registry.write_rule(c)

# C3's question and reason go into X10, so the merge does not drop the clock check (replay F6: 2/4 -> 0/4).
x10 = rid["HKS-X10"]
x10["text"] = ("No sponsor strip, no 3HD bug, no clock on footage. Zoom a clip that carries the sponsor strip in, "
               "centred on the video. On studio frames the bug and clock are fine, but blur the TV clock wherever "
               "it would show the cut: a clock that jumps between pieces shows the re-cut (was HKS-C3).")
x10["confirm"] = ("In a rendered frame of each footage cover, does any show a sponsor strip, the 3HD bug or the clock? "
                  "And where would a jumping clock show a cut, and is it blurred there?")
hks_registry.write_rule(x10)
print("applied", sum(len(g["absorbs"]) for g in P["groups"]), "supersessions in", len(P["groups"]), "groups")
