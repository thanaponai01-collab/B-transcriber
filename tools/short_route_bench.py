"""Measure how a Short is derived from a parent sequence, route by route, on a scratch project.

Every Premiere call goes through the helper exactly as an agent's MCP tool does (helper_protocol.ask).
After each call it records wall time and Premiere's process counters (private bytes, working set,
handles, GDI and USER objects); the helper's own command log gives the panel calls behind it.

    python tools/short_route_bench.py --route D --n 5 --parent yt --template "TT template" \
        --pieces pieces.json --out output/short-bench/D-5.jsonl

Routes (see the PR for the numbers):
  D  paste_from per piece into a copy of the template (today's fallback)
  A  make_subsequence of the span, cut_copy to the pieces, arrange into story order, one
     paste_from of the whole result into a copy of the template, temporaries removed
Never saves, never exports; the caller saves the scratch project when it wants a .prproj to read.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cutdeck.helper_protocol import ask  # noqa: E402

PIECE = " (CutDeck piece)"


def premiere_pid() -> int | None:
    for p in psutil.process_iter(["name"]):
        if p.info["name"] == "Adobe Premiere Pro.exe":
            return p.pid
    return None


def counters(pid: int | None) -> dict:
    if pid is None or not psutil.pid_exists(pid):
        return {"alive": False}
    p = psutil.Process(pid)
    mem = p.memory_info()
    handle = ctypes.windll.kernel32.OpenProcess(0x0400 | 0x0010, False, pid)  # QUERY_INFORMATION | VM_READ
    try:
        gdi = ctypes.windll.user32.GetGuiResources(handle, 0)
        user = ctypes.windll.user32.GetGuiResources(handle, 1)
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
    return {"alive": True, "private_mb": round(mem.private / 2**20), "ws_mb": round(mem.rss / 2**20),
            "handles": p.num_handles(), "gdi": gdi, "user": user}


class Bench:
    def __init__(self, out: Path, route: str, n: int):
        self.out, self.route, self.n = out, route, n
        self.pid = premiere_pid()
        self.calls = 0
        out.parent.mkdir(parents=True, exist_ok=True)
        self.log = out.open("a", encoding="utf-8")
        self.row({"event": "baseline", **counters(self.pid), "items": self.items()})

    def row(self, record: dict) -> None:
        self.log.write(json.dumps({"route": self.route, "n": self.n, "t": time.time(), **record}, ensure_ascii=False) + "\n")
        self.log.flush()

    def items(self) -> int | None:
        try:
            project = ask({"type": "premiere", "command": "list_project", "args": {"depth": 9}})["result"]
        except Exception:
            return None
        return sum(1 for _ in _walk(project))

    def __call__(self, command: str, args: dict, step: str = "") -> dict:
        self.calls += 1
        start = time.perf_counter()
        try:
            result, error = ask({"type": "premiere", "command": command, "args": args})["result"], None
        except Exception as exc:  # recorded, then raised: a route stops at its first failure
            result, error = None, str(exc)
        seconds = round(time.perf_counter() - start, 3)
        after = counters(self.pid)
        self.row({"event": "call", "i": self.calls, "command": command, "step": step, "s": seconds,
                  "ok": error is None, "error": error, **after,
                  "items": self.items() if after.get("alive") else None,
                  "summary": _summary(result)})
        print(f"{self.calls:3d} {command:18s} {step:14s} {seconds:7.2f}s {'OK ' if error is None else 'ERR'} "
              f"priv {after.get('private_mb')} MB h {after.get('handles')} gdi {after.get('gdi')} user {after.get('user')}"
              + (f"  {error[:120]}" if error else ""), flush=True)
        if error:
            raise RuntimeError(f"{command} ({step}): {error}")
        return result


def _walk(node):
    for child in (node or {}).get("items") or []:
        yield child
        yield from _walk(child)


def _summary(result):
    if not isinstance(result, dict):
        return None
    return {k: result[k] for k in ("name", "clips", "missing", "unexpected", "left_at_park", "end_ticks", "steps",
                                   "cuts", "splits", "removed", "sequence") if k in result}


def clips(timeline: dict) -> list[list]:
    return sorted([t["id"][0], int(t["id"][1:]), int(c["start_ticks"]), int(c["end_ticks"]), int(c["in_ticks"])]
                  for t in timeline["tracks"] for c in t["clips"])


def plan(parent: dict, pieces: list[tuple[int, int]], at: int) -> list[list]:
    """Where every parent clip inside each piece should sit in the Short, pieces in play order."""
    out = []
    for a, b in pieces:
        for k, n, s, e, i in clips(parent):
            if s < b and e > a:
                lo, hi = max(s, a), min(e, b)
                out.append([k, n, at + lo - a, at + hi - a, i + lo - s])
        at += b - a
    return sorted(out)


def route_d(call, parent, template, short, pieces, at):
    call("duplicate_sequence", {"sequence_name": template, "result_name": short}, "template")
    for j, (a, b) in enumerate(pieces):
        call("paste_from", {"source": parent, "in_ticks": str(a), "out_ticks": str(b), "target": short,
                            "at_ticks": str(at)}, f"piece {j + 1}")
        at += b - a


def route_a(call, parent, template, short, pieces, at, tpf):
    span = (min(a for a, _ in pieces), max(b for _, b in pieces))
    sub = f"{short} span{PIECE}"
    call("make_subsequence", {"sequence": parent, "in_ticks": str(span[0]), "out_ticks": str(span[1]),
                              "result_name": sub}, "subsequence")
    # Cut the span to the pieces (keep_words' engine, with exact frames instead of word pauses).
    kept = sorted((a - span[0], b - span[0]) for a, b in pieces)
    cuts, edge = [], 0
    for a, b in kept:
        if a > edge:
            cuts.append([edge // tpf, a // tpf])
        edge = b
    if edge < span[1] - span[0]:
        cuts.append([edge // tpf, (span[1] - span[0]) // tpf])
    cut = f"{short} cut{PIECE}"
    call("cut_copy", {"sequence_name": sub, "result_name": cut,
                      "cuts": {"ticks_per_frame": str(tpf), "cuts_frames": cuts}}, "cut")
    # Kept pieces now play back to back in time order; arrange puts them in play order.
    where, t = {}, 0
    for a, b in kept:
        where[(a, b)] = (t, t + b - a)
        t += b - a
    order = [where[(a - span[0], b - span[0])] for a, b in pieces]
    source = cut
    if order != sorted(order):
        source = f"{short} order{PIECE}"
        call("arrange", {"sequence": cut, "result_name": source,
                         "blocks": [{"from_ticks": str(f), "to_ticks": str(e)} for f, e in order]}, "arrange")
    call("duplicate_sequence", {"sequence_name": template, "result_name": short}, "template")
    call("paste_from", {"source": source, "in_ticks": "0", "out_ticks": str(t), "target": short,
                        "at_ticks": str(at)}, "paste whole")
    for name in dict.fromkeys([sub, cut, source]):
        call("remove_piece", {"name": name}, "remove temp")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--route", choices=["A", "D"], required=True)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--parent", required=True)
    ap.add_argument("--template", required=True)
    ap.add_argument("--pieces", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--at", type=int, default=0)
    a = ap.parse_args(argv)
    pieces = [(int(p["from_ticks"]), int(p["to_ticks"])) for p in json.loads(a.pieces.read_text())][: a.n]
    short = f"bench {a.route} N{a.n} {time.strftime('%H%M%S')}"
    bench = Bench(a.out, a.route, a.n)
    parent = ask({"type": "premiere", "command": "read_timeline", "args": {"sequence": a.parent}})["result"]
    tpf = int(parent["ticks_per_frame"])
    started = time.perf_counter()
    error = None
    try:
        if a.route == "D":
            route_d(bench, a.parent, a.template, short, pieces, a.at)
        else:
            route_a(bench, a.parent, a.template, short, pieces, a.at, tpf)
    except Exception as exc:
        error = str(exc)
    total = round(time.perf_counter() - started, 2)
    result = {"event": "done", "short": short, "total_s": total, "calls": bench.calls, "error": error,
              **counters(bench.pid)}
    if error is None:
        template = ask({"type": "premiere", "command": "read_timeline", "args": {"sequence": a.template}})["result"]
        got = ask({"type": "premiere", "command": "read_timeline", "args": {"sequence": short}})["result"]
        own = {tuple(c) for c in clips(template)}
        want = plan(parent, pieces, a.at)
        have = [c for c in clips(got) if tuple(c) not in own]
        result.update({"missing": [c for c in want if c not in have][:20], "unexpected": [c for c in have if c not in want][:20],
                       "exact": want == have, "planned_clips": len(want)})
    bench.row(result)
    print(json.dumps(result, ensure_ascii=False)[:2000])
    return 0 if error is None and result.get("exact") else 1


if __name__ == "__main__":
    raise SystemExit(main())
