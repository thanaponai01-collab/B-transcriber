"""hks_handover.py: the one step between an HKS draft and the user. Run it on the saved project.

1. Runs every code gate (``hks_gates``) with its line and kind from the registry.
2. Copies the saved .prproj into ``CutDeck/Drafts`` next to it, so the next episode can diff the
   agent's draft against the user's final (Auto-Save rotates the draft out within hours).
3. Appends a record to ``output/hks_gates/handover.jsonl``; the Stop hook
   (``.claude/hooks/hks_handover_gate.py``) reads it.
4. Prints the handover header: every failed control and warning, by gate id. The handover message
   opens with it.

Exit 1 when a kept control fails and is not overridden. ``--override GATE="reason"`` records the
override in ``projects/hks/gates/overrides.jsonl`` (who may override is the user's call).

    python -m cutdeck.hks_handover --prproj <day>.prproj --sequence "1 YOUTUBE agent v2" --from 26.76
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

from cutdeck import hks_gates

LOG = hks_gates.MAIN / "output" / "hks_gates" / "handover.jsonl"
OVERRIDES = hks_gates.REGISTRY.parent / "overrides.jsonl"


def snapshot(prproj: Path, sequence: str, drafts: Path | None, now: dt.datetime) -> Path:
    folder = drafts or prproj.parent / "CutDeck" / "Drafts"
    folder.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in " -_()" else "_" for ch in sequence)
    target = folder / f"{safe} {now:%Y%m%d-%H%M%S}.prproj"
    shutil.copy2(prproj, target)
    return target


def main(argv: list[str] | None = None) -> int:
    from cutdeck.prproj_reader import read_project
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prproj", type=Path, required=True)
    ap.add_argument("--sequence", required=True)
    ap.add_argument("--from", dest="body_from", type=float, default=0.0)
    ap.add_argument("--drafts", type=Path, default=None, help="snapshot folder (default: CutDeck/Drafts by the project)")
    ap.add_argument("--override", action="append", default=[], metavar='GATE="reason"')
    ap.add_argument("--by", default="agent", help="who overrides: recorded, not checked")
    ap.add_argument("--log", type=Path, default=LOG)
    a = ap.parse_args(argv)
    now = dt.datetime.now()
    project = read_project(a.prproj)
    seq = next((s for s in project["sequences"] if s["name"] == a.sequence
                and any(t.get("clips") for t in s["audio_tracks"])), None)
    if seq is None:
        print(f"HANDOVER BLOCKED: no sequence {a.sequence!r} with audio in the saved project (save first)")
        return 2
    found = hks_gates.run(project, seq, hks_gates.load_sources(seq, hks_gates.MAIN / "transcriber.db",
                                                               hks_gates.MAIN / "output/timeline_transcripts/levels"),
                          a.body_from, None)
    overrides = dict(o.split("=", 1) for o in a.override)
    live = {g: r for g, r in found.items() if r["status"] != "retired"}
    failed = [g for g, r in live.items() if not r["passed"] and r["kind"] == "control" and g not in overrides]
    warned = [g for g, r in live.items() if not r["passed"] and (r["kind"] == "warning" or g in overrides)]
    snap = snapshot(a.prproj, a.sequence, a.drafts, now)
    record = {"time": now.isoformat(timespec="seconds"), "prproj": str(a.prproj),
              "prproj_mtime": a.prproj.stat().st_mtime, "sequence": a.sequence, "snapshot": str(snap),
              "blocked": bool(failed), "failed": failed, "warned": warned, "overrides": overrides,
              "gates": {g: {k: r[k] for k in ("value", "line", "direction", "kind", "status", "passed")}
                        for g, r in found.items()}}
    a.log.parent.mkdir(parents=True, exist_ok=True)
    with a.log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    with OVERRIDES.open("a", encoding="utf-8") as f:
        for gate, reason in overrides.items():
            f.write(json.dumps({"time": record["time"], "gate": gate, "sequence": a.sequence,
                                "value": found.get(gate, {}).get("value"), "reason": reason, "by": a.by},
                               ensure_ascii=False) + "\n")
    head = "HANDOVER BLOCKED" if failed else "HANDOVER OK"
    print(f"{head}: {a.sequence} (snapshot {snap.name})")
    for g in failed + warned:
        r = found[g]
        sign = "<=" if r["direction"] == "max" else ">="
        tag = "FAILED" if g in failed else ("OVERRIDDEN" if g in overrides else "WARNING")
        print(f"  {tag} {g}: {r['value']} (line {sign} {r['line']}) {r.get('detail', '')} at {r['items'][:8]}")
    if failed:
        print("Fix each failed gate, or open the handover message with each failed gate's id and value.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
