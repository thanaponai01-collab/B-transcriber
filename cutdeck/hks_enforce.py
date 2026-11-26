"""hks_enforce.py: the helper side of the HKS handover. The agent asks; the helper decides.

``premiere_hks_handover`` saves the project, reads the save, finds the draft by its GUID, runs
every code gate, checks that each active do-confirm rule in the registry has a written answer,
copies the save into ``CutDeck/Drafts`` and stores a record keyed by GUID and cut hash
(``hks_gate_store``). ``premiere_hks_status`` lists every sequence of the last save with its
status from those records only: pass, fail (gate id and value) or ungated.

The body range (``body_from``, ``show_end``) is what the agent gives that changes gate values, so
the record keeps it and the status shows it. ``body_range`` fails a body that starts after
``MAX_BODY_FROM`` s or runs under ``MIN_BODY_S`` s (the user's 14 finals: start 18.6-32.0 s, body
984 s or more; output of tools/hks_gates_mutate.py, 2026-11-26).
A share of the sequence was tried first and never fired inside the show, because the YT
sequence holds the reels' pool after the show end (mutation test, 2026-11-26).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from cutdeck import hks_gate_store, hks_gates, hks_registry
from cutdeck.hks_handover import OVERRIDES, snapshot

MAX_BODY_FROM = 45.0
MIN_BODY_S = 900.0


def do_confirm_rules() -> dict[str, str]:
    return {r["id"]: r["confirm"] for r in hks_registry.load_rules()
            if r["status"] == "active" and r["kind"] == "do_confirm"}


def find_sequence(project: dict, sequence: str) -> dict:
    """By GUID, else by name; a name two sequences share is refused (names repeat in HKS days)."""
    hits = [s for s in project["sequences"] if s.get("guid") == sequence] or \
           [s for s in project["sequences"] if s["name"] == sequence and any(t.get("clips") for t in s["audio_tracks"])]
    if len(hits) != 1:
        raise ValueError(f"{len(hits)} sequences match {sequence!r} in the saved project; pass its sequence_id")
    return hits[0]


def judge(seq: dict, found: dict, body_from: float, answers: dict, overrides: dict,
          required: dict[str, str], show_end: float | None = None) -> dict:
    """The verdict on one gate run: failed controls, missing answers, the body range."""
    live = {g: r for g, r in found.items() if r["status"] != "retired"}
    failed = [g for g, r in live.items() if not r["passed"] and r["kind"] == "control" and g not in overrides]
    if body_from > MAX_BODY_FROM or (show_end is not None and show_end - body_from < MIN_BODY_S):
        failed.append("body_range")
    missing = sorted(rid for rid in required if not str(answers.get(rid, "")).strip())
    return {"failed": failed, "answers_missing": missing,
            "warned": [g for g, r in live.items() if not r["passed"] and (r["kind"] == "warning" or g in overrides)],
            "body_from": body_from, "show_end": show_end}


def handover(prproj: Path, sequence: str, body_from: float, show_end: float | None, answers: dict,
             overrides: dict, by: str, store: Path = hks_gate_store.STORE, now: dt.datetime | None = None,
             sources: dict | None = None) -> dict:
    from cutdeck.prproj_reader import read_project
    now = now or dt.datetime.now()
    if not all(str(r).strip() for r in overrides.values()):
        raise ValueError("every override needs a written reason")
    project = read_project(prproj)
    seq = find_sequence(project, sequence)
    if sources is None:
        sources = hks_gates.load_sources(seq, hks_gates.MAIN / "transcriber.db",
                                         hks_gates.MAIN / "output/timeline_transcripts/levels")
    found = hks_gates.run(project, seq, sources, body_from, show_end)
    verdict = judge(seq, found, body_from, answers, overrides, do_confirm_rules(), show_end)
    snap = snapshot(Path(prproj), seq["name"], None, now)
    record = {"time": now.isoformat(timespec="seconds"), "guid": seq["guid"], "name": seq["name"],
              "cut_hash": hks_gate_store.cut_hash(seq), "prproj": str(prproj), "snapshot": str(snap),
              **verdict, "overrides": {g: {"reason": r, "by": by} for g, r in overrides.items()},
              "answers": answers,
              "gates": {g: {**{k: r[k] for k in ("value", "line", "direction", "kind", "status", "passed")},
                            "items": r.get("items", [])[:20]} for g, r in found.items()}}
    record["gates"]["body_range"] = {"value": body_from, "line": MAX_BODY_FROM, "direction": "max",
                                     "kind": "control", "status": "kept", "passed": "body_range" not in verdict["failed"]}
    hks_gate_store.append(record, store)
    with OVERRIDES.open("a", encoding="utf-8") as f:
        for gate, reason in overrides.items():
            f.write(json.dumps({"time": record["time"], "gate": gate, "sequence": seq["name"], "guid": seq["guid"],
                                "value": found.get(gate, {}).get("value"), "reason": reason, "by": by},
                               ensure_ascii=False) + "\n")
    return {"status": "fail" if verdict["failed"] or verdict["answers_missing"] else "pass",
            **{k: record[k] for k in ("guid", "name", "cut_hash", "snapshot", "failed", "warned",
                                      "answers_missing", "body_from", "show_end", "overrides")},
            "values": {g: record["gates"][g]["value"] for g in record["failed"]}}


BASELINE = hks_gate_store.STORE.parent / "baseline.json"
_SAVED: dict = {}


def _read_saved(prproj: Path) -> dict:
    """The parsed save, read again only when the file changed (the panel asks every 30 s; a
    5.8 MB save takes 5 s to parse)."""
    from cutdeck import prproj_reader
    key = (str(prproj), prproj.stat().st_mtime_ns)
    if key not in _SAVED:
        _SAVED.clear()
        _SAVED[key] = prproj_reader.read_project(prproj)
    return _SAVED[key]


def status(prproj: Path, live: list[dict] | None = None, store: Path = hks_gate_store.STORE,
           mark_baseline: bool = False, baseline: Path = BASELINE) -> list[dict]:
    """Every sequence of the last save, with its status from the records. ``live`` is the open
    project's sequences ({name, sequence_id}); one missing from the save is ungated, "not saved
    yet". ``mark_baseline`` (at day set-up) records every sequence there now as the day's start;
    after that each row says ``new``: true for a sequence that came later, whoever made it and
    whatever its name or label (the template's GUIDs are not the day's, so it must be the day's)."""
    rows = hks_gate_store.status(_read_saved(Path(prproj)), store)
    saved = {r["guid"] for r in rows}
    for s in live or []:
        if s["sequence_id"] not in saved:
            rows.append({"guid": s["sequence_id"], "name": s["name"], "status": "ungated", "why": "not saved yet"})
    days = json.loads(baseline.read_text(encoding="utf-8")) if baseline.exists() else {}
    if mark_baseline:
        days[str(prproj)] = sorted(r["guid"] for r in rows)
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(json.dumps(days, indent=1), encoding="utf-8")
    start = days.get(str(prproj))
    for r in rows:
        r["new"] = None if start is None else r["guid"] not in start
    return rows
