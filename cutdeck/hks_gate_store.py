"""hks_gate_store.py: the helper's record of every HKS gate run, keyed by sequence and saved cut.

A record says what the gates found on one sequence (its GUID in the saved ``.prproj``) as it was
in one save (``cut_hash``: the tracks and clips the gates read, not the name or the rest of the
file). The panel shows a draft's status only from these records, never from what an agent says:

- ``pass`` / ``fail``: a record matches the sequence's cut in the latest save;
- ``ungated``: no record, the cut changed after the last run (an edit after passing), or the
  record is not signed by the helper.

Records are appended to one JSONL file; the newest record for a (guid, cut_hash) wins. Each is
signed (HMAC) with a key kept outside the repo, so a line written into the file by hand shows as
ungated instead of pass.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

from cutdeck import hks_gates

STORE = hks_gates.MAIN / "output" / "hks_gates" / "records.jsonl"
KEY = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "CutDeck" / "hks_gate.key"
_CUT_KEYS = ("start", "end", "source_in", "source_out", "media_path", "label", "disabled")


def cut_hash(seq: dict) -> str:
    """Hash of what the gates measure: every clip's place, source range, label and enable state.
    A rename, a marker or another sequence's edit leaves it unchanged."""
    tracks = [[[c.get(k) for k in _CUT_KEYS] for c in t.get("clips", [])]
              for t in seq.get("video_tracks", []) + seq.get("audio_tracks", [])]
    return hashlib.sha256(json.dumps(tracks, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _sign(record: dict, key: Path) -> str:
    if not key.exists():
        key.parent.mkdir(parents=True, exist_ok=True)
        key.write_text(secrets.token_hex(32), encoding="ascii")
    body = json.dumps({k: v for k, v in record.items() if k != "sig"}, sort_keys=True, ensure_ascii=False)
    return hmac.new(key.read_text(encoding="ascii").strip().encode(), body.encode(), hashlib.sha256).hexdigest()


def append(record: dict, store: Path = STORE, key: Path | None = None) -> None:
    store.parent.mkdir(parents=True, exist_ok=True)
    with store.open("a", encoding="utf-8") as f:
        f.write(json.dumps({**record, "sig": _sign(record, key or KEY)}, ensure_ascii=False) + "\n")


def records(store: Path = STORE) -> list[dict]:
    if not store.exists():
        return []
    return [json.loads(line) for line in store.read_text(encoding="utf-8").splitlines() if line.strip()]


def status(project: dict, store: Path = STORE, key: Path | None = None) -> list[dict]:
    """One row per sequence in a saved project: its gate status from the signed records alone."""
    latest = {(r["guid"], r["cut_hash"]): r for r in records(store)}
    ran = {r["guid"] for r in latest.values()}
    rows = []
    for seq in project["sequences"]:
        h = cut_hash(seq)
        r = latest.get((seq.get("guid"), h))
        why = None
        if r is None:
            why = "changed after its last gate run" if seq.get("guid") in ran else "never gated"
        elif not hmac.compare_digest(str(r.get("sig", "")), _sign(r, key or KEY)):
            why = "record not signed by the helper"
        if why:
            rows.append({"guid": seq.get("guid"), "name": seq["name"], "cut_hash": h, "status": "ungated", "why": why})
            continue
        rows.append({"guid": seq.get("guid"), "name": seq["name"], "cut_hash": h,
                     "status": "fail" if r["failed"] or r.get("answers_missing") else "pass",
                     "failed": [{"gate": g, "value": r["gates"][g]["value"], "line": r["gates"][g]["line"]}
                                for g in r["failed"]],
                     "warned": [{"gate": g, "value": r["gates"][g]["value"], "items": r["gates"][g].get("items", [])[:6]}
                                for g in r.get("warned", [])],
                     "answers_missing": r.get("answers_missing", []),
                     "overrides": r.get("overrides", {}), "body_from": r.get("body_from"),
                     "checked": r["time"]})
    return rows
