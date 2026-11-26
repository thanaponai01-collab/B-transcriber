"""Reader cost: load all rules + check referential integrity, one file (A) vs one file per rule (B).

Usage: python bench_readers.py <path to rules.json>
Writes work/bench/{n181,n1810}/ and prints medians. Each round runs in a fresh process,
so "first" is the first load in a new process (OS file cache warm, not a cold disk).
"""
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_a(root):
    return json.loads((root / "rules.json").read_text(encoding="utf-8"))["rules"]


def load_b(root):
    rules = []
    for p in sorted((root / "rules").glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        if r["id"] != p.stem:
            raise ValueError(f"{p.name} holds {r['id']}")
        rules.append(r)
    return rules


def validate(rules):
    ids = [r["id"] for r in rules]
    known = set(ids)
    problems = [f"duplicate {i}" for i in known if ids.count(i) > 1] if len(known) != len(ids) else []
    problems += [f"{r['id']}: superseded_by {r['superseded_by']} unknown"
                 for r in rules if r["superseded_by"] and r["superseded_by"] not in known]
    return problems


def build(src, n_copies):
    full = json.loads(Path(src).read_text(encoding="utf-8"))
    rules = []
    for k in range(n_copies):
        for r in full["rules"]:
            r = dict(r, id=r["id"] + (f"-c{k}" if k else ""))
            if r["superseded_by"] and k:
                r["superseded_by"] += f"-c{k}"
            rules.append(r)
    root = HERE / "work" / "bench" / f"n{len(rules)}"
    (root / "rules").mkdir(parents=True, exist_ok=True)
    doc = {"schema": full["schema"], "stages": full["stages"], "rules": rules}
    (root / "rules.json").write_bytes((json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode())
    for r in rules:
        (root / "rules" / f"{r['id']}.json").write_bytes((json.dumps(r, ensure_ascii=False, indent=1) + "\n").encode())
    return root, len(rules)


def child(root, layout, reps):
    root = Path(root)
    load = load_a if layout == "A" else load_b
    times = []
    for _ in range(reps):
        t = time.perf_counter()
        rules = load(root)
        t_load = time.perf_counter() - t
        problems = validate(rules)
        times.append((t_load, time.perf_counter() - t))
    assert not problems and rules, problems
    print(json.dumps({"n": len(rules), "times": times}))


def main():
    if sys.argv[1] == "--child":
        return child(sys.argv[2], sys.argv[3], int(sys.argv[4]))
    for copies in (1, 10):
        root, n = build(sys.argv[1], copies)
        res = {"A": {"first": [], "warm": [], "validate": []}, "B": {"first": [], "warm": [], "validate": []}}
        for _ in range(7):  # alternate A, B so drift favours neither
            for layout in ("A", "B"):
                out = subprocess.run([sys.executable, __file__, "--child", str(root), layout, "50"],
                                     capture_output=True, text=True, check=True).stdout
                t = json.loads(out)["times"]
                res[layout]["first"].append(t[0][1] * 1e3)
                res[layout]["warm"].append(statistics.median(x[1] for x in t[1:]) * 1e3)
                res[layout]["validate"].append(statistics.median(x[1] - x[0] for x in t[1:]) * 1e3)
        for layout, r in res.items():
            print(f"n={n} {layout}: first {statistics.median(r['first']):.2f} ms "
                  f"[{min(r['first']):.2f}-{max(r['first']):.2f}], warm load+validate "
                  f"{statistics.median(r['warm']):.2f} ms [{min(r['warm']):.2f}-{max(r['warm']):.2f}], "
                  f"validate alone {statistics.median(r['validate']):.3f} ms (7 processes x 50 reps)")


if __name__ == "__main__":
    main()
