"""Save diff minus the command log (#129): surface changes between consecutive .prproj saves
that could be manual edits.

    python -m cutdeck.save_diff SAVE... --log output/premiere/premiere_commands.jsonl
    python -m cutdeck.save_diff SAVE... --log ... --corrections corrections.json

A save's time is the stamp in a Premiere auto-save name (``..._2026-11-22_21-29-15.prproj``),
else the file's mtime. Clips carry no ID that survives a save, so a clip is matched by its full
reader record; a removed and an added clip with the same name on the same track are paired as
one changed clip. A completed write can explain changes in the sequences its arguments name
when the whole call falls between the saves. This is sequence-level attribution.

``--corrections`` is a JSON list written from the day's workflow-log, one entry per spoken
correction: ``{"said": "...", "change": "<id from the report>" | null}``. A correction is found
when its change is one the log does not explain; the trial passes when at least half are.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from cutdeck.prproj_reader import read_project

_AUTOSAVE_STAMP = re.compile(r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.prproj$")
_SEQUENCE_KEYS = ("sequence", "sequence_name", "result_name")


def save_time(path: Path) -> datetime:
    m = _AUTOSAVE_STAMP.search(path.name)
    if m:
        return datetime.strptime(m.group(1), "%Y-%m-%d_%H-%M-%S")
    return datetime.fromtimestamp(path.stat().st_mtime)


def _sequences(project: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for seq in project["sequences"]:
        name, n = seq["name"], 2
        while name in out:  # two sequences may share a name
            name, n = f"{seq['name']} #{n}", n + 1
        out[name] = seq
    return out


def _tracks(seq: dict) -> dict[str, dict]:
    return {f"{kind[0].upper()}{i}": t
            for kind in ("video", "audio") for i, t in enumerate(seq[f"{kind}_tracks"], 1)}


def _canon(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _span(*clips: dict | None) -> tuple[float, float]:
    clips = [c for c in clips if c]
    return min(c["start"] for c in clips), max(c["end"] or c["start"] for c in clips)


def _clip_changes(sequence: str, track: str, before: list[dict], after: list[dict]) -> list[dict]:
    pool = {}
    for c in after:
        pool.setdefault(_canon(c), []).append(c)
    removed = []
    for c in before:
        same = pool.get(_canon(c))
        if same:
            same.pop()
        else:
            removed.append(c)
    added = [c for group in pool.values() for c in group]
    out = []
    for old in removed:
        twins = [c for c in added if c["name"] == old["name"]]
        new = min(twins, key=lambda c: abs(c["start"] - old["start"])) if twins else None
        if new is not None:
            added.remove(new)
        out.append({"kind": "changed" if new else "removed", "before": old, "after": new,
                    "fields": sorted(k for k in old.keys() | (new or {}).keys()
                                     if new and old.get(k) != new.get(k))})
    out += [{"kind": "added", "before": None, "after": c, "fields": []} for c in added]
    for ch in out:
        ch["sequence"], ch["track"] = sequence, track
        ch["start"], ch["end"] = _span(ch["before"], ch["after"])
    return out


def diff(a: dict, b: dict) -> list[dict]:
    """Every change from project ``a`` to project ``b`` (both ``read_project`` output)."""
    seqs_a, seqs_b = _sequences(a), _sequences(b)
    out = []
    for name in seqs_a.keys() | seqs_b.keys():
        if name not in seqs_a or name not in seqs_b:
            out.append({"kind": "sequence", "sequence": name, "track": None, "start": None, "end": None,
                        "fields": ["added" if name in seqs_b else "removed"]})
            continue
        sa, sb = seqs_a[name], seqs_b[name]
        fields = [key for key in ("frame", "markers") if sa.get(key) != sb.get(key)]
        if fields:
            out.append({"kind": "sequence", "sequence": name, "track": None, "start": None, "end": None,
                        "fields": fields, "before": {key: sa.get(key) for key in fields},
                        "after": {key: sb.get(key) for key in fields}})
        tracks_a, tracks_b = _tracks(sa), _tracks(sb)
        for track in sorted(tracks_a.keys() | tracks_b.keys()):
            ta, tb = tracks_a.get(track), tracks_b.get(track)
            if ta is None or tb is None:
                fields = ["added" if ta is None else "removed"]
            else:
                fields = sorted(k for k in ta.keys() | tb.keys() if k != "clips" and ta.get(k) != tb.get(k))
            if fields:
                out.append({"kind": "track", "sequence": name, "track": track, "start": None, "end": None,
                            "fields": fields})
            out += _clip_changes(name, track, (ta or {"clips": []})["clips"], (tb or {"clips": []})["clips"])
    for ch in out:
        ch["sequence_name"] = (seqs_b.get(ch["sequence"]) or seqs_a[ch["sequence"]])["name"]
    return out


def read_log(path: Path) -> list[dict]:
    """Read successful non-read calls, with their start and completion times."""
    records = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    ends = {r["call"]: r for r in records if r["event"] == "end" and r.get("ok") is True}
    out = []
    for start in records:
        if start["event"] != "start" or start.get("hint") == "read":
            continue
        end = ends.get(start.get("call"))
        if end is not None:
            out.append({**start, "time": _local_time(start["time"]), "end_time": _local_time(end["time"])})
    return out


def _local_time(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp).astimezone().replace(tzinfo=None)


def named_sequences(args) -> set[str]:
    """The sequences explicitly named in the command arguments."""
    if not isinstance(args, dict):
        return set()
    names = {args[k] for k in _SEQUENCE_KEYS if isinstance(args.get(k), str)}
    multiple = args.get("sequences")
    if isinstance(multiple, list):
        names.update(s for s in multiple if isinstance(s, str))
    return names


def explains(command: dict, change: dict) -> bool:
    return change["sequence_name"] in named_sequences(command.get("args"))


def report(saves: list[Path], commands: list[dict]) -> list[dict]:
    saves = sorted(saves, key=save_time)
    intervals, ids = [], 0
    before = read_project(saves[0])
    for prev, path in zip(saves, saves[1:]):
        after = read_project(path)
        t0, t1 = save_time(prev), save_time(path)
        in_window = [c for c in commands if t0 <= c["time"] <= c["end_time"] < t1]
        changes = diff(before, after)
        for ch in changes:
            ids += 1
            ch["id"] = f"c{ids}"
            ch["explained_by"] = [f"{c['command']}@{c['time']:%H:%M:%S}" for c in in_window if explains(c, ch)]
        intervals.append({"from": prev.name, "to": path.name, "from_time": t0.isoformat(), "to_time": t1.isoformat(),
                          "commands": [f"{c['command']}@{c['time']:%H:%M:%S}" for c in in_window],
                          "changes": changes})
        before = after
    return intervals


def score(intervals: list[dict], corrections: list[dict]) -> dict:
    user = {ch["id"] for iv in intervals for ch in iv["changes"] if not ch["explained_by"]}
    found = [c for c in corrections if c.get("change") in user]
    claimed = {c.get("change") for c in corrections}
    return {"spoken": len(corrections), "found": len(found),
            "passed": bool(corrections) and 2 * len(found) >= len(corrections),
            "missed": [c["said"] for c in corrections if c not in found],
            "unclaimed_user_changes": sorted(user - claimed, key=lambda i: int(i[1:]))}


def _describe(ch: dict) -> str:
    where = f"{ch['sequence']} {ch['track'] or ''}".strip()
    if ch["kind"] in ("sequence", "track"):
        what = f"{ch['kind']} {', '.join(ch['fields'])}"
    else:
        name = (ch["after"] or ch["before"])["name"]
        what = f"{ch['kind']} {name} {ch['start']:.2f}-{ch['end']:.2f}s"
        if ch["fields"]:
            what += f" ({', '.join(ch['fields'])})"
    by = f"  [log: {', '.join(ch['explained_by'])}]" if ch["explained_by"] else "  [unattributed]"
    return f"  {ch['id']} {where}: {what}{by}"


def main(argv: list[str] | None = None) -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("saves", nargs="+", type=Path, help="two or more saves of one project")
    parser.add_argument("--log", type=Path, help="premiere_commands.jsonl (none: nothing is explained)")
    parser.add_argument("--corrections", type=Path, help="JSON list of {said, change} to score")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # clip names carry Thai and emoji
    if len(args.saves) < 2:
        parser.error("need at least two saves")
    intervals = report(args.saves, read_log(args.log) if args.log else [])
    if args.json:
        print(json.dumps(intervals, ensure_ascii=False, indent=1, default=str))
    else:
        for iv in intervals:
            print(f"{iv['from_time']} -> {iv['to_time']}: {len(iv['changes'])} changes, "
                  f"{len(iv['commands'])} logged commands")
            for ch in iv["changes"]:
                print(_describe(ch))
    if args.corrections:
        print(json.dumps(score(intervals, json.loads(args.corrections.read_text("utf-8"))),
                         ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
