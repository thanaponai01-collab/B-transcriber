"""Read the helper's command log (output/premiere/premiere_commands.jsonl and .1) and say where the
calls, the time and the failures went.

    python tools/helper_log.py                      the whole log
    python tools/helper_log.py --since 2026-11-24   from that local date or time on

Failures are grouped into incidents: the same command and error repeating with under GAP_S between
them. One agent waiting on a dead panel makes hundreds of failures but is one incident.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "output/premiere/premiere_commands.jsonl"
GAP_S = 600


def calls(log: Path, since: str = "") -> list[dict]:
    """One dict per finished call: command, caller, start time, seconds, ok, error."""
    starts, out = {}, []
    for path in (log.with_name(log.name + ".1"), log):
        if not path.exists():
            continue
        for line in path.open(encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("event") == "start":
                starts[r["call"]] = r
            elif r.get("event") == "end" and r.get("call") in starts:
                s = starts.pop(r["call"])
                if s["time"] < since:
                    continue
                t0 = datetime.fromisoformat(s["time"])
                out.append({"command": s["command"], "caller": s.get("caller"), "start": t0,
                            "seconds": (datetime.fromisoformat(r["time"]) - t0).total_seconds(),
                            "ok": r.get("ok", False), "error": r.get("error", "")})
    return out


def error_class(error: str) -> str:
    """The error without its specifics: the first sentence, cut at a quote."""
    return error.split(". ")[0].split('"')[0].strip().rstrip(".")[:90]


def incidents(rows: list[dict], gap_s: float = GAP_S) -> list[dict]:
    """Runs of failures with the same command and error class, each under gap_s from the last."""
    open_runs, done = {}, []
    for row in sorted((r for r in rows if not r["ok"]), key=lambda r: r["start"]):
        key = (row["command"], error_class(row["error"]))
        run = open_runs.get(key)
        if run and (row["start"] - run["last"]).total_seconds() <= gap_s:
            run["count"] += 1
            run["last"] = row["start"]
            run["callers"].add(row["caller"])
        else:
            if run:
                done.append(run)
            open_runs[key] = {"command": key[0], "error": key[1], "first": row["start"], "last": row["start"],
                              "count": 1, "callers": {row["caller"]}}
    return sorted(done + list(open_runs.values()), key=lambda r: -r["count"])


def report(rows: list[dict]) -> str:
    if not rows:
        return "No finished calls in the log."
    lines = [f"{len(rows)} calls, {rows[0]['start']:%Y-%m-%d %H:%M} to {rows[-1]['start']:%Y-%m-%d %H:%M}, "
             f"{sum(not r['ok'] for r in rows)} failed", "",
             f"{'command':28} {'n':>5} {'total s':>8} {'p50 s':>7} {'p95 s':>7} {'failed':>6}"]
    by = defaultdict(list)
    for r in rows:
        by[r["command"]].append(r)
    for command, rs in sorted(by.items(), key=lambda kv: -sum(r["seconds"] for r in kv[1])):
        s = sorted(r["seconds"] for r in rs)
        lines.append(f"{command:28} {len(s):5} {sum(s):8.0f} {s[len(s) // 2]:7.2f} {s[int(len(s) * .95)]:7.2f} "
                     f"{sum(not r['ok'] for r in rs):6}")
    lines += ["", f"Failure incidents (same command and error, under {GAP_S} s apart):"]
    for run in incidents(rows):
        callers = ", ".join(sorted(str(c) for c in run["callers"]))
        lines.append(f"{run['count']:5} x {run['command']}: {run['error']}  "
                     f"[{run['first']:%m-%d %H:%M} to {run['last']:%m-%d %H:%M}; caller {callers}]")
    callers = defaultdict(int)
    for r in rows:
        callers[r["caller"]] += 1
    lines += ["", "Calls by caller:"] + [f"{n:6}  {c}" for c, n in sorted(callers.items(), key=lambda kv: -kv[1])]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log", type=Path, default=LOG)
    parser.add_argument("--since", default="", help="local ISO date or time, e.g. 2026-11-24T03:00")
    args = parser.parse_args()
    print(report(calls(args.log, args.since)))


if __name__ == "__main__":
    main()
