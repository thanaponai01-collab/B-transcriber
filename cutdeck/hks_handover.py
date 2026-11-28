"""hks_handover.py: hand over an HKS draft from a saved .prproj, outside Premiere.

Agents in Premiere use the helper's ``premiere_hks_handover`` tool, which saves first. This CLI
runs the same ``hks_enforce.handover`` on a save already on disk (an earlier Drafts copy, the
next-episode measurement): every code gate, the do-confirm answers, a ``CutDeck/Drafts``
snapshot, and a signed record the panel reads. Exit 1 when the draft fails.

    python -m cutdeck.hks_handover --prproj <day>.prproj --sequence "1 YOUTUBE agent v2" --from 26.76
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cutdeck import hks_enforce


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prproj", type=Path, required=True)
    ap.add_argument("--sequence", required=True, help="the draft's GUID, or a name no other sequence has")
    ap.add_argument("--from", dest="body_from", type=float, default=0.0)
    ap.add_argument("--to", dest="show_end", type=float, default=None, help="body end (s), when the end kit is on")
    ap.add_argument("--answers", type=Path, default=None, help="JSON file {rule_id: answer}")
    ap.add_argument("--override", action="append", default=[], metavar='GATE="reason"')
    ap.add_argument("--by", default="agent", help="who overrides: recorded, not checked")
    a = ap.parse_args(argv)
    overrides = dict(o.split("=", 1) for o in a.override if "=" in o)
    if len(overrides) != len(a.override):
        print('HANDOVER BLOCKED: every --override needs a written reason: --override GATE="reason"')
        return 2
    answers = json.loads(a.answers.read_text(encoding="utf-8")) if a.answers else {}
    try:
        r = hks_enforce.handover(a.prproj, a.sequence, a.body_from, a.show_end, answers, overrides, a.by)
    except ValueError as exc:
        print(f"HANDOVER BLOCKED: {exc}")
        return 2
    print(f"HANDOVER {'OK' if r['status'] == 'pass' else 'BLOCKED'}: {r['name']} (snapshot {Path(r['snapshot']).name})")
    for g in r["failed"]:
        print(f"  FAILED {g}: {r['values'].get(g)}")
    for g in r["warned"]:
        print(f"  {'OVERRIDDEN' if g in r['overrides'] else 'WARNING'} {g}")
    if r["answers_missing"]:
        print(f"  {len(r['answers_missing'])} do-confirm answers missing: {', '.join(r['answers_missing'][:12])}")
    return 0 if r["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
